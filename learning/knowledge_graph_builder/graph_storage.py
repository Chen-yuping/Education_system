"""
知识图谱存储模块
将抽取的三元组存入Django模型（KnowledgePoint, KnowledgeGraph）和Neo4j
"""
import os
import sys
import io
import re

_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout

from django.db import transaction
from django.conf import settings
from learning.models import Subject, KnowledgePoint, KnowledgeGraph


def _sanitize_rel_type(rel_type: str) -> str:
    """将关系类型转换为合法的Cypher关系类型名"""
    sanitized = rel_type.upper().replace(" ", "_").replace("-", "_")
    return re.sub(r'[^A-Z0-9_]', '_', sanitized)


def _get_neo4j_driver():
    """创建Neo4j驱动实例（开发环境下跳过SSL证书验证）"""
    neo4j_uri = os.environ.get('NEO4J_URI') or getattr(settings, 'NEO4J_URI', None)
    neo4j_user = os.environ.get('NEO4J_USER') or getattr(settings, 'NEO4J_USER', 'neo4j')
    neo4j_password = os.environ.get('NEO4J_PASSWORD') or getattr(settings, 'NEO4J_PASSWORD', '')

    if not neo4j_uri:
        return None

    # 开发环境下使用+ssc方案绕过SSL证书验证
    uri = neo4j_uri.replace('neo4j+s://', 'neo4j+ssc://').replace('bolt+s://', 'bolt+ssc://')

    from neo4j import GraphDatabase
    return GraphDatabase.driver(uri, auth=(neo4j_user, neo4j_password))


def save_to_django(triples: list, subject: Subject, relation_source: str = '教材') -> dict:
    kp_count = 0
    rel_count = 0

    entity_map = {}
    created_kps = []
    created_rels = []

    all_entity_names = set()
    for t in triples:
        all_entity_names.add(t["subject"])
        all_entity_names.add(t["object"])

    print(f"[INFO] 准备存储 {len(all_entity_names)} 个知识点...")

    with transaction.atomic():
        for name in all_entity_names:
            if not name.strip():
                continue
            kp, created = KnowledgePoint.objects.get_or_create(
                subject=subject,
                name=name,
            )
            # 更新来源字段，使按来源过滤（教材/教案/课件）能正确匹配
            if relation_source not in kp.sources.split(','):
                kp.sources = (kp.sources + ',' + relation_source) if kp.sources else relation_source
                kp.save(update_fields=['sources'])
            entity_map[name] = kp
            if created:
                kp_count += 1
                created_kps.append(kp)

        seen_pairs = set()
        for t in triples:
            subj_name = t["subject"]
            obj_name = t["object"]
            if not subj_name.strip() or not obj_name.strip():
                continue

            pair = (subj_name, obj_name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            subj_kp = entity_map.get(subj_name)
            obj_kp = entity_map.get(obj_name)
            if not subj_kp or not obj_kp:
                continue

            rel_type = t.get("predicate", "关联")
            if rel_type not in dict(KnowledgeGraph.RELATION_CHOICES):
                rel_type = "关联"

            kg, created = KnowledgeGraph.objects.get_or_create(
                subject=subject,
                source=subj_kp,
                target=obj_kp,
                relation_source=relation_source,
                defaults={"relationship_type": rel_type},
            )
            if created:
                rel_count += 1
                created_rels.append(kg)
            elif KnowledgeGraph.objects.filter(
                subject=subject, source=subj_kp, target=obj_kp, relation_source=relation_source
            ).exclude(relationship_type=rel_type).exists():
                KnowledgeGraph.objects.filter(
                    subject=subject, source=subj_kp, target=obj_kp, relation_source=relation_source
                ).update(relationship_type=rel_type)

    print(f"[INFO] 新增 {kp_count} 个知识点，{rel_count} 个关系")
    print(f"[INFO] 科目共 {len(all_entity_names)} 个知识点，{len(seen_pairs)} 个关系")

    return {"kp_count": kp_count, "rel_count": rel_count, "entity_map": entity_map,
            "created_kps": created_kps, "created_rels": created_rels}


def save_to_neo4j(triples: list, subject_name: str, entity_map: dict = None):
    driver = _get_neo4j_driver()
    if driver is None:
        print("[WARN] 未配置Neo4j连接信息，跳过图谱存储")
        return False

    try:
        entity_names = set()
        for t in triples:
            entity_names.add((t["subject"], t.get("sub_type", "概念")))
            entity_names.add((t["object"], t.get("obj_type", "概念")))

        with driver.session() as session:
            for name, etype in entity_names:
                kp_id = entity_map.get(name).id if entity_map and entity_map.get(name) else None
                uid = f"{subject_name}::{name}"
                session.run(
                    """MERGE (c:Concept {uid: $uid})
                       SET c.name = $name, c.type = $type,
                           c.subject = $subject, c.kp_id = $kp_id""",
                    uid=uid, name=name, type=etype, subject=subject_name, kp_id=kp_id
                ).consume()

            count = 0
            seen_pairs = set()
            for t in triples:
                s_name = t["subject"]
                o_name = t["object"]
                pair = (s_name, o_name)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                s_uid = f"{subject_name}::{s_name}"
                o_uid = f"{subject_name}::{o_name}"
                rel_type_str = _sanitize_rel_type(t.get("predicate", "关联"))

                session.run(
                    f"""MATCH (a:Concept {{uid: $s_uid}})
                        MATCH (b:Concept {{uid: $o_uid}})
                        MERGE (a)-[r:{rel_type_str}]->(b)
                        SET r.type = $rel_type2""",
                    s_uid=s_uid, o_uid=o_uid, rel_type2=rel_type_str
                ).consume()
                count += 1

        print(f"[INFO] Neo4j图谱构建完成！共导入 {count} 条关系。")
        return True

    except Exception as e:
        print(f"[WARN] Neo4j存储失败: {e}")
        import traceback
        traceback.print_exc()
        print("   Django模型存储已完成，不影响系统使用")
        return False
    finally:
        driver.close()


def get_neo4j_graph(subject_name: str) -> dict:
    """从Neo4j查询指定科目的知识图谱数据，返回与MySQL API一致的格式"""
    driver = _get_neo4j_driver()
    if driver is None:
        return None

    try:
        with driver.session() as session:
            result = session.run(
                """MATCH (a:Concept {subject: $subject_name})-[r]->(b:Concept {subject: $subject_name})
                   RETURN a.uid AS source_uid, a.name AS source_name, a.kp_id AS source_kp_id,
                          b.uid AS target_uid, b.name AS target_name, b.kp_id AS target_kp_id,
                          type(r) AS rel_type, id(r) AS rel_id""",
                subject_name=subject_name
            )
            records = list(result)

        nodes_dict = {}
        links = []

        for row in records:
            for prefix in ['source', 'target']:
                uid = row[f'{prefix}_uid']
                if uid not in nodes_dict:
                    nodes_dict[uid] = {
                        'id': row[f'{prefix}_kp_id'] or hash(uid),
                        'name': row[f'{prefix}_name'],
                    }

            links.append({
                'source': row['source_kp_id'] or hash(row['source_uid']),
                'target': row['target_kp_id'] or hash(row['target_uid']),
                'type': 'unidirectional',
                'arrow': True,
            })

        nodes = list(nodes_dict.values())

        return {
            'nodes': nodes,
            'links': links,
            'node_count': len(nodes),
            'link_count': len(links),
        }

    except Exception as e:
        print(f"[WARN] Neo4j查询失败: {e}")
        return None
    finally:
        driver.close()
