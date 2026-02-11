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
    
    # 获取分类筛选
    category_filter = request.GET.get('category', '').strip()
    if category_filter:
        all_models = all_models.filter(category=category_filter)
    
    # 获取所有分类选项
    category_choices = DiagnosisModel.MODEL_CATEGORY_CHOICES
    
    # 统计各分类的模型数量
    from django.db.models import Count
    category_stats = DiagnosisModel.objects.filter(is_active=True).values('category').annotate(count=Count('id'))
    category_stats_dict = {stat['category']: stat['count'] for stat in category_stats}
    
    # 构建分类统计数据
    category_data = []
    for value, label in category_choices:
        category_data.append({
            'value': value,
            'label': label,
            'count': category_stats_dict.get(value, 0)
        })
    
    # 获取各分类的模型列表（用于树形图）
    probability_models = DiagnosisModel.objects.filter(is_active=True, category='probability')
    nn_models = DiagnosisModel.objects.filter(is_active=True, category='nn')
    gnn_models = DiagnosisModel.objects.filter(is_active=True, category='gnn')
    llm_models = DiagnosisModel.objects.filter(is_active=True, category='llm')
    
    # 分页处理 - 每页10条
    paginator = Paginator(all_models, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 检查是否是AJAX请求
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # 构建表格HTML
        table_html = ''
        for model in page_obj:
            category_label = dict(category_choices).get(model.category, '')
            table_html += f'''
            <tr>
                <td class="model-name">{model.name}</td>
                <td>
                    <span class="category-badge category-{model.category}">
                        {category_label}
                    </span>
                </td>
                <td class="model-description" title="{model.description}">{model.description}</td>
                <td>
                    <span class="status-badge status-{'active' if model.is_active else 'inactive'}">
                        {'启用' if model.is_active else '禁用'}
                    </span>
                </td>
                <td>
                    <div class="links-cell">
                        {'<a href="' + model.paper_link + '" class="link-btn paper" target="_blank"><i class="fas fa-file-pdf me-1"></i>论文</a>' if model.paper_link else '<span class="link-btn disabled"><i class="fas fa-file-pdf me-1"></i>暂无</span>'}
                    </div>
                </td>
            </tr>
            '''
        
        if not page_obj:
            table_html = '''
            <tr>
                <td colspan="5" class="text-center py-4 text-muted">
                    <i class="fas fa-inbox fa-2x mb-3"></i>
                    <p>暂无诊断模型</p>
                </td>
            </tr>
            '''
        
        # 构建分页HTML
        pagination_html = ''
        if page_obj.has_other_pages:
            pagination_html = '<nav aria-label="分页导航" class="mt-4"><ul class="pagination justify-content-center">'
            
            if page_obj.has_previous:
                pagination_html += f'''
                <li class="page-item">
                    <a class="page-link pagination-link" href="?page=1{'&search=' + search_query if search_query else ''}{'&category=' + category_filter if category_filter else ''}">&laquo;&laquo;</a>
                </li>
                <li class="page-item">
                    <a class="page-link pagination-link" href="?page={page_obj.previous_page_number}{'&search=' + search_query if search_query else ''}{'&category=' + category_filter if category_filter else ''}">&laquo;</a>
                </li>
                '''
            else:
                pagination_html += '''
                <li class="page-item disabled">
                    <span class="page-link">&laquo;&laquo;</span>
                </li>
                <li class="page-item disabled">
                    <span class="page-link">&laquo;</span>
                </li>
                '''
            
            for num in page_obj.paginator.page_range:
                if page_obj.number == num:
                    pagination_html += f'<li class="page-item active"><span class="page-link">{num}</span></li>'
                elif num > page_obj.number - 3 and num < page_obj.number + 3:
                    pagination_html += f'''
                    <li class="page-item">
                        <a class="page-link pagination-link" href="?page={num}{'&search=' + search_query if search_query else ''}{'&category=' + category_filter if category_filter else ''}">{num}</a>
                    </li>
                    '''
            
            if page_obj.has_next:
                pagination_html += f'''
                <li class="page-item">
                    <a class="page-link pagination-link" href="?page={page_obj.next_page_number}{'&search=' + search_query if search_query else ''}{'&category=' + category_filter if category_filter else ''}">&raquo;</a>
                </li>
                <li class="page-item">
                    <a class="page-link pagination-link" href="?page={page_obj.paginator.num_pages}{'&search=' + search_query if search_query else ''}{'&category=' + category_filter if category_filter else ''}">&raquo;&raquo;</a>
                </li>
                '''
            else:
                pagination_html += '''
                <li class="page-item disabled">
                    <span class="page-link">&raquo;</span>
                </li>
                <li class="page-item disabled">
                    <span class="page-link">&raquo;&raquo;</span>
                </li>
                '''
            
            pagination_html += '</ul></nav>'
            pagination_html += f'''
            <div class="text-center text-muted mt-3 mb-4">
                <small>第 {page_obj.number} 页，共 {page_obj.paginator.num_pages} 页</small>
            </div>
            '''
        
        return JsonResponse({
            'html': table_html,
            'pagination_html': pagination_html,
            'total_count': all_models.count(),
        })

    context = {
        'page_obj': page_obj,
        'total_count': all_models.count(),
        'search_query': search_query,
        'category_filter': category_filter,
        'category_choices': category_choices,
        'category_data': category_data,
        'probability_models': probability_models,
        'nn_models': nn_models,
        'gnn_models': gnn_models,
        'llm_models': llm_models,
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
