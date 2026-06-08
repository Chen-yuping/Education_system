"""
Learn 知识抽取桥接层
======================================================================
封装对 Learn/edu-knowledge-graph/backend/knowledge_extractor.py 中
KnowledgeExtractor（BERT-CRF + 规则 + 领域词典）的调用，使其可直接
被当前 Django 项目的知识图谱构建管线使用。

职责：
  1. 隔离 Learn 源码对 sys.path / 工作目录 / 本地模型路径的依赖
  2. 进程内单例（BERT 较重，初始化 ~7s，只加载一次）
  3. 把 Learn 的 (entities, relations) 转成 pipeline 期望的三元组格式
  4. 英文关系类型 -> 当前系统 4 种中文关系（隶属/关联/前置/相似）
  5. 全程容错：任何失败都返回空并打日志，绝不中断上传流程
"""
import os
import sys
import io
import re
import threading
import logging

from django.conf import settings

_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout

logger = logging.getLogger(__name__)

# ---------- 英文关系类型 -> 现有 4 种中文关系 ----------
# 当前 KnowledgeGraph.RELATION_CHOICES: 隶属 / 关联 / 前置 / 相似
_REL_MAP = {
    'HAS_PREREQUISITE': '前置',
    'DEPENDS_ON': '前置',
    'COMPOSED_OF': '隶属',
    'BELONGS_TO': '隶属',
    'SUBTYPE_OF': '隶属',
    'RELATED_TO': '关联',
    'COMPARED_WITH': '关联',
    'APPLIES_TO': '关联',
    'AFFECTS': '关联',
    'USES': '关联',
    'IMPLEMENTS': '关联',
    'DEFINED_AS': '关联',
    'DESCRIBES': '关联',
}


def _map_relation(rel_type: str) -> str:
    """英文关系 -> 中文；未知一律归为'关联'"""
    return _REL_MAP.get((rel_type or '').upper(), '关联')


# ---------- Learn backend 目录定位 ----------
def _get_backend_dir() -> str:
    """返回 Learn backend 绝对路径；优先读 settings.LEARN_KG_BACKEND_DIR"""
    configured = getattr(settings, 'LEARN_KG_BACKEND_DIR', None)
    if configured and os.path.isdir(configured):
        return configured
    base = getattr(settings, 'BASE_DIR', None)
    if base:
        guess = os.path.join(str(base), 'Learn', 'edu-knowledge-graph', 'backend')
        if os.path.isdir(guess):
            return guess
    return ''


# ---------- 单例 KnowledgeExtractor ----------
_extractor = None
_extractor_lock = threading.Lock()
_extractor_failed = False  # 初始化失败后不再重试，避免每次上传都卡 7s


def _get_extractor():
    """进程内懒加载单例。失败返回 None（调用方降级）"""
    global _extractor, _extractor_failed
    if _extractor is not None:
        return _extractor
    if _extractor_failed:
        return None

    with _extractor_lock:
        if _extractor is not None:
            return _extractor
        if _extractor_failed:
            return None

        backend_dir = _get_backend_dir()
        if not backend_dir:
            logger.warning("[learn_extractor] 未找到 Learn backend 目录，知识抽取降级")
            _extractor_failed = True
            return None

        proj_dir = os.path.dirname(backend_dir)  # edu-knowledge-graph 根
        src_dir = os.path.join(proj_dir, 'src')

        # Learn 源码大量使用相对 import / 相对路径（模型权重、词典），
        # 需注入 sys.path 并临时切换 cwd 到 backend 目录
        for p in (backend_dir, proj_dir, src_dir):
            if p and os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)

        old_cwd = os.getcwd()
        try:
            os.chdir(backend_dir)
            from knowledge_extractor import KnowledgeExtractor
            logger.info("[learn_extractor] 正在初始化 BERT-CRF 知识抽取器（首次较慢）...")
            _extractor = KnowledgeExtractor(use_ollama=False)
            logger.info(
                "[learn_extractor] 初始化完成 use_bert=%s use_bert_re=%s 词典领域=%s",
                getattr(_extractor, 'use_bert', None),
                getattr(_extractor, 'use_bert_re', None),
                len(getattr(_extractor, 'domain_dictionaries', {})),
            )
        except Exception as e:
            import traceback
            logger.error("[learn_extractor] 初始化失败，知识抽取降级：%s\n%s", e, traceback.format_exc())
            _extractor = None
            _extractor_failed = True
        finally:
            try:
                os.chdir(old_cwd)
            except Exception:
                pass
        return _extractor


# ---------- 关系兜底：实体共现 ----------
def _cooccurrence_relations(text, entities, existing_pairs, max_rel=60):
    """
    当模型/规则抽到的关系过少时，用同句共现补充'关联'关系，
    保证图谱不至于只有孤立节点。existing_pairs 用于去重。
    """
    rels = []
    sentences = re.split(r'[。！？.!?\n]', text)
    for sent in sentences:
        in_sent = [e for e in entities if e and e in sent]
        for i in range(len(in_sent)):
            for j in range(i + 1, len(in_sent)):
                a, b = in_sent[i], in_sent[j]
                if a == b:
                    continue
                key = frozenset((a, b))
                if key in existing_pairs:
                    continue
                existing_pairs.add(key)
                rels.append((a, b))
                if len(rels) >= max_rel:
                    return rels
    return rels


def extract_triples(full_text: str, subject_name: str = "", confidence_threshold: float = 0.6) -> list:
    """
    主入口：从文本抽取知识三元组（供 pipeline 调用）。
    返回与现有 pipeline 兼容的三元组列表：
      {subject, sub_type, predicate, object, obj_type,
       subject_desc, object_desc, confidence("高"/"低")}
    抽取失败或无内容时返回 []，绝不抛异常。
    """
    if not full_text or not full_text.strip():
        return []

    ke = _get_extractor()
    if ke is None:
        return []

    backend_dir = _get_backend_dir()
    old_cwd = os.getcwd()
    try:
        if backend_dir:
            os.chdir(backend_dir)  # 抽取期间词典/模型相对路径仍需有效

        # 1) 知识点实体（带描述）
        entities, ents_with_content = ke.extract_knowledge_points(full_text, subject=subject_name)
        if not entities:
            logger.warning("[learn_extractor] 未抽取到实体")
            return []

        desc_map = {e['name']: e.get('description', '') for e in (ents_with_content or [])}

        # 2) 关系
        try:
            relations = ke.extract_relations(full_text, entities) or []
        except Exception as e:
            logger.warning("[learn_extractor] 关系抽取异常，降级为共现：%s", e)
            relations = []

        triples = []
        seen_pairs = set()
        for r in relations:
            s, o = r.get('source'), r.get('target')
            if not s or not o or s == o:
                continue
            key = frozenset((s, o))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            conf_val = r.get('confidence', 1.0)
            try:
                conf_high = float(conf_val) >= confidence_threshold
            except (TypeError, ValueError):
                conf_high = True
            triples.append({
                'subject': s, 'sub_type': '概念',
                'predicate': _map_relation(r.get('relation')),
                'object': o, 'obj_type': '概念',
                'subject_desc': desc_map.get(s, ''),
                'object_desc': desc_map.get(o, ''),
                'confidence': '高' if conf_high else '低',
            })

        # 3) 关系兜底（共现），保证有边
        if len(triples) < max(2, len(entities) // 4):
            for a, b in _cooccurrence_relations(full_text, entities, seen_pairs):
                triples.append({
                    'subject': a, 'sub_type': '概念', 'predicate': '关联',
                    'object': b, 'obj_type': '概念',
                    'subject_desc': desc_map.get(a, ''),
                    'object_desc': desc_map.get(b, ''),
                    'confidence': '低',  # 共现推断，置低待人工审核
                })

        logger.info("[learn_extractor] 抽取完成：实体 %s，关系三元组 %s", len(entities), len(triples))
        return triples

    except Exception as e:
        import traceback
        logger.error("[learn_extractor] 抽取失败：%s\n%s", e, traceback.format_exc())
        return []
    finally:
        try:
            os.chdir(old_cwd)
        except Exception:
            pass
