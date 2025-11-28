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



def main():
    """主函数，执行所有数据创建流程"""
    print("开始创建演示数据...")

    # 1. 创建演示用户
    demo_teacher, demo_student, extra_students = create_demo_users()
    all_students = [demo_student] + extra_students



if __name__ == "__main__":
    main()
