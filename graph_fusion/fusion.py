"""
多学科 / 多课程知识图谱融合核心
======================================================================
把多个科目（Subject）各自子图融合成一张「无冲突、无重复、关系准确」的
全局统一图谱，供前端渲染。

融合算法：
  Step 1   跨课程同名知识点对齐合并（规范化名称聚类，生成全局虚拟节点）
  Step 1.5 Learn 四维语义对齐（等价->合并节点；泛化/应用->软关联边）
  Step 2+3 关系重映射 + 跨库去重 + 方向冲突消解
  Step 4   输出 {nodes, links} JSON（与单科 API 同构，前端零改动）
"""
import re
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# 关系方向冲突消解优先级：前置 > 隶属 > 关联 > 相似
_REL_PRIORITY = {'前置': 4, '隶属': 3, '关联': 2, '相似': 1}
# 无向关系类型：融合时按无序节点对去重
_UNDIRECTED = {'关联', '相似'}


def normalize_name(name: str) -> str:
    """实体名称规范化（同名合并判定键）：去空白/全角/大小写/常见标点"""
    if not name:
        return ""
    s = name.strip().lower().replace('　', ' ')
    s = re.sub(r'[\s\-_/（）()【】\[\]、,，.。:：;；]', '', s)
    return s


# ====================== Step 1: 同名知识点对齐合并 ======================
def _build_alignment(knowledge_points):
    clusters = defaultdict(list)
    for kp in knowledge_points:
        clusters[normalize_name(kp.name)].append(kp)

    kp_to_global = {}
    global_nodes = {}

    for norm, kps in clusters.items():
        if not norm:  # 空名脏数据，各自独立
            for kp in kps:
                kp_to_global[kp.id] = kp.id
                global_nodes[kp.id] = {
                    'id': kp.id, 'name': kp.name,
                    'subjects': [kp.subject.name], 'merged_count': 1,
                    'cross_subject': False,
                }
            continue

        global_id = min(kp.id for kp in kps)
        display_name = min(kps, key=lambda k: k.id).name
        subjects = sorted({kp.subject.name for kp in kps})
        global_nodes[global_id] = {
            'id': global_id, 'name': display_name,
            'subjects': subjects, 'merged_count': len(kps),
            'cross_subject': len(subjects) > 1,
        }
        for kp in kps:
            kp_to_global[kp.id] = global_id

    return kp_to_global, global_nodes


# ====================== Step 2+3: 关系重映射 + 去重 + 冲突消解 ======================
def _fuse_relations(relationships, kp_to_global):
    fused = {}
    for rel in relationships:
        gs = kp_to_global.get(rel.source_id)
        gt = kp_to_global.get(rel.target_id)
        if gs is None or gt is None or gs == gt:
            continue
        rel_type = rel.relationship_type or '关联'
        priority = _REL_PRIORITY.get(rel_type, 2)
        directed = rel_type not in _UNDIRECTED
        key = (frozenset((gs, gt)), rel_type) if not directed else (gs, gt, rel_type)
        if key not in fused:
            fused[key] = {'source': gs, 'target': gt, 'rel_type': rel_type,
                          'priority': priority, 'directed': directed}

    by_pair = defaultdict(list)
    for item in fused.values():
        by_pair[frozenset((item['source'], item['target']))].append(item)

    links = []
    for _, items in by_pair.items():
        best = max(items, key=lambda x: x['priority'])
        links.append({
            'source': best['source'], 'target': best['target'],
            'relationship_type': best['rel_type'],
            'type': 'unidirectional' if best['directed'] else 'bidirectional',
            'arrow': best['directed'],
        })
    return links


# ====================== Step 4: 对外统一入口 ======================
def fuse_graph(subject_ids=None, semantic=True):
    """
    生成融合后的全局统一图谱（同名精确合并 + 四维语义对齐）。

    参数:
      subject_ids: 科目 id 列表。None/空 -> 融合全部科目。
      semantic   : 是否启用 Learn 四维语义对齐。
    返回 dict（含 nodes/links + 融合统计 + 对齐对 alignments）。
    """
    from learning.models import Subject, KnowledgePoint, KnowledgeGraph, QMatrix

    subjects = Subject.objects.all()
    if subject_ids:
        subjects = subjects.filter(id__in=subject_ids)
    subject_id_list = list(subjects.values_list('id', flat=True))

    if not subject_id_list:
        return {'status': 'success', 'nodes': [], 'links': [],
                'node_count': 0, 'link_count': 0, 'subject_count': 0,
                'merged_node_count': 0, 'cross_subject_node_count': 0,
                'alignments': [], 'message': '无可融合的科目'}

    knowledge_points = list(
        KnowledgePoint.objects.filter(subject_id__in=subject_id_list).select_related('subject')
    )
    relationships = list(
        KnowledgeGraph.objects.filter(subject_id__in=subject_id_list)
        .only('source_id', 'target_id', 'relationship_type')
    )

    # Step 1: 同名对齐合并
    kp_to_global, global_nodes = _build_alignment(knowledge_points)

    # Step 1.5: 四维语义对齐
    semantic_merged = 0
    semantic_links = []
    alignment_pairs = []
    if semantic and len(subject_id_list) >= 2:
        try:
            from .entity_alignment import align_subjects
            alignments = align_subjects(subject_id_list)
            alignment_pairs = alignments
            for al in alignments:
                gs = kp_to_global.get(al['source_kp_id'])
                gt = kp_to_global.get(al['target_kp_id'])
                if gs is None or gt is None or gs == gt:
                    continue
                if al['type'] == 'EquivalentTo':
                    keep, drop = (gs, gt) if gs <= gt else (gt, gs)
                    for kid, gid in list(kp_to_global.items()):
                        if gid == drop:
                            kp_to_global[kid] = keep
                    if drop in global_nodes:
                        dn = global_nodes.pop(drop)
                        kn = global_nodes[keep]
                        kn['subjects'] = sorted(set(kn.get('subjects', [])) | set(dn.get('subjects', [])))
                        kn['merged_count'] = kn.get('merged_count', 1) + dn.get('merged_count', 1)
                        kn['cross_subject'] = len(kn['subjects']) > 1
                    semantic_merged += 1
                else:
                    semantic_links.append({
                        'source': gs, 'target': gt, 'relationship_type': '相似',
                        'type': 'bidirectional', 'arrow': False,
                        'semantic': True, 'confidence': al['confidence'],
                    })
            logger.info("[fusion] 语义对齐：等价合并 %s，软关联 %s", semantic_merged, len(semantic_links))
        except Exception as e:
            import traceback
            logger.warning("[fusion] 语义对齐失败（跳过）：%s\n%s", e, traceback.format_exc())

    # Step 2+3: 关系重映射 + 去重 + 冲突消解
    links = _fuse_relations(relationships, kp_to_global)

    # 合并语义软关联边（去掉与已有边重复的节点对）
    if semantic_links:
        existing_pairs = {frozenset((l['source'], l['target'])) for l in links}
        for sl in semantic_links:
            pair = frozenset((sl['source'], sl['target']))
            if pair not in existing_pairs:
                links.append(sl)
                existing_pairs.add(pair)

    # 习题关联数（按全局节点聚合）
    ex_counts = defaultdict(int)
    qm = QMatrix.objects.filter(
        knowledge_point__subject_id__in=subject_id_list
    ).values_list('knowledge_point_id', flat=True)
    for kp_id in qm:
        gid = kp_to_global.get(kp_id)
        if gid is not None:
            ex_counts[gid] += 1

    nodes = []
    for gid, node in global_nodes.items():
        node = dict(node)
        node['exercise_count'] = ex_counts.get(gid, 0)
        node.setdefault('cross_subject', len(node.get('subjects', [])) > 1)
        nodes.append(node)

    merged = sum(1 for n in nodes if n.get('merged_count', 1) > 1)
    cross = sum(1 for n in nodes if n.get('cross_subject'))

    return {
        'status': 'success',
        'nodes': nodes,
        'links': links,
        'node_count': len(nodes),
        'link_count': len(links),
        'subject_count': len(subject_id_list),
        'subject_ids': subject_id_list,
        'merged_node_count': merged,
        'cross_subject_node_count': cross,
        'semantic_merged': semantic_merged,
        'semantic_links': len(semantic_links),
        'alignments': alignment_pairs,
        'message': (f'融合 {len(subject_id_list)} 个科目：{len(nodes)} 节点'
                    f'（合并 {merged}，其中语义等价 {semantic_merged}），'
                    f'{len(links)} 关系（含语义软关联 {len(semantic_links)}）'),
    }
