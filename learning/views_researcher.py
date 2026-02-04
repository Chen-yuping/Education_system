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
    datasets_count = Dataset.objects.count()
    models_count = DiagnosisModel.objects.filter(is_active=True).count()

    context = {
        'subjects': subjects,
        'total_subjects': total_subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
        'total_students': total_students,
        'datasets_count': datasets_count,
        'models_count': models_count,
    }
    return render(request, 'researcher/researcher_dashboard.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_datasets(request):
    """数据集 - 展示常用的公开数据集"""
    # 从数据库查询所有数据集
    all_datasets = Dataset.objects.all()
    
    # 获取搜索关键词
    search_query = request.GET.get('search', '').strip()
    if search_query:
        all_datasets = all_datasets.filter(name__icontains=search_query)
    
    # 分页处理 - 每页10条
    paginator = Paginator(all_datasets, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'total_count': all_datasets.count(),
        'search_query': search_query,
    }
    return render(request, 'researcher/researcher_datasets.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_diagnosis_models(request):
    """诊断模型 - 展示各种诊断算法模型"""
    # 从数据库查询所有诊断模型
    all_models = DiagnosisModel.objects.filter(is_active=True)
    
    # 获取搜索关键词
    search_query = request.GET.get('search', '').strip()
    if search_query:
        all_models = all_models.filter(name__icontains=search_query)
    
    # 分页处理 - 每页10条
    paginator = Paginator(all_models, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'total_count': all_models.count(),
        'search_query': search_query,
    }
    return render(request, 'researcher/researcher_diagnosis_models.html', context)


@login_required
@user_passes_test(is_researcher)
def researcher_performance_comparison(request):
    """性能对比 - 对比不同诊断模型在不同数据集上的性能"""
    # 从数据库查询所有诊断模型和数据集
    models = DiagnosisModel.objects.filter(is_active=True)
    datasets = Dataset.objects.all()

    context = {
        'models': models,
        'datasets': datasets,
    }
    return render(request, 'researcher/researcher_performance_comparison.html', context)
