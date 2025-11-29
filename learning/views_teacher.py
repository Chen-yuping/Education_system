from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
import json
from itertools import groupby
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm

#教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

#教师控制面板
@login_required
def dashboard(request):
    if request.user.user_type == 'teacher':
        return redirect('teacher_dashboard')
    else:
        return redirect('student_dashboard')

#教师面板
@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    subjects = Subject.objects.all()
    total_exercises = Exercise.objects.filter(creator=request.user).count()
    total_knowledge_points = KnowledgePoint.objects.count()

    return render(request, 'teacher/teacher_dashboard.html', {
        'subjects': subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
    })


@login_required
@user_passes_test(is_teacher)
def upload_knowledge(request):
    if request.method == 'POST':
        form = KnowledgePointForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '知识点上传成功！')
            return redirect('upload_knowledge')
    else:
        form = KnowledgePointForm()

    return render(request, 'teacher/upload_knowledge.html', {
        'form': form
    })


@login_required
@user_passes_test(is_teacher)
def q_matrix_management(request):
    if request.method == 'POST':
        form = QMatrixForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Q矩阵关系添加成功！')
            return redirect('q_matrix_management')
    else:
        form = QMatrixForm()

    q_matrix = QMatrix.objects.all().select_related('exercise', 'knowledge_point')

    return render(request, 'teacher/q_matrix.html', {
        'form': form,
        'q_matrix': q_matrix
    })


def update_knowledge_mastery(student, exercise, is_correct):
    """更新学生对知识点的掌握程度"""
    related_kps = QMatrix.objects.filter(exercise=exercise).select_related('knowledge_point')

    for q_item in related_kps:
        diagnosis, created = StudentDiagnosis.objects.get_or_create(
            student=student,
            knowledge_point=q_item.knowledge_point
        )

        diagnosis.practice_count += 1
        if is_correct:
            diagnosis.correct_count += 1

        diagnosis.calculate_mastery()