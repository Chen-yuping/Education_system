from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
import json
from itertools import groupby
from learning.models import *
from learning.forms import ExerciseForm, KnowledgePointForm, QMatrixForm

#登录用户判断
def is_teacher(user):
    return user.user_type == 'teacher'

def is_student(user):
    return user.user_type == 'student'

# 获取学生的知识点掌握情况
@login_required
@user_passes_test(is_student)
def student_diagnosis(request):

    diagnoses = StudentDiagnosis.objects.filter(student=request.user).select_related('knowledge_point')

    # 按科目分组
    subjects = {}
    for diagnosis in diagnoses:
        subject_name = diagnosis.knowledge_point.subject.name
        if subject_name not in subjects:
            subjects[subject_name] = []
        subjects[subject_name].append(diagnosis)

    # 计算推荐学习路径
    weak_points = diagnoses.filter(mastery_level__lt=0.6).order_by('mastery_level')[:5]

    return render(request, 'student_diagnosis.html', {
        'subjects': subjects,
        'weak_points': weak_points
    })