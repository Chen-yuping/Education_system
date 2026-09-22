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
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from .models import Exercise, Subject, KnowledgePoint, Choice, QMatrix, AnswerLog, StudentDiagnosis
from accounts.models import *
import importlib.util
from .forms import ExerciseForm
import torch
from django.conf import settings
from django.core.cache import caches
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
    
    # 检查是否是AJAX请求
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # 构建表格HTML
        table_html = ''
        for model in all_models:
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
        
        if not all_models:
            table_html = '''
            <tr>
                <td colspan="5" class="text-center py-4 text-muted">
                    <i class="fas fa-inbox fa-2x mb-3"></i>
                    <p>暂无诊断模型</p>
                </td>
            </tr>
            '''
        
        return JsonResponse({
            'html': table_html,
            'total_count': all_models.count(),
        })

    context = {
        'models': all_models,
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


@login_required
@user_passes_test(is_researcher)
def researcher_algorithm_comparison(request):
    from .diagnosis.dual_relation_ncdm import MODEL_NAMES
    from .diagnosis.dual_relation_ncdm.platform import resolve_system_dataset_dir

    datasets = [dataset for dataset in Dataset.objects.all()
                if resolve_system_dataset_dir(dataset.name) or
                (dataset.name.casefold() in {'math', 'math1'} and
                 (Path(settings.BASE_DIR) / 'learning/diagnosis/CMD_survey/data/Math1/train.csv').exists())]
    independent_names = {'NCDM'}
    related_names = MODEL_NAMES | {'HierCDF', 'ConCDF', 'PCG-CDF', 'QCCDM'}
    independent_models = DiagnosisModel.objects.filter(is_active=True, name__in=independent_names)
    related_models = DiagnosisModel.objects.filter(is_active=True, name__in=related_names)
    return render(request, 'researcher/researcher_algorithm_comparison.html', {
        'datasets': datasets,
        'independent_models': independent_models,
        'related_models': related_models,
    })


def _train_hiercdf_mastery(data_dir, stats, task=None):
    """Train HierCDF on its native data and return student by skill posterior probabilities."""
    import numpy as np
    import pandas as pd
    from .researcher_cdf_compat import ensure_pandas_append

    required = ('config.py', 'knowledge_graphs_prereq.csv', 'q_matrix.txt',
                'log_split__train_mini.csv', 'log_split__valid_mini.csv')
    missing = [name for name in required if not (data_dir / name).is_file()]
    if missing:
        raise ValueError(f'HierCDF 缺少数据文件：{", ".join(missing)}')
    ensure_pandas_append()
    from .diagnosis.CMD_survey.model.HierCDF.HierCDF import HierCDF
    # HierCDF's data loader creates Double tensors. Its import changes the
    # default dtype only on first import, so set it on every training run.
    torch.set_default_dtype(torch.float64)

    spec = importlib.util.spec_from_file_location('comparison_hiercdf_config', data_dir / 'config.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    params = dict(config.hparams)
    counts = (stats['student_n'], stats['exercise_n'], stats['knowledge_n'])
    if tuple(int(params[key]) for key in ('n_user', 'n_item', 'n_know')) != counts:
        raise ValueError('HierCDF 配置中的学生、习题或知识点数量与数据集不一致。')
    graph = pd.read_csv(data_dir / 'knowledge_graphs_prereq.csv')
    q_matrix = np.loadtxt(data_dir / 'q_matrix.txt')
    train_data = pd.read_csv(data_dir / 'log_split__train_mini.csv')
    valid_data = pd.read_csv(data_dir / 'log_split__valid_mini.csv')
    params['device'] = torch.device('cpu')
    log_dir = _cdf_model_log_dir('HierCDF', data_dir.name)
    params['Hier_log_path'] = str(log_dir)
    if task is not None:
        task.update(log_dir=str(log_dir),
                    before_log_dirs=[str(path) for path in _snapshot_log_dirs(log_dir)],
                    started_at=time.time(),
                    batches_per_epoch=math.ceil(len(train_data) / int(params['batch_size'])),
                    total_epochs=int(params['epoch']))
        _save_algorithm_comparison_task(task['task_id'], task)
    model = HierCDF(*counts, hidden_dim=params['hidden_dim'], know_graph=graph,
                    itf_type='irt', log_path=str(log_dir))
    model.train(params, train_data, q_matrix, valid_data)
    if task is not None:
        task.update(progress=52, message='HierCDF 训练完成，正在提取掌握度')
        _save_algorithm_comparison_task(task['task_id'], task)
    with torch.no_grad():
        mastery = torch.cat([
            model.get_posterior(torch.arange(start, min(start + 256, counts[0])), device='cpu')
            for start in range(0, counts[0], 256)
        ]).cpu().numpy()
    if mastery.shape != (counts[0], counts[2]) or not np.isfinite(mastery).all():
        raise ValueError('HierCDF 未产生有效的逐知识点掌握度。')
    edges = [(int(source), int(target)) for source, target in graph.iloc[:, :2].itertuples(index=False, name=None)]
    if task is not None:
        task.pop('log_dir', None)
        _save_algorithm_comparison_task(task['task_id'], task)
    return mastery, edges


@login_required
@user_passes_test(is_researcher)
@require_POST
def researcher_algorithm_comparison_data(request):
    """Compare observed mastery with the selected relation-aware model's mastery."""
    from .diagnosis.dual_relation_ncdm import MODEL_NAMES
    from .diagnosis.dual_relation_ncdm.platform import resolve_system_dataset_dir

    try:
        payload = json.loads(request.body)
        dataset = Dataset.objects.get(pk=payload.get('dataset_id'))
        independent_model = DiagnosisModel.objects.get(pk=payload.get('independent_model_id'), is_active=True)
        related_model = DiagnosisModel.objects.get(pk=payload.get('related_model_id'), is_active=True)
    except (ValueError, TypeError, json.JSONDecodeError, Dataset.DoesNotExist, DiagnosisModel.DoesNotExist):
        return JsonResponse({'error': '请选择有效的数据集和模型。'}, status=400)
    if independent_model.name != 'NCDM' or related_model.name not in MODEL_NAMES | {'HierCDF'}:
        return JsonResponse({'error': '所选模型组合暂不支持逐知识点掌握度输出。'}, status=400)
    if related_model.name == 'HierCDF' and dataset.name.casefold() in {'math', 'math1'}:
        from .prepare_math1_hiercdf import prepare_math1_hiercdf, MATH1
        try:
            prepare_math1_hiercdf()
        except (OSError, ValueError) as exc:
            return JsonResponse({'error': f'Math 数据准备失败：{exc}'}, status=400)
        data_dir = MATH1
    else:
        data_dir = resolve_system_dataset_dir(dataset.name)
    if not data_dir:
        return JsonResponse({'error': '未找到该数据集的训练文件。'}, status=400)

    import uuid
    task_id = uuid.uuid4().hex
    task = {
        'user_id': request.user.pk, 'status': 'queued', 'progress': 0,
        'message': '等待训练资源', 'task_id': task_id,
    }
    _save_algorithm_comparison_task(task_id, task)
    threading.Thread(target=_run_algorithm_comparison,
                     args=(task_id, data_dir, related_model.name), daemon=True).start()
    return JsonResponse({'task_id': task_id})


def _run_algorithm_comparison(task_id, data_dir, related_model_name):
    task = _load_algorithm_comparison_task(task_id)
    try:
        task.update(status='training', progress=2, message='读取数据集')
        _save_algorithm_comparison_task(task_id, task)
        result = _calculate_algorithm_comparison(task, data_dir, related_model_name)
        task.update(status='completed', progress=100, message='分析完成', result=result)
        _save_algorithm_comparison_task(task_id, task)
    except Exception as exc:
        task.update(status='failed', message=f'诊断分析失败：{exc}')
        _save_algorithm_comparison_task(task_id, task)


def _calculate_algorithm_comparison(task, data_dir, related_model_name):
    from collections import defaultdict
    from .diagnosis.dual_relation_ncdm.platform import (
        build_context_from_json_dir, train_from_context, extract_mastery,
        normalize_index, read_adjacency_edges,
    )

    context = build_context_from_json_dir(data_dir)
    skill_names = {}
    names_file = data_dir / 'qnames.txt'
    if names_file.is_file():
        for line in names_file.read_text(encoding='utf-8-sig').splitlines():
            columns = line.strip().split(maxsplit=1)
            if len(columns) == 2 and columns[0].isdigit():
                skill_names[int(columns[0])] = columns[1].strip()
    task.update(progress=5, message='数据已准备，等待模型训练')
    _save_algorithm_comparison_task(task['task_id'], task)
    try:
        stats = context['stats']
        with training_execution_lock:
            try:
                if related_model_name == 'HierCDF':
                    task.update(progress=8, message='正在训练 HierCDF')
                    _save_algorithm_comparison_task(task['task_id'], task)
                    relation_mastery, hier_edges = _train_hiercdf_mastery(data_dir, stats, task)
                else:
                    task.update(progress=8, message=f'正在训练 {related_model_name}')
                    _save_algorithm_comparison_task(task['task_id'], task)
                    _, trained_model = train_from_context(context, model_name=related_model_name)
                    relation_mastery = extract_mastery(trained_model)
                task.update(progress=55, message='正在训练 NCDM')
                _save_algorithm_comparison_task(task['task_id'], task)
                torch.set_default_dtype(torch.float32)
                from .diagnosis.CMD_survey.model.NCDM import NCDM
                from .diagnosis.dual_relation_ncdm.platform import build_loader
                train_batches = [(user, exercise, original_q, score)
                                 for user, exercise, original_q, _, _, score
                                 in build_loader(context['train_records'], shuffle=True, seed=20260403)]
                class ProgressBatches:
                    def __init__(self, batches):
                        self.batches = batches
                        self.epoch = 0

                    def __len__(self):
                        return len(self.batches)

                    def __iter__(self):
                        self.epoch += 1
                        for index, batch in enumerate(self.batches, 1):
                            completed = (self.epoch - 1) * len(self.batches) + index
                            new_progress = min(94, 55 + round(40 * completed / (10 * len(self.batches))))
                            previous_progress = task['progress']
                            task.update(progress=new_progress,
                                        message=f'NCDM 第 {self.epoch}/10 轮，批次 {index}/{len(self.batches)}')
                            if new_progress != previous_progress or index == len(self.batches):
                                _save_algorithm_comparison_task(task['task_id'], task)
                            yield batch

                baseline = NCDM(stats['knowledge_n'], stats['exercise_n'], stats['student_n'])
                baseline.train_with_curves(ProgressBatches(train_batches), epoch=10,
                                           device='cuda:0' if torch.cuda.is_available() else 'cpu')
                baseline.ncdm_net.eval()
                with torch.no_grad():
                    independent_mastery = torch.sigmoid(baseline.ncdm_net.student_emb.weight).cpu().numpy()
            finally:
                torch.set_default_dtype(torch.float32)
        task.update(progress=96, message='正在计算知识点平均掌握率')
        _save_algorithm_comparison_task(task['task_id'], task)
        observed = defaultdict(lambda: [0.0, 0])
        for row in context['log_rows']:
            student = normalize_index(row['user_id'], stats['student_n'])
            if student is None:
                continue
            for code in row.get('knowledge_code') or []:
                skill = normalize_index(code, stats['knowledge_n'])
                if skill is not None:
                    item = observed[(student, skill)]
                    item[0] += float(row.get('score', 0) or 0)
                    item[1] += 1

        by_skill = defaultdict(list)
        by_student = defaultdict(list)
        for (student, skill), values in observed.items():
            by_skill[skill].append((student, values))
            by_student[student].append((skill, values))

        knowledge_rows = []
        for skill in range(stats['knowledge_n']):
            pairs = by_skill[skill]
            independent = (sum(float(independent_mastery[student][skill]) for student, _ in pairs) / len(pairs)
                           if pairs else None)
            related = (sum(float(relation_mastery[student][skill]) for student, _ in pairs) / len(pairs)
                       if pairs else None)
            knowledge_rows.append({
                'id': skill,
                'name': str(context['skill_mapping'].get(skill, skill + 1)),
                'skill_name': skill_names.get(int(context['skill_mapping'].get(skill, skill + 1)), ''),
                'independent': round(independent * 100, 1) if independent is not None else None,
                'related': round(related * 100, 1) if related is not None else None,
                'students': len(pairs),
            })
        edges = [
            {'source': source, 'target': target}
            for source, target in (hier_edges if related_model_name == 'HierCDF'
                                   else read_adjacency_edges(data_dir, stats))
            if source is not None and target is not None and source != target
        ]
        return {'student_count': len(by_student),
                'knowledge_points': knowledge_rows, 'relations': edges}
    finally:
        torch.set_default_dtype(torch.float32)


def _save_algorithm_comparison_task(task_id, task):
    caches['algorithm_comparison'].set(f'algorithm_comparison:{task_id}', task, timeout=86400)


def _load_algorithm_comparison_task(task_id):
    return caches['algorithm_comparison'].get(f'algorithm_comparison:{task_id}')


@login_required
@user_passes_test(is_researcher)
def researcher_algorithm_comparison_status(request):
    task = _load_algorithm_comparison_task(request.GET.get('task_id'))
    if not task or task['user_id'] != request.user.pk:
        return JsonResponse({'error': '未找到该分析任务。'}, status=404)
    response = {key: task[key] for key in ('status', 'progress', 'message')}
    if response['status'] == 'completed':
        response['result'] = task['result']
    if response['status'] == 'training' and 'log_dir' in task:
        detail = _hiercdf_progress(task)
        response['progress'] = max(response['progress'], min(54, 8 + round(detail['progress'] * .46)))
        response['message'] = f"HierCDF：{detail['message']}"
    return JsonResponse(response)


# 训练状态存储（实际生产环境应该用数据库或缓存）
training_tasks = {}
training_execution_lock = threading.Lock()

def _cdf_model_log_dir(model_name, dataset_name):
    return (
        Path(settings.BASE_DIR)
        / 'learning'
        / 'diagnosis'
        / 'CMD_survey'
        / 'model'
        / model_name
        / 'logs'
        / dataset_name
    )


def _snapshot_log_dirs(log_dir):
    if not log_dir.exists():
        return set()
    return {path.resolve() for path in log_dir.iterdir() if path.is_dir()}


def _find_newest_log_file(log_dir, before_dirs):
    if not log_dir.exists():
        return None

    candidates = []
    for path in log_dir.iterdir():
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in before_dirs:
            continue
        log_file = path / 'log.txt'
        if log_file.exists():
            candidates.append(log_file)

    if not candidates:
        candidates = [path / 'log.txt' for path in log_dir.iterdir() if path.is_dir() and (path / 'log.txt').exists()]

    if not candidates:
        return None

    return max(candidates, key=lambda item: item.stat().st_mtime)


def _parse_cdf_training_curves(log_file):
    curves = {'acc': [], 'auc': [], 'rmse': []}
    if not log_file or not log_file.exists():
        return curves

    epoch_metrics = {}
    train_pattern = re.compile(
        r"epoch\s*=\s*(?P<epoch>\d+).*?train_acc\s*=\s*(?P<acc>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
        r".*?train_auc\s*=\s*(?P<auc>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
        r".*?train_r?mse\s*=\s*(?P<rmse>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
    )
    valid_acc_pattern = re.compile(r"valid acc\s*=\s*(?P<acc>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
    valid_auc_pattern = re.compile(r"valid auc\s*=\s*(?P<auc>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
    valid_mse_pattern = re.compile(r"valid mse\s*=\s*(?P<mse>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
    epoch_hint_pattern = re.compile(r"epoch\s*=\s*(?P<epoch>\d+)")

    current_epoch = None
    lines = log_file.read_text(encoding='utf-8', errors='ignore').splitlines()
    for line in lines:
        train_match = train_pattern.search(line)
        if train_match:
            epoch = int(train_match.group('epoch'))
            epoch_metrics.setdefault(epoch, {})
            epoch_metrics[epoch]['acc'] = float(train_match.group('acc'))
            epoch_metrics[epoch]['auc'] = float(train_match.group('auc'))
            epoch_metrics[epoch]['rmse'] = float(train_match.group('rmse'))
            current_epoch = epoch
            continue

        epoch_hint_match = epoch_hint_pattern.search(line)
        if epoch_hint_match:
            current_epoch = int(epoch_hint_match.group('epoch'))

        if current_epoch is None:
            continue

        valid_acc_match = valid_acc_pattern.search(line)
        if valid_acc_match:
            epoch_metrics.setdefault(current_epoch, {})
            epoch_metrics[current_epoch]['acc'] = float(valid_acc_match.group('acc'))
            continue

        valid_auc_match = valid_auc_pattern.search(line)
        if valid_auc_match:
            epoch_metrics.setdefault(current_epoch, {})
            epoch_metrics[current_epoch]['auc'] = float(valid_auc_match.group('auc'))
            continue

        valid_mse_match = valid_mse_pattern.search(line)
        if valid_mse_match:
            epoch_metrics.setdefault(current_epoch, {})
            mse_value = float(valid_mse_match.group('mse'))
            epoch_metrics[current_epoch]['rmse'] = math.sqrt(mse_value) if mse_value > 0 else 0.0

    for epoch in sorted(epoch_metrics):
        metrics = epoch_metrics[epoch]
        curves['acc'].append(metrics.get('acc'))
        curves['auc'].append(metrics.get('auc'))
        curves['rmse'].append(metrics.get('rmse'))

    return curves


def _hiercdf_progress(task):
    log_dir = Path(task['log_dir'])
    before_dirs = {Path(path) for path in task['before_log_dirs']}
    log_file = _find_newest_log_file(log_dir, before_dirs)
    if not log_file or log_file.stat().st_mtime < task['started_at']:
        return {'progress': 0, 'message': '准备训练数据'}
    lines = log_file.read_text(encoding='utf-8', errors='ignore')
    updates = [line.split('HierCDF:', 1)[-1].strip() for line in lines.splitlines()
               if 'HierCDF:' in line]
    message = updates[-1] if updates else '模型已启动'
    batches = re.findall(r'epoch\s*=\s*(\d+),\s*batch\s*=\s*(\d+)', lines)
    if not batches:
        return {'progress': 0, 'message': message}
    epoch, batch = map(int, batches[-1])
    completed = (epoch - 1) * task['batches_per_epoch'] + batch + 1
    total = task['batches_per_epoch'] * task['total_epochs']
    return {'progress': min(99, round(completed / total * 100)) if total else 0,
            'message': message}

"""后台执行训练任务"""
def run_training_task(dataset_name, model_name, experiment_id, user_id, task_key):
    # HierCDF changes PyTorch's process-wide default dtype at import time.
    # Run comparison models one at a time so that it cannot alter NCDM's
    # parameters or Adam state while NCDM is training.
    with training_execution_lock:
        training_tasks[task_key] = {'status': 'training'}
        try:
            torch.set_default_dtype(torch.float64 if model_name == 'HierCDF' else torch.float32)
            _run_training_task(dataset_name, model_name, experiment_id, user_id, task_key)
        finally:
            torch.set_default_dtype(torch.float32)


def _run_training_task(dataset_name, model_name, experiment_id, user_id, task_key):
    import os
    try:
        print(f"========== 开始训练任务: {dataset_name}_{model_name} ==========")
        
        # CDF 系列模型单独走适配器训练逻辑。
        # 这里的展示名已经改成 IdpCDF / PCG-CDF，底层适配器目录也已经改成新名称。
        if model_name in {'IdpCDF', 'HierCDF', 'ConCDF', 'PCG-CDF'}:
            print(f"检测到 {model_name} 模型，使用专用适配器训练")

            device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
            cdf_dataset_name = 'Math1' if model_name == 'HierCDF' and dataset_name.casefold() in {'math', 'math1'} else dataset_name
            if model_name == 'IdpCDF':
                model_dir_name = 'IdpCDF'
            elif model_name == 'PCG-CDF':
                model_dir_name = 'PCGCDF'
            else:
                model_dir_name = model_name
            log_dir = _cdf_model_log_dir(model_dir_name, cdf_dataset_name)
            before_log_dirs = _snapshot_log_dirs(log_dir)
            if model_name == 'HierCDF':
                config_path = Path(settings.BASE_DIR) / 'learning' / 'diagnosis' / 'CMD_survey' / 'data' / cdf_dataset_name / 'config.py'
                train_path = config_path.parent / 'log_split__train_mini.csv'
                if cdf_dataset_name == 'Math1':
                    from .prepare_math1_hiercdf import prepare_math1_hiercdf
                    prepare_math1_hiercdf()
                spec = importlib.util.spec_from_file_location('hiercdf_progress_config', config_path)
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)
                batch_size = int(config_module.hparams.get('batch_size', 512))
                row_count = sum(1 for _ in train_path.open(encoding='utf-8')) - 1
                training_tasks[task_key].update({
                    'log_dir': str(log_dir),
                    'before_log_dirs': [str(path) for path in before_log_dirs],
                    'started_at': time.time(),
                    'batches_per_epoch': math.ceil(row_count / batch_size),
                    'total_epochs': int(config_module.hparams.get('epoch', 1)),
                })

            if model_name == 'ConCDF':
                # 包含关系模型使用 ConCDF 适配器。
                from learning.diagnosis.CMD_survey.model.ConCDF.ConCDF_adapter import train_concdm
                best_epoch, best_auc, best_acc, rmse = train_concdm(dataset_name, device=device)
            elif model_name == 'HierCDF':
                # 层次关系模型使用 HierCDF 适配器。
                if cdf_dataset_name == 'Math1':
                    device = 'cpu'
                from .researcher_cdf_compat import ensure_pandas_append
                ensure_pandas_append()
                from learning.diagnosis.CMD_survey.model.HierCDF.HierCDF_adapter import train_hiercdm
                best_epoch, best_auc, best_acc, rmse = train_hiercdm(cdf_dataset_name, device=device)
            elif model_name == 'IdpCDF':
                # IdpCDF 使用新的适配器。
                from learning.diagnosis.CMD_survey.model.IdpCDF.IdpCDF_adapter import train_basecdm
                best_epoch, best_auc, best_acc, rmse = train_basecdm(dataset_name, device=device)
            else:
                # PCG-CDF 使用新的适配器。
                from learning.diagnosis.CMD_survey.model.PCGCDF.PCGCDF_adapter import train_mixcdm
                best_epoch, best_auc, best_acc, rmse = train_mixcdm(dataset_name, device=device)

            log_file = _find_newest_log_file(log_dir, before_log_dirs)
            training_curves = _parse_cdf_training_curves(log_file)

            from .models import Experiment, ModelTrainingResult, Dataset, DiagnosisModel
            from django.contrib.auth import get_user_model

            User = get_user_model()
            dataset_obj = Dataset.objects.get(name=dataset_name)
            model_obj = DiagnosisModel.objects.get(name=model_name)

            if experiment_id:
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

            training_tasks[task_key] = {
                'status': 'completed',
                'result': {
                    'best_epoch': best_epoch,
                    'acc': best_acc,
                    'auc': best_auc,
                    'rmse': rmse,
                    'training_curves': training_curves
                }
            }
            print(f"========== 任务 {dataset_name}_{model_name} 完成 ==========")
            return


        from .diagnosis.dual_relation_ncdm import MODEL_NAMES as IRD_NCDM_MODEL_NAMES
        if model_name in IRD_NCDM_MODEL_NAMES:
            from .diagnosis.dual_relation_ncdm.platform import train_researcher_dataset

            result_data = train_researcher_dataset(dataset_name, model_name=model_name)
            best_epoch = result_data['best_epoch']
            best_auc = result_data['auc']
            best_acc = result_data['acc']
            rmse = result_data['rmse']
            training_curves = result_data.get('training_curves') or {
                'acc': [best_acc],
                'auc': [best_auc],
                'rmse': [rmse],
            }

            if experiment_id:
                from .models import Experiment, ModelTrainingResult, Dataset, DiagnosisModel
                from django.contrib.auth import get_user_model
                User = get_user_model()
                experiment = Experiment.objects.get(batch_id=experiment_id)
                dataset_obj = Dataset.objects.get(name=dataset_name)
                model_obj = DiagnosisModel.objects.get(name=model_name)
                ModelTrainingResult.objects.create(
                    experiment=experiment,
                    diagnosis_model=model_obj,
                    dataset=dataset_obj,
                    best_round=best_epoch,
                    acc=best_acc,
                    auc=best_auc,
                    rmse=rmse,
                    best_round_time=result_data.get('best_round_time', 0.0),
                    total_time=result_data.get('total_time', 0.0),
                    created_by=User.objects.get(id=user_id)
                )

            training_tasks[task_key] = {
                'status': 'completed',
                'result': {
                    'best_epoch': best_epoch,
                    'acc': best_acc,
                    'auc': best_auc,
                    'rmse': rmse,
                    'training_curves': training_curves
                }
            }
            print(f"========== 任务 {dataset_name}_{model_name} 完成 ==========")
            return

        # 每个任务使用独立配置；不修改进程工作目录、环境变量或模块缓存。
        from types import SimpleNamespace
        from .diagnosis.CMD_survey.dataloader import CD_DL

        input_dataset_name = 'Math1' if model_name == 'NCDM' and dataset_name.casefold() in {'math', 'math1'} else dataset_name
        if input_dataset_name == 'Math1' and model_name == 'NCDM':
            from .prepare_math1_hiercdf import prepare_math1_hiercdf
            prepare_math1_hiercdf()
        data_path = Path(settings.BASE_DIR) / 'learning' / 'diagnosis' / 'CMD_survey' / 'data' / input_dataset_name
        with (data_path / 'config.txt').open(encoding='utf-8') as config_file:
            config_file.readline()
            un, en, kn = map(int, config_file.readline().strip().split(','))
        training_config = SimpleNamespace(
            src=data_path / 'train.json',
            tgt=data_path / 'val.json',
            kn=kn,
            batch_size=128,
            lr=0.002,
        )

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
        model_module = importlib.import_module(f'learning.diagnosis.CMD_survey.model.{module_name}')

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
        src, tgt = CD_DL(training_config)
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

        # ========== 新增：修改训练方法，获取每轮数据 ==========
        device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        print(f"开始训练，使用设备: {device}")

        # 存储每轮的训练数据
        training_curves = {
            'acc': [],
            'auc': [],
            'rmse': []
        }

        # 检查模型是否有自定义的训练方法
        if hasattr(cdm, 'train_with_curves'):
            # 如果模型支持返回曲线数据
            result, training_curves = cdm.train_with_curves(
                train_data=src, test_data=tgt, epoch=10, device=device, lr=training_config.lr
            )
        elif hasattr(cdm, 'train_one_epoch'):
            # 否则手动记录每轮数据
            best_epoch = 0
            best_acc = 0
            best_auc = 0
            best_rmse = None

            # 假设训练10轮
            num_epochs = 10

            for epoch in range(num_epochs):
                print(f"训练第 {epoch + 1}/{num_epochs} 轮...")

                # 训练一轮（需要根据你的模型接口调整）
                # 这里假设模型有 train_one_epoch 方法
                cdm.train_one_epoch(train_data=src, device=device, lr=training_config.lr)
                epoch_acc, epoch_auc, epoch_rmse = evaluate_model(cdm, tgt, device)
                # 记录数据
                training_curves['acc'].append(epoch_acc)
                training_curves['auc'].append(epoch_auc)
                training_curves['rmse'].append(epoch_rmse)

                # 更新最佳结果
                if epoch_acc > best_acc:
                    best_acc = epoch_acc
                    best_auc = epoch_auc
                    best_rmse = epoch_rmse
                    best_epoch = epoch + 1

            result = (best_epoch, best_auc, best_acc, best_rmse)
        else:
            raise AttributeError(f"{model_name} does not provide train_with_curves or train_one_epoch.")

        print(f"训练完成，原始结果: {result}")
        print(f"训练曲线数据: {training_curves}")

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

        if experiment_id:
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

        # 更新任务状态 - 包含 training_curves
        training_tasks[task_key] = {
            'status': 'completed',
            'result': {
                'best_epoch': best_epoch,
                'acc': best_acc,
                'auc': best_auc,
                'rmse': rmse,
                'training_curves': training_curves  # 新增：返回训练曲线数据
            }
        }
        print(f"========== 任务 {dataset_name}_{model_name} 完成 ==========")

    except Exception as e:
        print(f"!!!!!!!!!! 训练任务出错: {str(e)} !!!!!!!!!!")
        import traceback
        traceback.print_exc()

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

        # 每次点击使用新的运行 ID，防止重复运行读到上一轮的状态或结果。
        run_id = uuid.uuid4().hex
        tasks = []
        # 为每个模型启动训练任务
        for model in models:
            # 启动后台线程训练
            task_key = f"{run_id}:{model.id}"
            training_tasks[task_key] = {'status': 'queued'}
            tasks.append({'id': task_key, 'model': model.name})

            thread = threading.Thread(
                target=run_training_task,
                args=(dataset.name, model.name, experiment.batch_id if experiment else None, request.user.id, task_key)
            )
            thread.start()

        return JsonResponse({
            'success': True,
            'message': '训练任务已启动',
            'experiment_id': experiment.batch_id if experiment else None,
            'tasks': tasks
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
        task = training_tasks[task_key]
        if task.get('status') == 'training' and 'log_dir' in task:
            return JsonResponse({'status': 'training', **_hiercdf_progress(task)})
        return JsonResponse(task)
    return JsonResponse({'status': 'not_found'})
