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

        # 过滤参数：resource_file_id（优先）或 source（向后兼容）
        resource_file_id = request.GET.get('resource_file_id', '').strip()
        source_filter = request.GET.get('source', '').strip()
        source_list = [s.strip() for s in source_filter.split(',') if s.strip()] if source_filter else []

        # 获取该科目的知识点
        knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)

        rel_filter = {'subject_id': subject_id}

        if resource_file_id:
            # 按资源文件过滤：只显示该资源文件解析出的关系涉及的知识点
            resource_file_id = int(resource_file_id)
            rel_filter['resource_file_id'] = resource_file_id
            # 获取该资源文件关系涉及的所有知识点ID
            rel_kp_ids = set(
                KnowledgeGraph.objects.filter(
                    subject_id=subject_id, resource_file_id=resource_file_id
                ).values_list('source_id', flat=True)
            ) | set(
                KnowledgeGraph.objects.filter(
                    subject_id=subject_id, resource_file_id=resource_file_id
                ).values_list('target_id', flat=True)
            )
            if rel_kp_ids:
                knowledge_points = knowledge_points.filter(id__in=rel_kp_ids)
            else:
                knowledge_points = KnowledgePoint.objects.none()
        elif source_list:
            # 按来源筛选（向后兼容）
            from django.db.models import Q
            q_filter = Q()
            for s in source_list:
                q_filter |= Q(sources__contains=s)
            knowledge_points = knowledge_points.filter(q_filter)
            rel_filter['relation_source__in'] = source_list

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
        relationships = KnowledgeGraph.objects.filter(**rel_filter)

        links = []
        processed_pairs = set()

        for rel in relationships:
            source_id = rel.source_id
            target_id = rel.target_id
            pair_key = frozenset([source_id, target_id])

            if pair_key in processed_pairs:
                continue

            # 检查反向关系是否存在
            rev_filter = {
                'subject_id': subject_id,
                'source_id': target_id,
                'target_id': source_id,
            }
            if resource_file_id:
                rev_filter['resource_file_id'] = resource_file_id
            elif source_list:
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

        # 获取该科目下有知识图谱的资源文件列表（用于前端动态生成标签页）
        available_sources = list(set(
            list(KnowledgeGraph.objects.filter(
                subject_id=subject_id
            ).values_list('relation_source', flat=True).distinct())
            + [
                s.strip() for kp in KnowledgePoint.objects.filter(
                    subject_id=subject_id
                ).exclude(sources='').values_list('sources', flat=True)
                for s in kp.split(',') if s.strip()
            ]
        ))

        # 获取关联了 ResourceFile 的图谱资源文件列表
        resource_files_data = []
        resource_file_ids = KnowledgeGraph.objects.filter(
            subject_id=subject_id,
            resource_file__isnull=False
        ).values_list('resource_file_id', flat=True).distinct()
        for rf_id in set(resource_file_ids):
            try:
                rf = ResourceFile.objects.get(id=rf_id)
                resource_files_data.append({
                    'id': rf.id,
                    'title': rf.title,
                    'resource_type': rf.resource_type,
                })
            except ResourceFile.DoesNotExist:
                pass
        # 按 ID 排序
        resource_files_data.sort(key=lambda x: x['id'])

        response_data = {
            'status': 'success',
            'subject_id': subject_id,
            'subject_name': subject.name,
            'source': source_filter or ('resource_file' if resource_file_id else 'all'),
            'available_sources': available_sources,
            'available_resource_files': resource_files_data,
            'current_resource_file_id': resource_file_id,
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