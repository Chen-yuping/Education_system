"""
Learn 多图谱融合桥接层（四维特征实体对齐）
======================================================================
移植 Learn/edu-knowledge-graph/backend/multi_graph_fusion 的实体对齐核心算法，
数据源从 Learn 的 Neo4j schema 改为当前系统的 MySQL（KnowledgePoint）。

四维加权置信度：
  - 语义相似度（本地 BERT 嵌入余弦）权重 0.35
  - 名称字面相似度                权重 0.40
  - 属性重叠度                    权重 0.15
  - 规则匹配度                    权重 0.10

对齐类型（按置信度）：
  - >= 0.85  EquivalentTo  等价  -> 融合层合并为同一全局节点
  - >= 0.65  GeneralizeTo  泛化  -> 增加'相似'软关联边
  - >= 0.50  ApplyTo       应用  -> 增加'相似'软关联边

依赖容错：
  - jieba 未安装 -> 倒排索引回退为字符级候选生成
  - 本地 BERT 不可用 -> 语义相似度回退为字面相似度
"""
import os
import sys
import logging
from difflib import SequenceMatcher

from django.conf import settings

logger = logging.getLogger(__name__)

# jieba 可选
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    jieba = None
    _HAS_JIEBA = False


# ====================== 本地 BERT 语义相似度（单例，带降级） ======================
_sim_model = None
_sim_tokenizer = None
_sim_inited = False


def _init_sim_model():
    """懒加载本地 bert-base-chinese；失败则置 None（降级为字面相似度）"""
    global _sim_model, _sim_tokenizer, _sim_inited
    if _sim_inited:
        return
    _sim_inited = True
    try:
        import torch  # noqa
        from transformers import AutoTokenizer, AutoModel
        local_path = r'C:\Users\30748\.cache\huggingface\hub\models--bert-base-chinese\snapshots\8f23c25b06e129b6c986331a13d8d025a92cf0ea'
        name = local_path if os.path.isdir(local_path) else 'bert-base-chinese'
        _sim_tokenizer = AutoTokenizer.from_pretrained(name, local_files_only=True)
        _sim_model = AutoModel.from_pretrained(name, local_files_only=True)
        _sim_model.eval()
        logger.info("[learn_fusion] 语义相似度 BERT 加载成功")
    except Exception as e:
        logger.warning("[learn_fusion] BERT 加载失败，语义相似度降级为字面：%s", e)
        _sim_model = None
        _sim_tokenizer = None


def _semantic_similarity(text1: str, text2: str) -> float:
    """两文本语义相似度；BERT 不可用时退化为字面相似度"""
    _init_sim_model()
    if _sim_model is None or _sim_tokenizer is None:
        return SequenceMatcher(None, text1, text2).ratio()
    try:
        import torch
        import numpy as np
        from scipy.spatial.distance import cosine

        def emb(t):
            inp = _sim_tokenizer(t, return_tensors='pt', max_length=128, truncation=True)
            with torch.no_grad():
                out = _sim_model(**inp)
            return out.last_hidden_state[:, 0, :].squeeze().numpy()

        e1, e2 = emb(text1), emb(text2)
        return float(1 - cosine(e1, e2))
    except Exception as e:
        logger.debug("[learn_fusion] 语义相似度计算失败，降级：%s", e)
        return SequenceMatcher(None, text1, text2).ratio()


# ====================== 四维特征对齐 ======================
# 置信度阈值（沿用 Learn EntityAlignment）
TH_EQUIVALENT = 0.85   # 等价 -> 合并节点
TH_GENERALIZE = 0.65   # 泛化 -> 软关联
TH_APPLY = 0.50        # 应用 -> 软关联

_WEIGHTS = {'semantic': 0.35, 'name': 0.40, 'attribute': 0.15, 'rule': 0.10}


def _name_similarity(n1: str, n2: str) -> float:
    return SequenceMatcher(None, n1, n2).ratio()


def _attribute_overlap(e1: dict, e2: dict) -> float:
    """属性重叠度：当前以 description 是否同为空/同非空粗略衡量，预留扩展"""
    attrs = ['description']
    overlap = 0
    for a in attrs:
        v1, v2 = e1.get(a), e2.get(a)
        if v1 and v2:
            overlap += SequenceMatcher(None, str(v1), str(v2)).ratio()
    return overlap / len(attrs) if attrs else 0.0


def _confidence(e1: dict, e2: dict):
    """四维加权置信度"""
    sem = _semantic_similarity(
        f"{e1['name']} {e1.get('description', '') or ''}",
        f"{e2['name']} {e2.get('description', '') or ''}",
    )
    nam = _name_similarity(e1['name'], e2['name'])
    att = _attribute_overlap(e1, e2)
    rule = 0.1  # 默认低规则匹配，避免无关实体高分
    conf = (sem * _WEIGHTS['semantic'] + nam * _WEIGHTS['name']
            + att * _WEIGHTS['attribute'] + rule * _WEIGHTS['rule'])
    # 语义与名称都很低时强制压低
    if sem < 0.5 and nam < 0.5:
        conf *= 0.6
    return conf, {'semantic': sem, 'name': nam, 'attribute': att}


def _alignment_type(conf: float):
    if conf >= TH_EQUIVALENT:
        return 'EquivalentTo'
    if conf >= TH_GENERALIZE:
        return 'GeneralizeTo'
    if conf >= TH_APPLY:
        return 'ApplyTo'
    return None


def _candidate_index(entities):
    """构建候选倒排索引：词/字 -> 实体下标列表。jieba 可选。"""
    index = {}
    for idx, e in enumerate(entities):
        name = e['name']
        if _HAS_JIEBA:
            tokens = [w for w in jieba.cut(name) if len(w) >= 2]
        else:
            # 回退：相邻二元字 + 单字
            tokens = [name[i:i + 2] for i in range(len(name) - 1)] or [name]
        for tok in tokens:
            index.setdefault(tok, []).append(idx)
    return index


def align_cross_subject(entities1, entities2, name_prefilter=0.3):
    """
    对齐两个学科的实体集合（带倒排索引候选 + 名称预过滤）。
    entities*: [{'name','description','kp_id','subject'}]
    返回对齐对列表 [{'source_kp_id','target_kp_id','source','target','type','confidence'}]
    """
    if not entities1 or not entities2:
        return []

    index2 = _candidate_index(entities2)
    alignments = []
    processed = set()

    for e1 in entities1:
        name1 = e1['name']
        # 候选：倒排命中的实体下标
        cand_idx = set()
        if _HAS_JIEBA:
            tokens = [w for w in jieba.cut(name1) if len(w) >= 2]
        else:
            tokens = [name1[i:i + 2] for i in range(len(name1) - 1)] or [name1]
        for tok in tokens:
            cand_idx.update(index2.get(tok, []))
        candidates = [entities2[i] for i in cand_idx] if cand_idx else entities2

        best, best_conf, best_feat = None, 0.0, None
        for e2 in candidates:
            if e2['kp_id'] in processed:
                continue
            if _name_similarity(name1, e2['name']) < name_prefilter:
                continue
            conf, feat = _confidence(e1, e2)
            if conf > best_conf:
                best, best_conf, best_feat = e2, conf, feat

        atype = _alignment_type(best_conf)
        if atype and best:
            alignments.append({
                'source_kp_id': e1['kp_id'], 'target_kp_id': best['kp_id'],
                'source': name1, 'target': best['name'],
                'type': atype, 'confidence': round(best_conf, 4),
                'features': best_feat,
            })
            processed.add(e1['kp_id'])
            processed.add(best['kp_id'])

    return alignments


def align_subjects(subject_ids, max_per_subject=500):
    """
    对给定科目集合两两做跨学科实体对齐（数据源 MySQL）。
    返回所有对齐对（去掉同科目内对齐，只保留跨科目）。
    """
    from learning.models import KnowledgePoint

    # 按科目分组取实体
    by_subject = {}
    qs = KnowledgePoint.objects.filter(subject_id__in=subject_ids).select_related('subject')
    for kp in qs:
        rec = {
            'name': kp.name,
            'description': '',  # KnowledgePoint 无描述字段，留空（语义退化为名称）
            'kp_id': kp.id,
            'subject': kp.subject.name,
            'subject_id': kp.subject_id,
        }
        by_subject.setdefault(kp.subject_id, []).append(rec)

    # 采样限制，防止 O(n^2) 爆炸
    import random
    for sid, ents in by_subject.items():
        if len(ents) > max_per_subject:
            by_subject[sid] = random.sample(ents, max_per_subject)

    sids = list(by_subject.keys())
    all_alignments = []
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            pairs = align_cross_subject(by_subject[sids[i]], by_subject[sids[j]])
            all_alignments.extend(pairs)

    logger.info("[learn_fusion] 跨学科对齐完成，共 %s 对", len(all_alignments))
    return all_alignments
