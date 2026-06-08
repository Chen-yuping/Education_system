"""
知识图谱融合 / 展示视图（核心接口）
======================================================================
对外提供两个接口，输出 JSON 与既有单科接口 (knowledge_points_api) 同构，
前端可直接复用现有渲染逻辑：

  1. fused_knowledge_graph_api  : 多科目融合后的全局统一图谱
  2. fused_knowledge_graph_page : 融合图谱展示页面（渲染模板，可选）

权限：沿用项目的教师身份校验。
"""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..models import Subject, TeacherSubject
from ..knowledge_graph_builder.graph_fusion import fuse_graph


def is_teacher(user):
    return getattr(user, 'user_type', None) == 'teacher'


@login_required
@user_passes_test(is_teacher)
@require_GET
def fused_knowledge_graph_api(request):
    """
    多课程 / 多学科融合图谱数据接口。

    查询参数:
      subject_ids=1,2,3   指定融合范围；缺省则融合「当前教师所授全部科目」。
    返回: {status, nodes, links, node_count, link_count,
           subject_count, merged_node_count, cross_subject_node_count}
    """
    try:
        raw = request.GET.get('subject_ids', '').strip()
        if raw:
            subject_ids = [int(x) for x in raw.split(',') if x.strip().isdigit()]
        else:
            # 默认：当前教师授课的全部科目
            subject_ids = list(
                TeacherSubject.objects.filter(teacher=request.user)
                .values_list('subject_id', flat=True)
            )

        result = fuse_graph(subject_ids)
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
def fused_knowledge_graph_page(request):
    """多学科融合图谱展示页面：教师选择若干学科，融合为全局统一图谱"""
    subjects = [
        ts.subject for ts in
        TeacherSubject.objects.filter(teacher=request.user).select_related('subject')
    ]
    context = {
        'subjects': subjects,
        'subject_count': len(subjects),
    }
    return render(request, 'teacher/knowledge_graph_fusion.html', context)
