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


@login_required
@user_passes_test(is_teacher)
@require_POST
def review_candidates_api(request):
    """生成/刷新融合新增关系的审核候选，返回待审 + 历史列表"""
    try:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        teacher_ids = _teacher_subject_ids(request.user)
        subject_ids = _parse_subject_ids(payload.get('subject_ids'), teacher_ids)

        if len(subject_ids) < 2:
            return JsonResponse(
                {'status': 'error', 'message': '至少需要选择 2 个学科才能生成跨学科关系候选'},
                status=400, json_dumps_params={'ensure_ascii': False},
            )

        from graph_fusion.review import build_candidates
        candidates = build_candidates(subject_ids)
        pending = sum(1 for c in candidates if c['status'] == 'pending')
        return JsonResponse(
            {'status': 'success', 'candidates': candidates,
             'total': len(candidates), 'pending': pending},
            json_dumps_params={'ensure_ascii': False},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {'status': 'error', 'message': f'生成候选失败: {e}'},
            status=500, json_dumps_params={'ensure_ascii': False},
        )


@login_required
@user_passes_test(is_teacher)
@require_POST
def review_submit_api(request):
    """提交审核结果：通过的关系写回 KnowledgeGraph，拒绝的仅标记"""
    try:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        def _ids(raw):
            # review_id 为方向归一的知识点对 key（形如 "123_456"），按字符串收集
            if isinstance(raw, (list, tuple)):
                return [str(x).strip() for x in raw if str(x).strip()]
            return []

        approved_ids = _ids(payload.get('approved_ids'))
        rejected_ids = _ids(payload.get('rejected_ids'))
        if not approved_ids and not rejected_ids:
            return JsonResponse(
                {'status': 'error', 'message': '没有需要提交的审核项'},
                status=400, json_dumps_params={'ensure_ascii': False},
            )

        teacher_ids = _teacher_subject_ids(request.user)

        from graph_fusion.review import apply_review
        result = apply_review(
            approved_ids, rejected_ids, request.user,
            allowed_subject_ids=teacher_ids,
        )
        return JsonResponse(
            {'status': 'success', **result,
             'message': (f'审核完成：写回 {result["written_back"]} 条关系，'
                         f'通过 {result["approved"]}，拒绝 {result["rejected"]}')},
            json_dumps_params={'ensure_ascii': False},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {'status': 'error', 'message': f'提交审核失败: {e}'},
            status=500, json_dumps_params={'ensure_ascii': False},
        )


@login_required
@user_passes_test(is_teacher)
@require_POST
def edit_relation_api(request):
    """对评估中判定存疑的关系做人工修改（改关系类型）或删除"""
    try:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        relation_id = payload.get('relation_id')
        action = (payload.get('action') or '').strip()
        new_type = (payload.get('new_type') or '').strip() or None

        if relation_id in (None, '') or action not in ('update', 'delete'):
            return JsonResponse(
                {'status': 'error', 'message': '参数缺失：relation_id / action(update|delete)'},
                status=400, json_dumps_params={'ensure_ascii': False},
            )

        teacher_ids = _teacher_subject_ids(request.user)

        from graph_fusion.review import edit_relation
        result = edit_relation(
            relation_id, action, new_type=new_type, user=request.user,
            allowed_subject_ids=teacher_ids,
        )
        return JsonResponse(
            {'status': 'success', **result},
            json_dumps_params={'ensure_ascii': False},
        )
    except PermissionError as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=403, json_dumps_params={'ensure_ascii': False},
        )
    except ValueError as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=400, json_dumps_params={'ensure_ascii': False},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {'status': 'error', 'message': f'修改关系失败: {e}'},
            status=500, json_dumps_params={'ensure_ascii': False},
        )
