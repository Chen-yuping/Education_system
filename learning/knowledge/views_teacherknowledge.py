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

        context = {
            'subjects': subjects,
            'default_subject': default_subject,
        }

        return render(request, 'teacher/knowledge_graph.html', context)
    except Exception as e:
        print(f"知识图谱页面错误: {e}")
        # 返回空列表，让前端显示"请选择科目"
        context = {
            'subjects': [],
            'default_subject': None,
        }
        return render(request, 'teacher/knowledge_graph.html', context)


@login_required
@user_passes_test(is_teacher)
@require_GET
def knowledge_points_api(request, subject_id):
    """获取知识点关系图数据 - 返回JSON格式"""
    try:

        # 验证科目存在
        subject = Subject.objects.get(id=subject_id)

        # 获取该科目的所有知识点
        knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)

        # 构建节点数据
        nodes = []
        for kp in knowledge_points:
            # 获取每个知识点的习题数量（从QMatrix统计）

            # 获取科目对应的习题模型
            exercise_model = None
            if subject.name == '数学':
                exercise_model = MathExercise
            elif subject.name == '语文':
                exercise_model = ChineseExercise
            elif subject.name == '英语':
                exercise_model = EnglishExercise

            exercise_count = 0
            if exercise_model:
                # 统计与该知识点相关的习题数量
                exercise_count = QMatrix.objects.filter(
                    content_type__model=exercise_model._meta.model_name,
                    knowledge_point=kp
                ).count()

            nodes.append({
                'id': kp.id,
                'name': kp.name,
                'subject': subject.name,
                'exercise_count': exercise_count
            })

        # 获取该科目的所有知识点关系
        relationships = KnowledgeGraph.objects.filter(subject_id=subject_id)

        # 处理关系，合并双向关系
        links = []
        processed_pairs = set()

        for rel in relationships:
            # 创建唯一标识符
            source_id = rel.source_id
            target_id = rel.target_id
            pair_key = frozenset([source_id, target_id])

            # 跳过已处理的关系对
            if pair_key in processed_pairs:
                continue

            # 检查是否存在反向关系
            reverse_exists = KnowledgeGraph.objects.filter(
                subject_id=subject_id,
                source_id=target_id,
                target_id=source_id
            ).exists()

            if reverse_exists:
                # 双向关系 - 无箭头
                links.append({
                    'source': min(source_id, target_id),
                    'target': max(source_id, target_id),
                    'type': 'bidirectional',
                    'arrow': False
                })
            else:
                # 单向关系 - 有箭头
                links.append({
                    'source': source_id,
                    'target': target_id,
                    'type': 'unidirectional',
                    'arrow': True
                })

            # 标记已处理
            processed_pairs.add(pair_key)

        response_data = {
            'status': 'success',
            'subject_id': subject_id,
            'subject_name': subject.name,
            'nodes': nodes,
            'links': links,
            'node_count': len(nodes),
            'link_count': len(links),
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
        return JsonResponse({
            'status': 'error',
            'message': f'获取数据失败: {str(e)}',
            'nodes': [],
            'links': []
        }, status=500)