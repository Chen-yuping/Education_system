from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
import sys
import threading  # 添加这个
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
import importlib.util
from .forms import ExerciseForm
import torch
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

"""性能对比页面 - 对比不同诊断模型在不同数据集上的性能"""
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


# 训练状态存储（实际生产环境应该用数据库或缓存）
training_tasks = {}

"""后台执行训练任务"""
def run_training_task(dataset_name, model_name, experiment_id, user_id):

    import os
    try:
        print(f"========== 开始训练任务: {dataset_name}_{model_name} ==========")

        # 设置环境变量，告诉params.py使用哪个数据集
        os.environ['CD_DATASET'] = dataset_name
        print(f"设置环境变量 CD_DATASET={dataset_name}")

        # 构建数据集路径
        base_path = os.path.join(settings.BASE_DIR, 'learning', 'diagnosis', 'CMD_survey')
        data_path = os.path.join(base_path, 'data', dataset_name)
        print(f"数据路径: {data_path}")

        # 读取config.txt获取学生数、习题数、知识点数
        config_path = os.path.join(data_path, 'config.txt')
        print(f"读取配置文件: {config_path}")
        with open(config_path, 'r') as f:
            f.readline()  # 跳过注释行
            un, en, kn = f.readline().strip().split(',')
            un, en, kn = int(un), int(en), int(kn)
        print(f"数据集信息: 学生数={un}, 习题数={en}, 知识点数={kn}")

        # 切换到 CMD_survey 目录
        sys.path.insert(0, base_path)
        os.chdir(base_path)
        print(f"当前工作目录: {os.getcwd()}")

        # 导入params（现在它会读取环境变量）
        import params
        print("已导入params模块")

        # 验证params中的路径是否正确
        print(f"params.dataset = {params.dataset}")

        # 导入对应的模型模块
        model_module_map = {
            'IRT': 'IRT',
            'NCDM': 'NCDM',
            'DINA': 'DINA',
        }

        module_name = model_module_map.get(model_name)
        if not module_name:
            raise Exception(f'未知模型: {model_name}')

        print(f"导入模型模块: model.{module_name}")
        model_module = importlib.import_module(f'model.{module_name}')

        # 创建模型实例
        print(f"创建{model_name}模型实例...")
        if model_name == 'IRT':
            cdm = model_module.IRT(un, en, value_range=4.0, a_range=2.0)
        elif model_name == 'NCDM':
            cdm = model_module.NCDM(kn, en, un)
        elif model_name == 'DINA':
            cdm = model_module.DINA(un, en, kn)
        else:
            raise Exception(f'未实现的模型: {model_name}')
        print("模型实例创建完成")

        # 加载数据
        print("加载数据...")
        import dataloader
        importlib.reload(dataloader)
        src, tgt = dataloader.CD_DL()
        print("数据加载完成")

        # 将ID从1-based转换为0-based
        print("转换ID从1-based到0-based...")

        def convert_to_zero_based(dataloader):
            new_batches = []
            for batch in dataloader:
                user_ids, exer_ids, knowledge_emb, ys = batch
                # ID减1（1-based -> 0-based）
                user_ids = user_ids - 1
                exer_ids = exer_ids - 1
                new_batches.append((user_ids, exer_ids, knowledge_emb, ys))
            return new_batches

        # 转换训练集和验证集
        src = convert_to_zero_based(src)
        tgt = convert_to_zero_based(tgt)
        print("ID转换完成")

        # 训练
        import torch
        device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        print(f"开始训练，使用设备: {device}")
        result = cdm.train(train_data=src, test_data=tgt, epoch=10, device=device, lr=params.lr)
        print(f"训练完成，原始结果: {result}")

        # result 格式可能是 (best_epoch, best_auc, best_acc) 或包含 rmse
        if len(result) == 3:
            best_epoch, best_auc, best_acc = result
            rmse = None
        else:
            best_epoch, best_auc, best_acc, rmse = result

        print(f"解析结果: best_epoch={best_epoch}, acc={best_acc}, auc={best_auc}, rmse={rmse}")

        # 保存到数据库
        print("保存结果到数据库...")
        from .models import Experiment, ModelTrainingResult, Dataset, DiagnosisModel
        from django.contrib.auth import get_user_model

        User = get_user_model()

        dataset_obj = Dataset.objects.get(name=dataset_name)
        model_obj = DiagnosisModel.objects.get(name=model_name)
        experiment = Experiment.objects.get(batch_id=experiment_id)

        ModelTrainingResult.objects.create(
            experiment=experiment,
            diagnosis_model=model_obj,
            dataset=dataset_obj,
            best_round=best_epoch,
            acc=best_acc,
            auc=best_auc,
            rmse=rmse if rmse else 0.0,
            best_round_time=0.0,
            total_time=0.0,
            created_by=User.objects.get(id=user_id)
        )
        print("数据库保存完成")

        # 更新任务状态
        task_key = f"{dataset_name}_{model_name}"
        training_tasks[task_key] = {
            'status': 'completed',
            'result': {
                'best_epoch': best_epoch,
                'acc': best_acc,
                'auc': best_auc,
                'rmse': rmse
            }
        }
        print(f"========== 任务 {dataset_name}_{model_name} 完成 ==========")

    except Exception as e:
        print(f"!!!!!!!!!! 训练任务出错: {str(e)} !!!!!!!!!!")
        import traceback
        traceback.print_exc()

        task_key = f"{dataset_name}_{model_name}"
        training_tasks[task_key] = {
            'status': 'failed',
            'error': str(e)
        }

"""处理性能对比的AJAX请求 - 异步启动训练任务"""
@login_required
@user_passes_test(is_researcher)
@require_POST
def researcher_run_comparison(request):

    try:
        # 解析JSON数据
        data = json.loads(request.body)
        print("收到数据:", data)

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

        # 如果需要记录数据，创建实验批次
        import uuid
        from django.utils import timezone

        experiment = None
        if record_data:
            batch_id = f"{timezone.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            experiment = Experiment.objects.create(
                batch_id=batch_id,
                dataset=dataset,
                created_by=request.user
            )

        # 为每个模型启动训练任务
        for model in models:
            # 启动后台线程训练
            task_key = f"{dataset.name}_{model.name}"
            training_tasks[task_key] = {'status': 'training'}

            thread = threading.Thread(
                target=run_training_task,
                args=(dataset.name, model.name, experiment.batch_id if experiment else None, request.user.id)
            )
            thread.start()

        return JsonResponse({
            'success': True,
            'message': '训练任务已启动',
            'experiment_id': experiment.batch_id if experiment else None,
            'tasks': [f"{dataset.name}_{model.name}" for model in models]
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '数据格式错误'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

"""检查训练任务状态"""
@login_required
@user_passes_test(is_researcher)
def check_training_status(request):

    task_key = request.GET.get('task')
    if task_key in training_tasks:
        return JsonResponse(training_tasks[task_key])
    return JsonResponse({'status': 'not_found'})
