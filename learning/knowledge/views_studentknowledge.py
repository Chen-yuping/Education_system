# views_student.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from ..models import *
from django.contrib.auth.decorators import user_passes_test


def is_student(user):
    return user.user_type == 'student'


def detect_clusters(nodes, links):
    """
    使用简单的聚类算法检测知识点聚类
    基于节点之间的连接关系进行聚类
    """
    if not nodes:
        return {}
    
    # 构建邻接表
    adjacency = {str(node['id']): [] for node in nodes}
    for link in links:
        source_id = str(nodes[link['source']]['id'])
        target_id = str(nodes[link['target']]['id'])
        adjacency[source_id].append(target_id)
        adjacency[target_id].append(source_id)
    
    # 使用DFS进行聚类
    visited = set()
    clusters = []
    cluster_id = 0
    
    def dfs(node_id, cluster):
        visited.add(node_id)
        cluster.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            if neighbor not in visited:
                dfs(neighbor, cluster)
    
    for node in nodes:
        node_id = str(node['id'])
        if node_id not in visited:
            cluster = []
            dfs(node_id, cluster)
            clusters.append({
                'id': cluster_id,
                'nodes': cluster,
                'size': len(cluster)
            })
            cluster_id += 1
    
    # 为每个节点分配聚类ID
    node_cluster_map = {}
    for cluster in clusters:
        for node_id in cluster['nodes']:
            node_cluster_map[node_id] = cluster['id']
    
    return node_cluster_map, clusters

#"""学生知识点诊断图页面"""
@login_required
@user_passes_test(is_student)
def student_knowledge_diagnosis(request):

    try:
        # 方法1：直接查询学生的选课
        student_subjects = StudentSubject.objects.filter(
            student=request.user
        ).select_related('subject')

        # 如果没有找到选课，尝试用ID直接查询
        if student_subjects.count() == 0:
            # 查询数据库中是否有这个用户的选课
            user_exists_in_subjects = StudentSubject.objects.filter(
                student_id=request.user.id
            ).exists()

            # 查询该用户的所有选课（不指定student）
            user_all_subjects = StudentSubject.objects.filter(
                student_id=request.user.id
            )

        # 构建科目列表
        subjects = [ss.subject for ss in student_subjects]

        # 如果有科目，设置第一个为默认
        default_subject = subjects[0] if subjects else None

        context = {
            'subjects': subjects,
            'default_subject': default_subject,
            'user': request.user,
        }

        return render(request, 'student/student_diagnosis.html', context)
    except Exception as e:
        print(f"学生诊断页面错误: {e}")
        import traceback
        traceback.print_exc()
        context = {
            'subjects': [],
            'default_subject': None,
            'user': request.user,
        }
        return render(request, 'student/knowledge_diagnosis.html', context)

# """获取学生知识点诊断数据"""
@login_required
@user_passes_test(is_student)
@require_GET
def student_knowledge_data_api(request, subject_id):

    try:

        # 验证科目存在
        subject = get_object_or_404(Subject, id=subject_id)

        # 获取该科目的所有知识点
        knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)

        # 获取学生对每个知识点的掌握情况（只获取 diagnosis_model=3 的数据）
        student_diagnoses = StudentDiagnosis.objects.filter(
            student=request.user,
            knowledge_point__subject_id=subject_id,
            diagnosis_model_id=3  # 只获取 diagnosis_model=3 的数据
        ).select_related('knowledge_point')

        # 创建掌握程度字典
        mastery_dict = {}
        for diagnosis in student_diagnoses:
            mastery_dict[diagnosis.knowledge_point_id] = {
                'mastery_level': float(diagnosis.mastery_level or 0),
                'practice_count': diagnosis.practice_count or 0,
                'correct_count': diagnosis.correct_count or 0,
                'last_practiced': diagnosis.last_practiced.strftime('%Y-%m-%d') if diagnosis.last_practiced else None
            }

        # 构建节点数据
        nodes = []
        node_index_map = {}  # 用于快速查找节点索引

        for idx, kp in enumerate(knowledge_points):
            mastery_info = mastery_dict.get(kp.id, {
                'mastery_level': 0.0,
                'practice_count': 0,
                'correct_count': 0,
                'last_practiced': None
            })

            # 修正后的颜色判断逻辑
            mastery_level = mastery_info['mastery_level']
            if mastery_level >= 0.8:
                color = '#2ecc71'  # 绿色 - 掌握良好（≥80%）
            elif mastery_level >= 0.6:
                color = '#f39c12'  # 橙色 - 基本掌握（60%-80%）
            elif mastery_level >= 0.4:
                color = '#e74c3c'  # 红色 - 需要加强（40%-60%）
            elif mastery_level > 0:
                color = '#e74c3c'  # 红色 - 需要加强（0%-40%，但有数据）
            else:
                color = '#95a5a6'  # 灰色 - 未学习（0%，无数据）

            # 计算准确率
            practice_count = mastery_info['practice_count'] or 0
            correct_count = mastery_info['correct_count'] or 0
            accuracy = (correct_count / practice_count * 100) if practice_count > 0 else 0

            node_data = {
                'id': str(kp.id),  # 转为字符串
                'name': kp.name[:15] + '...' if len(kp.name) > 15 else kp.name,  # 限制名称长度
                'full_name': kp.name,
                'subject': subject.name,
                'mastery_level': mastery_level,
                'mastery_percent': round(mastery_level * 100, 1),
                'practice_count': practice_count,
                'correct_count': correct_count,
                'accuracy': round(accuracy, 1),
                'last_practiced': mastery_info['last_practiced'],
                'color': color,
                'index': idx  # 添加索引供D3使用
            }

            nodes.append(node_data)
            node_index_map[str(kp.id)] = idx  # 存储ID到索引的映射

        # 构建链接数据
        links = []
        processed_pairs = set()

        try:
            relationships = KnowledgeGraph.objects.filter(subject_id=subject_id)
        except Exception as db_error:
            print(f"查询知识图谱关系表失败: {db_error}")
            relationships = []

        for rel in relationships:
            source_id = str(rel.source_id)
            target_id = str(rel.target_id)
            pair_key = f"{min(source_id, target_id)}-{max(source_id, target_id)}"

            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            # 检查两个节点是否存在
            if source_id not in node_index_map or target_id not in node_index_map:
                continue

            # 检查反向关系
            reverse_exists = KnowledgeGraph.objects.filter(
                subject_id=subject_id,
                source_id=rel.target_id,
                target_id=rel.source_id
            ).exists()

            # 获取掌握程度
            source_mastery = mastery_dict.get(int(source_id), {'mastery_level': 0})['mastery_level']
            target_mastery = mastery_dict.get(int(target_id), {'mastery_level': 0})['mastery_level']
            avg_mastery = round((source_mastery + target_mastery) / 2, 2)

            link_data = {
                'source': node_index_map[source_id],  # 使用索引而不是ID
                'target': node_index_map[target_id],  # 使用索引而不是ID
                'source_id': source_id,
                'target_id': target_id,
                'type': 'bidirectional' if reverse_exists else 'unidirectional',
                'bidirectional': reverse_exists,
                'avg_mastery': avg_mastery,
                'strength': 1
            }
            links.append(link_data)

        # 执行聚类
        node_cluster_map, clusters = detect_clusters(nodes, links)
        
        # 为每个节点添加聚类信息
        for node in nodes:
            node['cluster'] = node_cluster_map.get(str(node['id']), 0)

        response_data = {
            'status': 'success',
            'student_id': request.user.id,
            'student_name': request.user.get_full_name() or request.user.username,
            'subject_id': subject_id,
            'subject_name': subject.name,
            'nodes': nodes,
            'links': links,
            'clusters': clusters,
            'node_count': len(nodes),
            'link_count': len(links),
            'cluster_count': len(clusters),
            'mastery_stats': {
                'total': len(nodes),
                'mastered': len([n for n in nodes if n['mastery_level'] >= 0.8]),
                'partial': len([n for n in nodes if 0.6 <= n['mastery_level'] < 0.8]),
                'weak': len([n for n in nodes if 0.4 <= n['mastery_level'] < 0.6]),
                'beginner': len([n for n in nodes if 0 < n['mastery_level'] < 0.4]),
                'none': len([n for n in nodes if n['mastery_level'] == 0])
            },
            'message': f'成功获取{len(nodes)}个知识点的掌握情况，分为{len(clusters)}个聚类'
        }
        return JsonResponse(response_data, json_dumps_params={'ensure_ascii': False})

    except Subject.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': f'科目ID {subject_id} 不存在',
            'nodes': [],
            'links': []
        }, status=404, json_dumps_params={'ensure_ascii': False})
    except Exception as e:
        print(f"API错误: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'status': 'error',
            'message': f'获取数据失败: {str(e)}',
            'nodes': [],
            'links': []
        }, status=500, json_dumps_params={'ensure_ascii': False})

