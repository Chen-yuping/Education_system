from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Avg
from django.core.paginator import Paginator
import json
from datetime import datetime, timedelta
from .models import Exercise, Subject, KnowledgePoint, Choice, QMatrix, AnswerLog, StudentDiagnosis
from accounts.models import *
from .forms import ExerciseForm
import csv

#研究者身份判断
def is_researcher(user):
    return user.user_type == 'researcher'


#研究者面板
@login_required
@user_passes_test(is_researcher)
def researcher_dashboard(request):
    """研究者仪表板 - 显示系统概览"""
    subjects = Subject.objects.all()
    total_subjects = subjects.count()
    total_exercises = Exercise.objects.count()
    total_knowledge_points = KnowledgePoint.objects.count()
    total_students = User.objects.filter(user_type='student').count()

    context = {
        'subjects': subjects,
        'total_subjects': total_subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
        'total_students': total_students,
    }
    return render(request, 'researcher/researcher_dashboard.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_data_analysis(request):
    """数据集分析 - 分析系统中的数据"""
    # 获取所有科目
    all_subjects = Subject.objects.all()
    
    # 获取筛选参数
    subject_filter = request.GET.get('subject', '')
    data_type_filter = request.GET.get('data_type', 'all')
    
    # 应用科目筛选
    if subject_filter:
        subjects_filtered = all_subjects.filter(id=subject_filter)
    else:
        subjects_filtered = all_subjects
    
    # 计算每个科目的统计信息
    for subject in subjects_filtered:
        subject.answer_count = AnswerLog.objects.filter(
            exercise__subject=subject
        ).count()
        
        # 计算平均正确率
        correct_answers = AnswerLog.objects.filter(
            exercise__subject=subject,
            is_correct=True
        ).count()
        
        if subject.answer_count > 0:
            subject.avg_correct_rate = round((correct_answers / subject.answer_count) * 100, 1)
        else:
            subject.avg_correct_rate = 0

    # 分页处理 - 每页10条
    paginator = Paginator(subjects_filtered, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 计算总体统计
    total_subjects = all_subjects.count()
    total_exercises = Exercise.objects.count()
    total_knowledge_points = KnowledgePoint.objects.count()
    total_answers = AnswerLog.objects.count()

    context = {
        'all_subjects': all_subjects,  # 用于图表和筛选下拉框
        'page_obj': page_obj,  # 用于表格分页显示
        'total_subjects': total_subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
        'total_answers': total_answers,
        'subject_filter': subject_filter,
        'data_type_filter': data_type_filter,
    }
    return render(request, 'researcher/researcher_data_analysis.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_algorithm_comparison(request):
    """算法对比 - 对比不同诊断算法的性能"""
    subjects = Subject.objects.all()

    context = {
        'subjects': subjects,
    }
    return render(request, 'researcher/researcher_algorithm_comparison.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_performance_analysis(request):
    """性能分析 - 分析系统性能指标"""
    subjects = Subject.objects.all()

    context = {
        'subjects': subjects,
    }
    return render(request, 'researcher/researcher_performance_analysis.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_reports(request):
    """研究报告 - 管理和生成研究报告"""
    subjects = Subject.objects.all()

    context = {
        'subjects': subjects,
    }
    return render(request, 'researcher/researcher_reports.html', context)
