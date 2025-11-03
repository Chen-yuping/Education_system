import os
import django
import random
from datetime import datetime, timedelta

# 设置了Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
django.setup()

from django.contrib.auth import get_user_model
from accounts.models import User, StudentProfile, TeacherProfile
from learning.models import (
    Subject, KnowledgePoint, Exercise, Choice,
    QMatrix, AnswerLog, StudentDiagnosis
)


def create_demo_users():
    """创建演示用户数据"""
    User = get_user_model()

    # 创建演示教师
    demo_teacher, created = User.objects.get_or_create(
        username='demo_teacher',
        defaults={
            'email': 'demo_teacher@school.com',
            'user_type': 'teacher',
            'first_name': '张',
            'last_name': '老师'
        }
    )
    if created:
        demo_teacher.set_password('demo123')
        demo_teacher.save()
        # 创建教师档案
        TeacherProfile.objects.create(
            user=demo_teacher,
            subject='数学',
            school='演示中学'
        )
        print("创建演示教师: demo_teacher")

    # 创建演示学生
    demo_student, created = User.objects.get_or_create(
        username='demo_student',
        defaults={
            'email': 'demo_student@school.com',
            'user_type': 'student',
            'first_name': '李',
            'last_name': '同学'
        }
    )
    if created:
        demo_student.set_password('demo123')
        demo_student.save()
        # 创建学生档案
        StudentProfile.objects.create(
            user=demo_student,
            grade='高一',
            school='演示中学'
        )
        print("创建演示学生: demo_student")

    # 创建额外学生用于丰富数据
    extra_students_data = [
        {'username': 'student_wang', 'first_name': '王', 'last_name': '同学', 'grade': '高一'},
        {'username': 'student_zhao', 'first_name': '赵', 'last_name': '同学', 'grade': '高二'},
        {'username': 'student_liu', 'first_name': '刘', 'last_name': '同学', 'grade': '高一'},
        {'username': 'student_chen', 'first_name': '陈', 'last_name': '同学', 'grade': '高三'},
    ]

    extra_students = []
    for data in extra_students_data:
        student, created = User.objects.get_or_create(
            username=data['username'],
            defaults={
                'email': f'{data["username"]}@school.com',
                'user_type': 'student',
                'first_name': data['first_name'],
                'last_name': data['last_name']
            }
        )
        if created:
            student.set_password('demo123')
            student.save()
            StudentProfile.objects.create(
                user=student,
                grade=data['grade'],
                school='演示中学'
            )
            extra_students.append(student)
            print(f"创建学生: {student.username}")

    return demo_teacher, demo_student, extra_students


def create_subjects():
    """创建科目数据"""
    subjects_data = [
        {'name': '数学', 'description': '基础数学知识，包括代数、几何、函数等内容'},
        {'name': '物理', 'description': '物理学基础知识，力学、电磁学、光学等'},
        {'name': '英语', 'description': '英语语言学习，语法、词汇、阅读等'},
        {'name': '化学', 'description': '化学基础知识，元素、反应、有机化学等'},
    ]

    subjects = []
    for data in subjects_data:
        subject, created = Subject.objects.get_or_create(
            name=data['name'],
            defaults={'description': data['description']}
        )
        subjects.append(subject)
        print(f"创建科目: {subject.name}")

    return subjects


def create_knowledge_points(subjects):
    """创建知识点数据"""
    knowledge_points_data = {
        '数学': [
            {'name': '代数基础', 'level': 1, 'children': [
                {'name': '一元一次方程', 'level': 1},
                {'name': '二元一次方程组', 'level': 2},
                {'name': '不等式', 'level': 2},
                {'name': '多项式', 'level': 2},
            ]},
            {'name': '几何基础', 'level': 1, 'children': [
                {'name': '平面几何', 'level': 2},
                {'name': '立体几何', 'level': 3},
                {'name': '三角函数', 'level': 3},
                {'name': '相似三角形', 'level': 2},
            ]},
            {'name': '函数', 'level': 2, 'children': [
                {'name': '一次函数', 'level': 2},
                {'name': '二次函数', 'level': 3},
                {'name': '指数函数', 'level': 3},
                {'name': '对数函数', 'level': 3},
            ]},
        ],
        '物理': [
            {'name': '力学', 'level': 1, 'children': [
                {'name': '牛顿定律', 'level': 2},
                {'name': '动量守恒', 'level': 3},
                {'name': '能量守恒', 'level': 3},
                {'name': '圆周运动', 'level': 2},
            ]},
            {'name': '电磁学', 'level': 2, 'children': [
                {'name': '静电场', 'level': 2},
                {'name': '电路基础', 'level': 2},
                {'name': '电磁感应', 'level': 3},
                {'name': '磁场', 'level': 3},
            ]},
            {'name': '光学', 'level': 2, 'children': [
                {'name': '光的反射', 'level': 1},
                {'name': '光的折射', 'level': 2},
                {'name': '透镜成像', 'level': 2},
            ]},
        ],
        '英语': [
            {'name': '语法', 'level': 1, 'children': [
                {'name': '时态', 'level': 2},
                {'name': '语态', 'level': 2},
                {'name': '从句', 'level': 3},
                {'name': '虚拟语气', 'level': 3},
            ]},
            {'name': '词汇', 'level': 1, 'children': [
                {'name': '基础词汇', 'level': 1},
                {'name': '高级词汇', 'level': 3},
                {'name': '短语动词', 'level': 2},
            ]},
            {'name': '阅读', 'level': 2, 'children': [
                {'name': '阅读理解', 'level': 2},
                {'name': '完形填空', 'level': 3},
            ]},
        ],
        '化学': [
            {'name': '无机化学', 'level': 1, 'children': [
                {'name': '元素周期表', 'level': 1},
                {'name': '化学反应', 'level': 2},
                {'name': '化学平衡', 'level': 3},
                {'name': '酸碱盐', 'level': 2},
            ]},
            {'name': '有机化学', 'level': 2, 'children': [
                {'name': '烃类', 'level': 2},
                {'name': '官能团', 'level': 3},
                {'name': '有机反应', 'level': 3},
            ]},
        ]
    }

    knowledge_points = []
    for subject in subjects:
        if subject.name in knowledge_points_data:
            for kp_data in knowledge_points_data[subject.name]:
                # 创建父知识点
                parent_kp, created = KnowledgePoint.objects.get_or_create(
                    subject=subject,
                    name=kp_data['name'],
                    defaults={
                        'description': f'{kp_data["name"]}的详细描述，包含相关概念和解题方法',
                        'level': kp_data['level']
                    }
                )
                knowledge_points.append(parent_kp)
                print(f"创建知识点: {parent_kp.name}")

                # 创建子知识点
                if 'children' in kp_data:
                    for child_data in kp_data['children']:
                        child_kp, created = KnowledgePoint.objects.get_or_create(
                            subject=subject,
                            name=child_data['name'],
                            parent=parent_kp,
                            defaults={
                                'description': f'{child_data["name"]}的具体内容和应用',
                                'level': child_data['level']
                            }
                        )
                        knowledge_points.append(child_kp)
                        print(f"创建子知识点: {child_kp.name}")

    return knowledge_points


def create_exercises(subjects, knowledge_points, teacher):
    """创建习题数据"""
    exercises_data = [
        # 数学习题
        {
            'subject': '数学',
            'title': '一元一次方程求解',
            'content': '解方程: 2x + 5 = 13，求x的值。',
            'question_type': 'single',
            'difficulty': 'easy',
            'knowledge_points': ['一元一次方程'],
            'choices': [
                {'content': 'x = 4', 'is_correct': True},
                {'content': 'x = 5', 'is_correct': False},
                {'content': 'x = 6', 'is_correct': False},
                {'content': 'x = 7', 'is_correct': False},
            ]
        },
        {
            'subject': '数学',
            'title': '二次函数图像性质',
            'content': '关于二次函数 y = x² - 4x + 3，下列说法正确的是：',
            'question_type': 'multiple',
            'difficulty': 'medium',
            'knowledge_points': ['二次函数', '函数图像'],
            'choices': [
                {'content': '开口向上', 'is_correct': True},
                {'content': '对称轴是 x = 2', 'is_correct': True},
                {'content': '顶点在 (2, -1)', 'is_correct': True},
                {'content': '与x轴有两个交点', 'is_correct': True},
            ]
        },
        {
            'subject': '数学',
            'title': '几何证明题',
            'content': '在三角形ABC中，AB=AC，D是BC的中点。证明：AD垂直于BC。',
            'question_type': 'text',
            'difficulty': 'hard',
            'knowledge_points': ['平面几何', '相似三角形'],
            'choices': []
        },
        # 物理习题
        {
            'subject': '物理',
            'title': '牛顿第一定律',
            'content': '简述牛顿第一定律的内容及其在生活中的应用。',
            'question_type': 'text',
            'difficulty': 'easy',
            'knowledge_points': ['牛顿定律'],
            'choices': []
        },
        {
            'subject': '物理',
            'title': '电路分析',
            'content': '在如图所示的电路中，R1=10Ω，R2=20Ω，电源电压为12V。求电路中的总电流。',
            'question_type': 'single',
            'difficulty': 'medium',
            'knowledge_points': ['电路基础'],
            'choices': [
                {'content': '0.4A', 'is_correct': True},
                {'content': '0.6A', 'is_correct': False},
                {'content': '0.8A', 'is_correct': False},
                {'content': '1.0A', 'is_correct': False},
            ]
        },
        # 英语习题
        {
            'subject': '英语',
            'title': '时态选择',
            'content': 'I ______ to the park yesterday.',
            'question_type': 'single',
            'difficulty': 'easy',
            'knowledge_points': ['时态'],
            'choices': [
                {'content': 'go', 'is_correct': False},
                {'content': 'went', 'is_correct': True},
                {'content': 'have gone', 'is_correct': False},
                {'content': 'will go', 'is_correct': False},
            ]
        },
        {
            'subject': '英语',
            'title': '阅读理解',
            'content': '阅读以下短文，选择正确答案：\n\nThe Internet has changed the way we communicate...',
            'question_type': 'multiple',
            'difficulty': 'medium',
            'knowledge_points': ['阅读理解'],
            'choices': [
                {'content': 'The Internet improves communication', 'is_correct': True},
                {'content': 'The Internet has no negative effects', 'is_correct': False},
                {'content': 'Social media is mentioned in the text', 'is_correct': True},
                {'content': 'The text is about cooking', 'is_correct': False},
            ]
        },
        # 化学习题
        {
            'subject': '化学',
            'title': '元素周期表',
            'content': '下列元素中属于碱金属的是：',
            'question_type': 'multiple',
            'difficulty': 'medium',
            'knowledge_points': ['元素周期表', '碱金属'],
            'choices': [
                {'content': '钠 (Na)', 'is_correct': True},
                {'content': '钾 (K)', 'is_correct': True},
                {'content': '钙 (Ca)', 'is_correct': False},
                {'content': '锂 (Li)', 'is_correct': True},
            ]
        },
        {
            'subject': '化学',
            'title': '化学方程式',
            'content': '写出盐酸与氢氧化钠反应的中和反应方程式。',
            'question_type': 'text',
            'difficulty': 'medium',
            'knowledge_points': ['化学反应', '酸碱盐'],
            'choices': []
        },
    ]

    exercises = []
    for ex_data in exercises_data:
        subject = Subject.objects.get(name=ex_data['subject'])

        exercise, created = Exercise.objects.get_or_create(
            title=ex_data['title'],
            subject=subject,
            defaults={
                'content': ex_data['content'],
                'question_type': ex_data['question_type'],
                'difficulty': ex_data['difficulty'],
                'created_by': teacher
            }
        )

        if created:
            print(f"创建习题: {exercise.title}")

            # 创建选项
            for i, choice_data in enumerate(ex_data['choices']):
                Choice.objects.create(
                    exercise=exercise,
                    content=choice_data['content'],
                    is_correct=choice_data['is_correct'],
                    order=i
                )

            exercises.append(exercise)

    return exercises


def create_qmatrix(exercises, knowledge_points):
    """创建Q矩阵数据"""
    qmatrix_mapping = {
        '一元一次方程求解': ['一元一次方程'],
        '二次函数图像性质': ['二次函数', '函数图像'],
        '几何证明题': ['平面几何', '相似三角形'],
        '牛顿第一定律': ['牛顿定律'],
        '电路分析': ['电路基础'],
        '时态选择': ['时态'],
        '阅读理解': ['阅读理解'],
        '元素周期表': ['元素周期表', '碱金属'],
        '化学方程式': ['化学反应', '酸碱盐'],
    }

    qmatrix_entries = []
    for exercise in exercises:
        if exercise.title in qmatrix_mapping:
            for kp_name in qmatrix_mapping[exercise.title]:
                try:
                    kp = KnowledgePoint.objects.get(name=kp_name)
                    qm, created = QMatrix.objects.get_or_create(
                        exercise=exercise,
                        knowledge_point=kp,
                        defaults={'weight': round(random.uniform(0.5, 1.0), 2)}
                    )
                    if created:
                        qmatrix_entries.append(qm)
                        print(f"创建Q矩阵: {exercise.title} - {kp.name}")
                except KnowledgePoint.DoesNotExist:
                    print(f"知识点不存在: {kp_name}")

    return qmatrix_entries


def create_answer_logs(students, exercises):
    """创建答题记录数据"""
    answer_logs = []

    for student in students:
        # 每个学生回答5-10个题目
        student_exercises = random.sample(list(exercises), min(len(exercises), random.randint(5, 10)))

        for exercise in student_exercises:
            # 根据学生类型设置不同的正确率
            if student.username == 'demo_student':
                # 演示学生有中等水平
                is_correct = random.random() > 0.3  # 70%的正确率
            else:
                # 其他学生随机水平
                is_correct = random.random() > 0.5  # 50%的正确率

            # 创建答题记录
            answer_log = AnswerLog.objects.create(
                student=student,
                exercise=exercise,
                is_correct=is_correct,
                time_spent=random.randint(30, 600),  # 30秒到10分钟
                submitted_at=datetime.now() - timedelta(days=random.randint(1, 90))
            )

            # 如果是选择题，选择选项
            if exercise.question_type in ['single', 'multiple']:
                choices = exercise.choices.all()
                if exercise.question_type == 'single':
                    # 单选题：如果正确就选正确选项，否则随机选
                    if is_correct:
                        correct_choice = choices.filter(is_correct=True).first()
                        if correct_choice:
                            answer_log.selected_choices.add(correct_choice)
                    else:
                        wrong_choices = choices.filter(is_correct=False)
                        if wrong_choices:
                            answer_log.selected_choices.add(random.choice(list(wrong_choices)))
                else:
                    # 多选题：根据是否正确来选择
                    if is_correct:
                        # 正确回答：选择所有正确选项
                        correct_choices = choices.filter(is_correct=True)
                        answer_log.selected_choices.set(correct_choices)
                    else:
                        # 错误回答：随机选择，可能漏选或错选
                        selected_count = random.randint(1, len(choices))
                        selected = random.sample(list(choices), selected_count)
                        answer_log.selected_choices.set(selected)

            answer_logs.append(answer_log)
            print(f"创建答题记录: {student.username} - {exercise.title} - 正确: {is_correct}")

    return answer_logs


def create_student_diagnosis(students, knowledge_points):
    """创建学生诊断数据"""
    diagnoses = []

    for student in students:
        for kp in knowledge_points:
            # 找到涉及该知识点的习题
            related_exercises = Exercise.objects.filter(
                qmatrix__knowledge_point=kp
            ).distinct()

            # 该学生回答过的相关习题
            answered_exercises = related_exercises.filter(
                answerlog__student=student
            )

            practice_count = answered_exercises.count()
            correct_count = answered_exercises.filter(
                answerlog__student=student,
                answerlog__is_correct=True
            ).count()

            if practice_count > 0:
                mastery_level = correct_count / practice_count

                # 为演示学生设置更有意义的数据
                if student.username == 'demo_student':
                    # 演示学生在某些知识点上表现更好
                    if kp.name in ['一元一次方程', '时态', '光的反射']:
                        mastery_level = min(1.0, mastery_level + 0.3)
                    elif kp.level >= 3:  # 高难度知识点掌握度较低
                        mastery_level = max(0.1, mastery_level - 0.2)

                diagnosis, created = StudentDiagnosis.objects.get_or_create(
                    student=student,
                    knowledge_point=kp,
                    defaults={
                        'practice_count': practice_count,
                        'correct_count': correct_count,
                        'mastery_level': round(mastery_level, 2)
                    }
                )

                if created:
                    diagnoses.append(diagnosis)
                    print(f"创建诊断: {student.username} - {kp.name} - 掌握度: {diagnosis.mastery_level:.2f}")

    return diagnoses


def main():
    """主函数，执行所有数据创建流程"""
    print("开始创建演示数据...")

    # 1. 创建演示用户
    demo_teacher, demo_student, extra_students = create_demo_users()
    all_students = [demo_student] + extra_students

    # 2. 创建科目
    subjects = create_subjects()

    # 3. 创建知识点
    knowledge_points = create_knowledge_points(subjects)

    # 4. 创建习题
    exercises = create_exercises(subjects, knowledge_points, demo_teacher)

    # 5. 创建Q矩阵
    qmatrix_entries = create_qmatrix(exercises, knowledge_points)

    # 6. 创建答题记录
    answer_logs = create_answer_logs(all_students, exercises)

    # 7. 创建学生诊断
    diagnoses = create_student_diagnosis(all_students, knowledge_points)

    print("\n演示数据创建完成！")
    print("=" * 50)
    print("演示账号信息：")
    print(f"教师账号: demo_teacher / demo123")
    print(f"学生账号: demo_student / demo123")
    print("=" * 50)
    print(f"创建了 {len(subjects)} 个科目")
    print(f"创建了 {len(knowledge_points)} 个知识点")
    print(f"创建了 {len(exercises)} 个习题")
    print(f"创建了 {len(qmatrix_entries)} 个Q矩阵条目")
    print(f"创建了 {len(answer_logs)} 条答题记录")
    print(f"创建了 {len(diagnoses)} 个学生诊断记录")
    print("\n可以使用演示账号登录系统测试功能！")


if __name__ == "__main__":
    main()
