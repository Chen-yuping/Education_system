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
from django.views.decorators.http import require_POST
from django.utils import timezone

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


"""数据集 - 展示常用的公开数据集"""
def researcher_datasets(request):

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

"""诊断模型 - 展示各种诊断算法模型"""
def researcher_diagnosis_models(request):

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

"""性能对比 - 对比不同诊断模型在不同数据集上的性能"""
@login_required
@user_passes_test(is_researcher)
def researcher_performance_comparison(request):
    # 从数据库查询所有诊断模型和数据集
    models = DiagnosisModel.objects.filter(is_active=True)
    datasets = Dataset.objects.all()

    context = {
        'models': models,
        'datasets': datasets,
    }
    return render(request, 'researcher/researcher_performance_comparison.html', context)


@login_required
@user_passes_test(is_researcher)
@require_POST
def researcher_run_comparison(request):
    """
    处理性能对比的AJAX请求
    """
    try:
        # 解析JSON数据
        data = json.loads(request.body)
        print("收到数据:", data)  # 调试用

        dataset_id = data.get('dataset_id')
        model_ids = data.get('model_ids', [])
        record_data = data.get('record_data', False)

        # 验证数据
        if not dataset_id:
            return JsonResponse({'success': False, 'error': '请选择数据集'})

        if not model_ids:
            return JsonResponse({'success': False, 'error': '请选择至少一个模型'})

        # 获取数据集信息
        try:
            dataset = Dataset.objects.get(id=dataset_id)
        except Dataset.DoesNotExist:
            return JsonResponse({'success': False, 'error': '数据集不存在'})

        # 获取模型信息
        models = DiagnosisModel.objects.filter(id__in=model_ids, is_active=True)

        # 查询每个模型的训练结果
        results = []
        for model in models:
            # 查找该模型在选定数据集上的最新训练结果
            training_result = ModelTrainingResult.objects.filter(
                diagnosis_model=model,
                dataset=dataset
            ).order_by('-created_at').first()

            if training_result:
                results.append({
                    'model_id': model.id,
                    'model_name': model.name,
                    'acc': training_result.acc,
                    'auc': training_result.auc,
                    'rmse': training_result.rmse,
                    'best_round': training_result.best_round
                })
            else:
                results.append({
                    'model_id': model.id,
                    'model_name': model.name,
                    'acc': None,
                    'auc': None,
                    'rmse': None,
                    'message': '暂无训练记录'
                })

        return JsonResponse({
            'success': True,
            'dataset_name': dataset.name,
            'results': results
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '数据格式错误'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
