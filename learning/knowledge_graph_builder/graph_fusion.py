"""
多学科 / 多课程知识图谱融合核心模块（最高优先级）
======================================================================
目标：把多个科目（Subject）各自的子图，融合成一张「无冲突、无重复、关系准确」
      的全局统一图谱，供前端渲染。

数据来源（严格遵守双库分工）：
  - 知识点实体          -> MySQL  (KnowledgePoint)
  - 知识点之间的关系    -> MySQL  (KnowledgeGraph，真相源) + Neo4j 镜像（可选加速/跨库一致）

融合算法四步：
  1. 跨课程 / 跨学科「同名知识点」对齐合并 —— 规范化名称做聚类，生成全局虚拟节点
  2. 关系重映射 —— 把原始关系的两端 kp_id 映射到合并后的全局节点 id
  3. 跨库关系去重 —— 同一对全局节点 + 同一关系类型只保留一条，方向冲突按优先级消解
  4. 全局图谱结构生成 —— 输出与既有单科 API 完全一致的 {nodes, links} JSON

输出 JSON 与 views_teacherknowledge.knowledge_points_api 对齐，前端零改动即可渲染。
"""
import re
import logging
from collections import defaultdict

from learning.models import Subject, KnowledgePoint, KnowledgeGraph

logger = logging.getLogger(__name__)


# 关系方向冲突消解优先级：值越大越「强」，冲突时保留强关系
# 前置(有向、最强语义) > 隶属(有向) > 关联(无向) > 相似(无向)
_REL_PRIORITY = {'前置': 4, '隶属': 3, '关联': 2, '相似': 1}

# 无向关系类型：融合时按无序节点对去重，避免 A→B / B→A 重复
_UNDIRECTED = {'关联', '相似'}


def normalize_name(name: str) -> str:
    """
    实体名称规范化（同名合并的判定键）。
    去除空白、全角/半角差异、大小写、常见标点，保证「数据结构」与「数据结构 」「Data Structure」可对齐。
    """
    if not name:
        return ""
    s = name.strip().lower()
    # 全角转半角（常见符号 + 空格）
    s = s.replace('　', ' ')
    s = re.sub(r'[\s\-_/（）()【】\[\]、,，.。:：;；]', '', s)
    return s


# ====================== Step 1: 跨学科同名知识点对齐合并 ======================
def _build_alignment(knowledge_points):
    """
    输入科目集合下的全部知识点，按规范化名称聚类。
    返回:
      kp_to_global : {kp_id -> global_id}           原始知识点 -> 全局合并节点
      global_nodes : {global_id -> 节点字典}         合并后的全局节点（含来源科目列表）
    全局节点 id 复用「该同名簇中最小的原始 kp_id」，保证 id 稳定且为正整数，
    前端 links 引用的 source/target 始终能在 nodes 中找到。
    """
    clusters = defaultdict(list)  # norm_name -> [kp, ...]
    for kp in knowledge_points:
        clusters[normalize_name(kp.name)].append(kp)

    kp_to_global = {}
    global_nodes = {}

    for norm, kps in clusters.items():
        if not norm:  # 跳过空名（脏数据），各自独立不参与合并
            for kp in kps:
                kp_to_global[kp.id] = kp.id
                global_nodes[kp.id] = {
                    'id': kp.id, 'name': kp.name,
                    'subjects': [kp.subject.name], 'merged_count': 1,
                }
            continue

        global_id = min(kp.id for kp in kps)               # 簇代表 id
        display_name = min(kps, key=lambda k: k.id).name   # 代表显示名（取最早创建）
        subjects = sorted({kp.subject.name for kp in kps})

        global_nodes[global_id] = {
            'id': global_id,
            'name': display_name,
            'subjects': subjects,          # 该知识点出现在哪些科目（跨学科证据）
            'merged_count': len(kps),      # 合并了多少个原始知识点
            'cross_subject': len(subjects) > 1,
        }
        for kp in kps:
            kp_to_global[kp.id] = global_id

    return kp_to_global, global_nodes


# ====================== Step 2+3: 关系重映射 + 跨库去重 + 冲突消解 ======================
def _fuse_relations(relationships, kp_to_global):
    """
    把原始关系映射到全局节点并去重。
      - 自环（合并后两端相同）丢弃
      - 无向关系（关联/相似）按无序对去重
      - 有向关系（前置/隶属）按有序对去重
      - 同一对节点出现多种关系类型时，按 _REL_PRIORITY 保留语义最强的一条
    返回 links 列表（全局 id 引用）。
    """
    # key -> {'source','target','rel_type','priority','directed'}
    fused = {}

    for rel in relationships:
        gs = kp_to_global.get(rel.source_id)
        gt = kp_to_global.get(rel.target_id)
        if gs is None or gt is None or gs == gt:
            continue  # 缺节点或自环，跳过

        rel_type = rel.relationship_type or '关联'
        priority = _REL_PRIORITY.get(rel_type, 2)
        directed = rel_type not in _UNDIRECTED

        # 去重键：无向用 frozenset，有向用有序元组
        key = (frozenset((gs, gt)), rel_type) if not directed else (gs, gt, rel_type)

        existing = fused.get(key)
        if existing is None:
            fused[key] = {
                'source': gs, 'target': gt,
                'rel_type': rel_type, 'priority': priority, 'directed': directed,
            }

    # 同一对节点的多关系冲突消解：每对节点只保留优先级最高的一条边
    by_pair = defaultdict(list)
    for item in fused.values():
        by_pair[frozenset((item['source'], item['target']))].append(item)

    links = []
    for pair, items in by_pair.items():
        best = max(items, key=lambda x: x['priority'])
        links.append({
            'source': best['source'],
            'target': best['target'],
            'relationship_type': best['rel_type'],
            'type': 'unidirectional' if best['directed'] else 'bidirectional',
            'arrow': best['directed'],
        })
    return links


# ====================== Step 4: 对外统一入口 ======================
def fuse_graph(subject_ids=None, semantic=True):
    """
    生成融合后的全局统一图谱（同名精确合并 + 四维语义对齐结合）。

    参数:
      subject_ids: 科目 id 列表。None/空 -> 融合全部科目（全局大图）。
      semantic: 是否启用 Learn 四维特征语义对齐（等价合并 + 泛化/应用软关联）。

    返回（与 knowledge_points_api 输出结构一致，前端零改动）:
      {
        'status': 'success',
        'nodes': [{'id','name','subjects','merged_count','cross_subject','exercise_count'}],
        'links': [{'source','target','relationship_type','type','arrow'}],
        'node_count', 'link_count',
        'subject_count', 'merged_node_count', 'cross_subject_node_count',
        'semantic_merged', 'semantic_links',
      }
    """
    subjects = Subject.objects.all()
    if subject_ids:
        subjects = subjects.filter(id__in=subject_ids)
    subject_id_list = list(subjects.values_list('id', flat=True))

    if not subject_id_list:
        return {'status': 'success', 'nodes': [], 'links': [],
                'node_count': 0, 'link_count': 0, 'subject_count': 0,
                'merged_node_count': 0, 'cross_subject_node_count': 0,
                'message': '无可融合的科目'}

    knowledge_points = list(
        KnowledgePoint.objects.filter(subject_id__in=subject_id_list).select_related('subject')
    )
    relationships = list(
        KnowledgeGraph.objects.filter(subject_id__in=subject_id_list)
        .only('source_id', 'target_id', 'relationship_type')
    )

    # Step 1: 同名对齐合并
    kp_to_global, global_nodes = _build_alignment(knowledge_points)

    # Step 1.5: 四维语义对齐（Learn 算法）。等价 -> 合并节点；泛化/应用 -> 软关联边
    semantic_merged = 0
    semantic_links = []
    if semantic and len(subject_id_list) >= 2:
        try:
            from .learn_fusion import align_subjects, TH_EQUIVALENT
            alignments = align_subjects(subject_id_list)
            for al in alignments:
                gs = kp_to_global.get(al['source_kp_id'])
                gt = kp_to_global.get(al['target_kp_id'])
                if gs is None or gt is None or gs == gt:
                    continue
                if al['type'] == 'EquivalentTo':
                    # 等价：把 gt 簇并入 gs，全局节点合并
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
                    # 泛化/应用：保留为'相似'软关联边（不合并节点）
                    semantic_links.append({
                        'source': gs, 'target': gt,
                        'relationship_type': '相似',
                        'type': 'bidirectional', 'arrow': False,
                        'semantic': True, 'confidence': al['confidence'],
                    })
            logger.info("[graph_fusion] 语义对齐：等价合并 %s，软关联 %s",
                        semantic_merged, len(semantic_links))
        except Exception as e:
            import traceback
            logger.warning("[graph_fusion] 语义对齐失败（跳过，不影响同名融合）：%s\n%s",
                           e, traceback.format_exc())

    # Step 2+3: 关系重映射 + 跨库去重 + 冲突消解
    links = _fuse_relations(relationships, kp_to_global)

    # 合并语义软关联边（去掉与已有边重复的节点对）
    if semantic_links:
        existing_pairs = {frozenset((l['source'], l['target'])) for l in links}
        for sl in semantic_links:
            if frozenset((sl['source'], sl['target'])) not in existing_pairs:
                links.append(sl)
                existing_pairs.add(frozenset((sl['source'], sl['target'])))

    # 习题关联数（沿用单科 API 的节点附加信息）；按全局节点聚合
    from learning.models import QMatrix
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
        'merged_node_count': merged,
        'cross_subject_node_count': cross,
        'semantic_merged': semantic_merged,
        'semantic_links': len(semantic_links),
        'message': (f'融合 {len(subject_id_list)} 个科目：{len(nodes)} 节点'
                    f'（同名+语义合并 {merged}，其中语义等价 {semantic_merged}），'
                    f'{len(links)} 关系（含语义软关联 {len(semantic_links)}）'),
    }

