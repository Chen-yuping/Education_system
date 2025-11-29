from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from ..models import *

def knowledge_mastery_diagnoses(user, answerlog):

    return


def is_student(user):
    return user.user_type == 'student'
# 获取学生的知识点掌握情况，学习诊断页面
@login_required
@user_passes_test(is_student)
def student_diagnosis(request):

    diagnoses = StudentDiagnosis.objects.filter(student=request.user).select_related('knowledge_point')
    answerlog = AnswerLog.objects.filter(student=request.user)

    knowledge_mastery_diagnoses(request.user, answerlog)

    # 按科目分组
    subjects = {}
    for diagnosis in diagnoses:
        subject_name = diagnosis.knowledge_point.subject.name
        if subject_name not in subjects:
            subjects[subject_name] = []
        subjects[subject_name].append(diagnosis)

    # 计算推荐学习路径
    weak_points = diagnoses.filter(mastery_level__lt=0.6).order_by('mastery_level')[:5]
    # 更新知识点掌握情况


    return render(request, 'student/student_diagnosis.html', {
        'subjects': subjects,
        'weak_points': weak_points
    })