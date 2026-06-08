"""
多学科知识图谱融合 + 融合图谱评估：教师端视图
======================================================================
路由（在 learning/urls.py 注册）：
  GET  multi-graph-fusion/                     -> page          融合页面
  GET  api/multi-graph-fusion/fuse/            -> fuse_api      执行融合，返回图谱 JSON
  POST api/multi-graph-fusion/evaluate/        -> evaluate_api  DeepSeek 评估融合图谱

权限：沿用教师身份校验。融合数据源为当前教师所授科目；可通过 subject_ids 指定。
"""
import json
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger(__name__)


def is_teacher(user):
    return getattr(user, 'user_type', None) == 'teacher'


def _teacher_subject_ids(user):
    """当前教师所授全部科目 id"""
    from learning.models import TeacherSubject
    return list(
        TeacherSubject.objects.filter(teacher=user).values_list('subject_id', flat=True)
    )


def _parse_subject_ids(raw, fallback_ids):
    """解析 subject_ids 参数（逗号分隔 / 列表），并限制在教师可访问范围内"""
    ids = []
    if isinstance(raw, (list, tuple)):
        ids = [int(x) for x in raw if str(x).strip().isdigit()]
    elif isinstance(raw, str) and raw.strip():
        ids = [int(x) for x in raw.split(',') if x.strip().isdigit()]
    if not ids:
        return list(fallback_ids)
    allowed = set(fallback_ids)
    return [i for i in ids if i in allowed] or list(fallback_ids)


@login_required
@user_passes_test(is_teacher)
def page(request):
    """融合页面：列出当前教师已导入的课程供勾选"""
    from learning.models import TeacherSubject
    subjects = [
        ts.subject for ts in
        TeacherSubject.objects.filter(teacher=request.user).select_related('subject')
    ]
    return render(request, 'teacher/multi_graph_fusion.html', {
        'subjects': subjects,
        'subject_count': len(subjects),
    })


@login_required
@user_passes_test(is_teacher)
@require_GET
def fuse_api(request):
    """执行多学科融合，返回 {status, nodes, links, ...融合统计}"""
    try:
        teacher_ids = _teacher_subject_ids(request.user)
        subject_ids = _parse_subject_ids(request.GET.get('subject_ids', ''), teacher_ids)

        from graph_fusion.fusion import fuse_graph
        result = fuse_graph(subject_ids, semantic=True)
        return JsonResponse(result, json_dumps_params={'ensure_ascii': False})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {'status': 'error', 'message': f'融合失败: {e}', 'nodes': [], 'links': []},
            status=500, json_dumps_params={'ensure_ascii': False},
        )


@login_required
@user_passes_test(is_teacher)
@require_POST
def evaluate_api(request):
    """DeepSeek 评估融合图谱质量，返回 {status, data: {fusionMetrics, entityStats, ...}}"""
    try:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        teacher_ids = _teacher_subject_ids(request.user)
        subject_ids = _parse_subject_ids(payload.get('subject_ids'), teacher_ids)

        if len(subject_ids) < 2:
            return JsonResponse(
                {'status': 'error', 'message': '至少需要选择 2 个学科才能评估融合质量'},
                status=400, json_dumps_params={'ensure_ascii': False},
            )

        sample_size = int(payload.get('sample_size', 15) or 15)

        from graph_fusion.deepseek_evaluator import evaluate_fusion
        data = evaluate_fusion(subject_ids, sample_size=sample_size)
        return JsonResponse(
            {'status': 'success', 'data': data},
            json_dumps_params={'ensure_ascii': False},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {'status': 'error', 'message': f'评估失败: {e}'},
            status=500, json_dumps_params={'ensure_ascii': False},
        )
