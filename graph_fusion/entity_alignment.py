"""
Learn 四维特征实体对齐（移植自 multi_graph_fusion/entity_alignment.py）
======================================================================
数据源由 Learn 的 Neo4j 改为主项目 MySQL（learning.models.KnowledgePoint）。

四维加权置信度：
  语义相似度(本地BERT/字面降级) 0.35 + 名称字面 0.40 + 属性重叠 0.15 + 规则 0.10
对齐类型（按置信度阈值）：
  >=0.85 EquivalentTo 等价 -> 融合层合并为同一全局节点
  >=0.65 GeneralizeTo 泛化 -> 增加'相似'软关联边
  >=0.50 ApplyTo      应用 -> 增加'相似'软关联边
容错：jieba / BERT 不可用时自动降级，不影响主流程。
"""
import os
import logging
from functools import lru_cache
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# jieba 可选
try:
    import jieba
    _HAS_JIEBA = True
except Exception:
    jieba = None
    _HAS_JIEBA = False

# 置信度阈值（沿用 Learn EntityAlignment）
TH_EQUIVALENT = 0.85
TH_GENERALIZE = 0.65
TH_APPLY = 0.50

_WEIGHTS = {'semantic': 0.35, 'name': 0.40, 'attribute': 0.15, 'rule': 0.10}

# ---------------- 本地 BERT 语义相似度（单例，带降级） ----------------
_sim_model = None
_sim_tokenizer = None
_sim_inited = False


def _init_sim_model():
    global _sim_model, _sim_tokenizer, _sim_inited
    if _sim_inited:
        return
    _sim_inited = True
    # 强制离线：避免无缓存 + 坏代理的机器卡在 huggingface 联网校验上。
    # 没有本地缓存时会立即抛异常并优雅降级为字面相似度，而不是等待代理超时。
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    try:
        import torch  # noqa
        from transformers import AutoTokenizer, AutoModel
        # 模型来源优先级：settings.BERT_MODEL_PATH > 默认模型名（依赖本地缓存）
        name = 'bert-base-chinese'
        try:
            from django.conf import settings
            name = getattr(settings, 'BERT_MODEL_PATH', None) or name
        except Exception:
            pass
        _sim_tokenizer = AutoTokenizer.from_pretrained(name, local_files_only=True)
        _sim_model = AutoModel.from_pretrained(name, local_files_only=True)
        _sim_model.eval()
        logger.info("[fusion] 语义相似度 BERT 加载成功: %s", name)
    except Exception as e:
        logger.warning("[fusion] BERT 加载失败，语义相似度降级为字面：%s", e)
        _sim_model = None
        _sim_tokenizer = None


@lru_cache(maxsize=8192)
def _embed(text: str):
    """对单段文本做 BERT [CLS] 向量编码，带 LRU 缓存避免重复前向。"""
    import torch
    inp = _sim_tokenizer(text, return_tensors='pt', max_length=128, truncation=True)
    with torch.no_grad():
        out = _sim_model(**inp)
    return out.last_hidden_state[:, 0, :].squeeze().numpy()


def _semantic_similarity(t1: str, t2: str) -> float:
    _init_sim_model()
    if _sim_model is None or _sim_tokenizer is None:
        return SequenceMatcher(None, t1, t2).ratio()
    try:
        from scipy.spatial.distance import cosine
        return float(1 - cosine(_embed(t1), _embed(t2)))
    except Exception:
        return SequenceMatcher(None, t1, t2).ratio()


# ---------------- 四维特征 ----------------
def _name_similarity(n1: str, n2: str) -> float:
    return SequenceMatcher(None, n1, n2).ratio()


def _attribute_overlap(e1: dict, e2: dict) -> float:
    v1, v2 = e1.get('description'), e2.get('description')
    if v1 and v2:
        return SequenceMatcher(None, str(v1), str(v2)).ratio()
    return 0.0


def _confidence(e1: dict, e2: dict):
    sem = _semantic_similarity(
        f"{e1['name']} {e1.get('description', '') or ''}",
        f"{e2['name']} {e2.get('description', '') or ''}",
    )
    nam = _name_similarity(e1['name'], e2['name'])
    att = _attribute_overlap(e1, e2)
    rule = 0.1
    conf = (sem * _WEIGHTS['semantic'] + nam * _WEIGHTS['name']
            + att * _WEIGHTS['attribute'] + rule * _WEIGHTS['rule'])
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
    index = {}
    for idx, e in enumerate(entities):
        name = e['name']
        if _HAS_JIEBA:
            tokens = [w for w in jieba.cut(name) if len(w) >= 2]
        else:
            tokens = [name[i:i + 2] for i in range(len(name) - 1)] or [name]
        for tok in tokens:
            index.setdefault(tok, []).append(idx)
    return index


def align_cross_subject(entities1, entities2, name_prefilter=0.3):
    """对齐两学科实体集合（倒排索引候选 + 名称预过滤）"""
    if not entities1 or not entities2:
        return []
    index2 = _candidate_index(entities2)
    alignments = []
    processed = set()

    for e1 in entities1:
        name1 = e1['name']
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
                'source_subject': e1.get('subject'), 'target_subject': best.get('subject'),
            })
            processed.add(e1['kp_id'])
            processed.add(best['kp_id'])
    return alignments


def align_subjects(subject_ids, max_per_subject=500):
    """对科目集合两两跨学科对齐（数据源 MySQL），返回所有跨科目对齐对"""
    from learning.models import KnowledgePoint
    import random

    by_subject = {}
    qs = KnowledgePoint.objects.filter(subject_id__in=subject_ids).select_related('subject')
    for kp in qs:
        by_subject.setdefault(kp.subject_id, []).append({
            'name': kp.name, 'description': '', 'kp_id': kp.id,
            'subject': kp.subject.name, 'subject_id': kp.subject_id,
        })
    # 采样限制防止 O(n^2) 爆炸；固定种子保证同一组科目结果可复现
    rng = random.Random(42)
    for sid, ents in by_subject.items():
        if len(ents) > max_per_subject:
            by_subject[sid] = rng.sample(ents, max_per_subject)

    sids = list(by_subject.keys())
    all_alignments = []
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            all_alignments.extend(align_cross_subject(by_subject[sids[i]], by_subject[sids[j]]))
    logger.info("[fusion] 跨学科对齐完成，共 %s 对", len(all_alignments))
    return all_alignments
