"""
将MySQL中现有的KnowledgePoint和KnowledgeGraph数据迁移到Neo4j
用法: python manage.py migrate_to_neo4j [--subject 科目名称]
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from learning.models import Subject, KnowledgePoint, KnowledgeGraph
import os


class Command(BaseCommand):
    help = "将MySQL中的知识点和关系数据迁移到Neo4j"

    def add_arguments(self, parser):
        parser.add_argument('--subject', type=str, help='只迁移指定科目（按名称精确匹配）')

    def handle(self, *args, **options):
        neo4j_uri = os.environ.get('NEO4J_URI') or getattr(settings, 'NEO4J_URI', None)
        neo4j_user = os.environ.get('NEO4J_USER') or getattr(settings, 'NEO4J_USER', 'neo4j')
        neo4j_password = os.environ.get('NEO4J_PASSWORD') or getattr(settings, 'NEO4J_PASSWORD', '')

        if not neo4j_uri:
            raise CommandError("未配置Neo4j连接信息（NEO4J_URI）")

        try:
            from py2neo import Graph, Node, Relationship
        except ImportError:
            raise CommandError("请先安装 py2neo: pip install py2neo")

        graph = Graph(neo4j_uri, auth=(neo4j_user, neo4j_password))
        graph.run("RETURN 1")
        self.stdout.write(self.style.SUCCESS(f"已连接到 Neo4j: {neo4j_uri}"))

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
            kp_count = 0
            for kp in kps:
                uid = f"{subject.name}::{kp.name}"
                node = Node("Concept",
                            uid=uid,
                            name=kp.name,
                            type="概念",
                            subject=subject.name,
                            kp_id=kp.id)
                graph.merge(node, "Concept", "uid")
                kp_count += 1
            total_kp += kp_count
            self.stdout.write(f"  知识点: {kp_count} 个")

            # 迁移关系
            rels = KnowledgeGraph.objects.filter(subject=subject)
            rel_count = 0
            for rel in rels:
                s_uid = f"{subject.name}::{rel.source.name}"
                o_uid = f"{subject.name}::{rel.target.name}"
                graph.run(
                    """MATCH (a:Concept {uid: $s_uid})
                       MATCH (b:Concept {uid: $o_uid})
                       MERGE (a)-[r:关联]->(b)
                       SET r.type = '关联'""",
                    s_uid=s_uid, o_uid=o_uid
                )
                rel_count += 1
            total_rel += rel_count
            self.stdout.write(f"  关系: {rel_count} 条")

        self.stdout.write(self.style.SUCCESS(
            f"\n迁移完成！共处理 {total_kp} 个知识点，{total_rel} 条关系"
        ))
