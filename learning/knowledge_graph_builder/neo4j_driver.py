"""
Neo4j 连接与关系操作核心模块
======================================================================
职责（严格遵守双库分工）：
  - MySQL  : 知识点实体的唯一真相源（KnowledgePoint），本模块不写实体业务字段
  - Neo4j  : 知识点之间「关系」的图存储，节点仅作关系的锚点（携带 kp_id 回指 MySQL）

设计要点：
  - 单例驱动：进程内复用同一个 GraphDatabase.driver（线程安全，内置连接池）
  - 容错优先：Neo4j 不可用时所有方法静默降级，绝不影响 MySQL 主流程
  - 节点 uid = "<subject>::<name>"，与历史 migrate_to_neo4j 命令保持一致
"""
import os
import re
import threading

from django.conf import settings

try:
    from neo4j import GraphDatabase
    _NEO4J_AVAILABLE = True
except ImportError:  # 未安装驱动时整体降级
    GraphDatabase = None
    _NEO4J_AVAILABLE = False


# ====================== 单例驱动 ======================
_driver = None
_driver_lock = threading.Lock()


def _build_uri(raw_uri: str) -> str:
    """开发环境绕过 SSL 证书校验（与项目既有写法一致）"""
    return raw_uri.replace('neo4j+s://', 'neo4j+ssc://').replace('bolt+s://', 'bolt+ssc://')


def get_driver():
    """返回进程级单例驱动；未配置或不可用时返回 None（调用方负责降级）"""
    global _driver
    if not _NEO4J_AVAILABLE:
        return None

    if _driver is not None:
        return _driver

    with _driver_lock:
        if _driver is not None:
            return _driver

        uri = os.environ.get('NEO4J_URI') or getattr(settings, 'NEO4J_URI', None)
        if not uri:
            return None
        user = os.environ.get('NEO4J_USER') or getattr(settings, 'NEO4J_USER', 'neo4j')
        password = os.environ.get('NEO4J_PASSWORD') or getattr(settings, 'NEO4J_PASSWORD', '')

        try:
            _driver = GraphDatabase.driver(_build_uri(uri), auth=(user, password))
            _driver.verify_connectivity()
        except Exception as e:
            print(f"[WARN] Neo4j 连接失败，关系图谱降级为仅 MySQL：{e}")
            _driver = None
        return _driver


def close_driver():
    """进程退出/测试清理时调用"""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        finally:
            _driver = None


def is_available() -> bool:
    return get_driver() is not None


# ====================== 工具函数 ======================
def make_uid(subject_name: str, kp_name: str) -> str:
    """节点全局唯一标识：科目内按名称唯一"""
    return f"{subject_name}::{kp_name}"


def sanitize_rel_type(rel_type: str) -> str:
    """中文/任意关系名 -> 合法 Cypher 关系标签。空值兜底为 RELATED"""
    if not rel_type:
        return "RELATED"
    s = re.sub(r'[^A-Z0-9_]', '_', rel_type.upper().replace(" ", "_").replace("-", "_"))
    return s or "RELATED"


# ====================== 核心关系操作 ======================
def upsert_relation(subject_name, source_name, target_name, rel_type,
                    source_kp_id=None, target_kp_id=None, relation_source='教材'):
    """
    写入/更新一条关系（含两端锚节点）。Neo4j 只存关系，不重复存知识点业务数据。
    使用 MERGE 实现幂等：同一对节点 + 同一关系标签不会重复建边。
    """
    driver = get_driver()
    if driver is None:
        return False

    s_uid = make_uid(subject_name, source_name)
    o_uid = make_uid(subject_name, target_name)
    label = sanitize_rel_type(rel_type)

    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (a:Concept {uid: $s_uid})
                  SET a.name = $s_name, a.subject = $subject, a.kp_id = $s_kp_id
                MERGE (b:Concept {uid: $o_uid})
                  SET b.name = $o_name, b.subject = $subject, b.kp_id = $o_kp_id
                MERGE (a)-[r:`%s`]->(b)
                  SET r.type = $rel_type, r.relation_source = $relation_source
                """ % label,
                s_uid=s_uid, o_uid=o_uid, subject=subject_name,
                s_name=source_name, o_name=target_name,
                s_kp_id=source_kp_id, o_kp_id=target_kp_id,
                rel_type=rel_type, relation_source=relation_source,
            ).consume()
        return True
    except Exception as e:
        print(f"[WARN] Neo4j 写入关系失败（已降级）：{e}")
        return False


def sync_relations(triples, subject_name, entity_map=None):
    """
    批量同步一组三元组的关系到 Neo4j（供构建管线 dual-write 调用）。
    triples: [{"subject","object","predicate", ...}]
    entity_map: {name: KnowledgePoint}，用于把 kp_id 写入节点便于回指 MySQL
    返回成功写入的关系条数。
    """
    driver = get_driver()
    if driver is None:
        return 0

    def _kp_id(name):
        kp = entity_map.get(name) if entity_map else None
        return kp.id if kp else None

    count = 0
    seen = set()
    try:
        with driver.session() as session:
            for t in triples:
                s_name, o_name = t.get("subject", ""), t.get("object", "")
                if not s_name.strip() or not o_name.strip():
                    continue
                pair = (s_name, o_name)
                if pair in seen:
                    continue
                seen.add(pair)

                label = sanitize_rel_type(t.get("predicate", "关联"))
                session.run(
                    """
                    MERGE (a:Concept {uid: $s_uid})
                      SET a.name = $s_name, a.subject = $subject, a.kp_id = $s_kp_id
                    MERGE (b:Concept {uid: $o_uid})
                      SET b.name = $o_name, b.subject = $subject, b.kp_id = $o_kp_id
                    MERGE (a)-[r:`%s`]->(b)
                      SET r.type = $rel_type
                    """ % label,
                    s_uid=make_uid(subject_name, s_name),
                    o_uid=make_uid(subject_name, o_name),
                    subject=subject_name,
                    s_name=s_name, o_name=o_name,
                    s_kp_id=_kp_id(s_name), o_kp_id=_kp_id(o_name),
                    rel_type=t.get("predicate", "关联"),
                ).consume()
                count += 1
        print(f"[INFO] Neo4j 关系镜像完成，共 {count} 条")
    except Exception as e:
        print(f"[WARN] Neo4j 批量同步失败（已降级，不影响 MySQL）：{e}")
    return count


def query_relations(subject_names=None):
    """
    查询关系。subject_names 为空 -> 全部；否则按科目列表过滤。
    返回 [{source_kp_id, source_name, source_subject, target_kp_id, target_name,
           target_subject, rel_type, relation_source}]
    """
    driver = get_driver()
    if driver is None:
        return []

    if subject_names:
        cypher = """
            MATCH (a:Concept)-[r]->(b:Concept)
            WHERE a.subject IN $subjects AND b.subject IN $subjects
            RETURN a.kp_id AS s_id, a.name AS s_name, a.subject AS s_sub,
                   b.kp_id AS t_id, b.name AS t_name, b.subject AS t_sub,
                   r.type AS rel_type, r.relation_source AS rel_src
        """
        params = {"subjects": list(subject_names)}
    else:
        cypher = """
            MATCH (a:Concept)-[r]->(b:Concept)
            RETURN a.kp_id AS s_id, a.name AS s_name, a.subject AS s_sub,
                   b.kp_id AS t_id, b.name AS t_name, b.subject AS t_sub,
                   r.type AS rel_type, r.relation_source AS rel_src
        """
        params = {}

    try:
        with driver.session() as session:
            rows = session.run(cypher, **params)
            return [{
                "source_kp_id": r["s_id"], "source_name": r["s_name"], "source_subject": r["s_sub"],
                "target_kp_id": r["t_id"], "target_name": r["t_name"], "target_subject": r["t_sub"],
                "rel_type": r["rel_type"], "relation_source": r["rel_src"],
            } for r in rows]
    except Exception as e:
        print(f"[WARN] Neo4j 查询失败：{e}")
        return []


def delete_relation(subject_name, source_name, target_name):
    """删除指定方向的关系边（节点保留，避免误删其它关系的锚点）"""
    driver = get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (a:Concept {uid: $s_uid})-[r]->(b:Concept {uid: $o_uid})
                DELETE r
                """,
                s_uid=make_uid(subject_name, source_name),
                o_uid=make_uid(subject_name, target_name),
            ).consume()
        return True
    except Exception as e:
        print(f"[WARN] Neo4j 删除关系失败：{e}")
        return False
