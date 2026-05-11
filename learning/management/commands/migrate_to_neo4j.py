"""
将MySQL中现有的KnowledgePoint和KnowledgeGraph数据迁移到Neo4j
用法: python manage.py migrate_to_neo4j [--subject 科目名称]
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from learning.models import Subject, KnowledgePoint, KnowledgeGraph
import os


def _get_neo4j_driver():
    neo4j_uri = os.environ.get('NEO4J_URI') or getattr(settings, 'NEO4J_URI', None)
    neo4j_user = os.environ.get('NEO4J_USER') or getattr(settings, 'NEO4J_USER', 'neo4j')
    neo4j_password = os.environ.get('NEO4J_PASSWORD') or getattr(settings, 'NEO4J_PASSWORD', '')

    if not neo4j_uri:
        return None, "未配置Neo4j连接信息（NEO4J_URI）"

    uri = neo4j_uri.replace('neo4j+s://', 'neo4j+ssc://').replace('bolt+s://', 'bolt+ssc://')

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(neo4j_user, neo4j_password))
        # 验证连接
        with driver.session() as session:
            session.run("RETURN 1").consume()
        return driver, None
    except ImportError:
        return None, "请先安装 neo4j 驱动: pip install neo4j"
    except Exception as e:
        return None, f"Neo4j连接失败: {e}"


class Command(BaseCommand):
    help = "将MySQL中的知识点和关系数据迁移到Neo4j"

    def add_arguments(self, parser):
        parser.add_argument('--subject', type=str, help='只迁移指定科目（按名称精确匹配）')

    def handle(self, *args, **options):
        driver, error = _get_neo4j_driver()
        if error:
            raise CommandError(error)

        self.stdout.write(self.style.SUCCESS("已连接到 Neo4j"))

        # 筛选科目
        subjects = Subject.objects.all()
        if options['subject']:
            subjects = subjects.filter(name=options['subject'])

        total_kp = 0
        total_rel = 0

        for subject in subjects:
            self.stdout.write(f"\n处理科目: {subject.name}")

            # 迁移知识点节点
            kps = KnowledgePoint.objects.filter(subject=subject)
            with driver.session() as session:
                kp_count = 0
                for kp in kps:
                    uid = f"{subject.name}::{kp.name}"
                    session.run(
                        """MERGE (c:Concept {uid: $uid})
                           SET c.name = $name, c.type = $type,
                               c.subject = $subject, c.kp_id = $kp_id""",
                        uid=uid, name=kp.name, type="概念", subject=subject.name, kp_id=kp.id
                    ).consume()
                    kp_count += 1
                total_kp += kp_count
                self.stdout.write(f"  知识点: {kp_count} 个")

                # 迁移关系
                rels = KnowledgeGraph.objects.filter(subject=subject)
                rel_count = 0
                for rel in rels:
                    s_uid = f"{subject.name}::{rel.source.name}"
                    o_uid = f"{subject.name}::{rel.target.name}"
                    session.run(
                        """MATCH (a:Concept {uid: $s_uid})
                           MATCH (b:Concept {uid: $o_uid})
                           MERGE (a)-[r:关联]->(b)
                           SET r.type = '关联'""",
                        s_uid=s_uid, o_uid=o_uid
                    ).consume()
                    rel_count += 1
                total_rel += rel_count
                self.stdout.write(f"  关系: {rel_count} 条")

        driver.close()
        self.stdout.write(self.style.SUCCESS(
            f"\n迁移完成！共处理 {total_kp} 个知识点，{total_rel} 条关系"
        ))
