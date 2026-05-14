# views_knowledge.py 中修改知识图谱相关视图
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from ..models import *
from django.contrib.auth.decorators import user_passes_test

#教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

@login_required
@user_passes_test(is_teacher)
def knowledge_graph(request):
    """知识点关系图页面"""
    try:
        # 获取当前老师授课的科目
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).select_related('subject')

        subjects = [ts.subject for ts in teacher_subjects]

        # 如果有科目，设置第一个为默认
        default_subject = subjects[0] if subjects else None
        
        # 获取subject_id参数
        subject_id = request.GET.get('subject_id')
        subject = None
        if subject_id:
            subject = Subject.objects.get(id=subject_id)

        context = {
            'subjects': subjects,
            'default_subject': default_subject,
            'subject': subject,
        }

        return render(request, 'teacher/knowledge_graph.html', context)
    except Exception as e:
        print(f"知识图谱页面错误: {e}")
        # 返回空列表，让前端显示"请选择科目"
        context = {
            'subjects': [],
            'default_subject': None,
            'subject': None,
        }
        return render(request, 'teacher/knowledge_graph.html', context)


@login_required
@user_passes_test(is_teacher)
@require_GET
def knowledge_points_api(request, subject_id):
    """获取知识点关系图数据 - 从MySQL获取数据"""
    try:

        # 验证科目存在
        subject = Subject.objects.get(id=subject_id)

        # source 过滤参数：教材/教案/课件，为空时返回全部（融合视图）
        # 支持逗号分隔多个来源，如 ?source=教案,课件
        source_filter = request.GET.get('source', '').strip()
        source_list = [s.strip() for s in source_filter.split(',') if s.strip()] if source_filter else []

        # 获取该科目的知识点
        knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)

        # 按来源筛选：使用 KnowledgePoint 的 sources 字段（删除关系后仍然保留）
        if source_list:
            from django.db.models import Q
            q_filter = Q()
            for s in source_list:
                q_filter |= Q(sources__contains=s)
            knowledge_points = knowledge_points.filter(q_filter)

        # 构建节点数据
        nodes = []
        for kp in knowledge_points:
            exercise_count = QMatrix.objects.filter(knowledge_point=kp).count()

            nodes.append({
                'id': kp.id,
                'name': kp.name,
                'subject': subject.name,
                'exercise_count': exercise_count
            })

        # 构建关系查询
        rel_filter = {'subject_id': subject_id}
        if source_list:
            rel_filter['relation_source__in'] = source_list

        relationships = KnowledgeGraph.objects.filter(**rel_filter)

        links = []
        processed_pairs = set()

        for rel in relationships:
            source_id = rel.source_id
            target_id = rel.target_id
            pair_key = frozenset([source_id, target_id])

            if pair_key in processed_pairs:
                continue

            # 检查反向关系是否存在（同源过滤下检查同源，全量视图则跨源检查）
            rev_filter = {
                'subject_id': subject_id,
                'source_id': target_id,
                'target_id': source_id,
            }
            if source_list:
                rev_filter['relation_source__in'] = source_list

            reverse_exists = KnowledgeGraph.objects.filter(**rev_filter).exists()

            if reverse_exists:
                links.append({
                    'source': min(source_id, target_id),
                    'target': max(source_id, target_id),
                    'type': 'bidirectional',
                    'arrow': False,
                    'relationship_type': rel.relationship_type,
                })
            else:
                links.append({
                    'source': source_id,
                    'target': target_id,
                    'type': 'unidirectional',
                    'arrow': True,
                    'relationship_type': rel.relationship_type,
                })

            processed_pairs.add(pair_key)

        response_data = {
            'status': 'success',
            'subject_id': subject_id,
            'subject_name': subject.name,
            'source': source_filter or 'all',
            'available_sources': list(set(
                list(KnowledgeGraph.objects.filter(
                    subject_id=subject_id
                ).values_list('relation_source', flat=True).distinct())
                + [
                    s.strip() for kp in KnowledgePoint.objects.filter(
                        subject_id=subject_id
                    ).exclude(sources='').values_list('sources', flat=True)
                    for s in kp.split(',') if s.strip()
                ]
            )),
            'nodes': nodes,
            'links': links,
            'node_count': len(nodes),
            'link_count': len(links),
            'data_source': 'mysql',
            'message': f'成功获取{len(nodes)}个知识点和{len(links)}个关系'
        }
        return JsonResponse(response_data)

    except Subject.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': f'科目ID {subject_id} 不存在',
            'nodes': [],
            'links': []
        }, status=404)
    except Exception as e:
        print(f"API错误: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'status': 'error',
            'message': f'获取数据失败: {str(e)}',
            'nodes': [],
            'links': []
        }, status=500)