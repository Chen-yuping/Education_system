from django.core.management.base import BaseCommand
from learning.models import Dataset


class Command(BaseCommand):
    help = '初始化数据集数据'

    def handle(self, *args, **options):
        datasets_data = [
            {
                'name': 'FrcSub',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 1,
            },
            {
                'name': 'Math1',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 2,
            },
            {
                'name': 'Math2',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 3,
            },
            {
                'name': 'AAAI_2023',
                'student_info': 'False',
                'exercise_info': 'masked text',
                'knowledge_relation': 'tree',
                'doc_link': '#',
                'download_link': '#',
                'order': 4,
            },
            {
                'name': 'ASSISTment_2009-2010',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 5,
            },
            {
                'name': 'ASSISTment_2012-2013',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 6,
            },
            {
                'name': 'ASSISTment_2015-2016',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 7,
            },
            {
                'name': 'ASSISTment_2017',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 8,
            },
            {
                'name': 'Algebra_2005-2006',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 9,
            },
            {
                'name': 'Algebra_2006-2007',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 10,
            },
            {
                'name': 'Bridge2Algebra_2006-2007',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 11,
            },
            {
                'name': 'Junyi',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'tree and prerequisite',
                'doc_link': '#',
                'download_link': '#',
                'order': 12,
            },
            {
                'name': 'EdNet_KT1',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 13,
            },
            {
                'name': 'Eedi_2020_Task1&2',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'tree',
                'doc_link': '#',
                'download_link': '#',
                'order': 14,
            },
            {
                'name': 'Eedi_2020_Task3&4',
                'student_info': 'True',
                'exercise_info': 'images',
                'knowledge_relation': 'tree',
                'doc_link': '#',
                'download_link': '#',
                'order': 15,
            },
            {
                'name': 'Statics - Fall 2011',
                'student_info': 'False',
                'exercise_info': 'web pages',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 16,
            },
            {
                'name': 'MoocRadar',
                'student_info': 'True',
                'exercise_info': 'True',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'paper_link': '#',
                'order': 17,
            },
            {
                'name': 'MoocCubeX',
                'student_info': 'True',
                'exercise_info': 'True',
                'knowledge_relation': 'prerequisite',
                'paper_link': '#',
                'order': 18,
            },
            {
                'name': 'SLP',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'paper_link': '#',
                'order': 19,
            },
            {
                'name': 'MooPer',
                'student_info': 'True',
                'exercise_info': 'True',
                'knowledge_relation': 'tree',
                'paper_link': '#',
                'order': 20,
            },
            {
                'name': 'XES3G5M',
                'student_info': 'False',
                'exercise_info': 'True',
                'knowledge_relation': 'tree',
                'paper_link': '#',
                'order': 21,
            },
            {
                'name': 'Simulated-5',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'doc_link': '#',
                'download_link': '#',
                'order': 22,
            },
            {
                'name': 'PISA2015',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'download_link': '#',
                'order': 23,
            },
            {
                'name': 'PISA2018',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'download_link': '#',
                'order': 24,
            },
            {
                'name': 'PISA2022',
                'student_info': 'True',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'download_link': '#',
                'order': 25,
            },
            {
                'name': 'SingPAD',
                'student_info': 'False',
                'exercise_info': 'False',
                'knowledge_relation': 'False',
                'paper_link': '#',
                'download_link': '#',
                'order': 26,
            },
        ]

        # 清空现有数据
        Dataset.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('已清空现有数据集'))

        # 创建新数据
        for data in datasets_data:
            dataset, created = Dataset.objects.get_or_create(
                name=data['name'],
                defaults={
                    'student_info': data.get('student_info', ''),
                    'exercise_info': data.get('exercise_info', ''),
                    'knowledge_relation': data.get('knowledge_relation', ''),
                    'doc_link': data.get('doc_link', ''),
                    'download_link': data.get('download_link', ''),
                    'paper_link': data.get('paper_link', ''),
                    'order': data.get('order', 0),
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✓ 创建数据集: {data["name"]}'))
            else:
                self.stdout.write(self.style.WARNING(f'⊘ 数据集已存在: {data["name"]}'))

        self.stdout.write(self.style.SUCCESS('✓ 数据集初始化完成！'))
