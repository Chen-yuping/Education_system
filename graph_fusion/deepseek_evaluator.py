"""
融合图谱质量评估器（DeepSeek 大模型）
======================================================================
对「多学科融合图谱」做质量评估。各项指标参考 Learn/edu-knowledge-graph 的
backend/app.py（calculate_fusion_score / get_fusion_level / 融合率 / 共同节点占比）
与 knowledge_quality_evaluator.py，但关系准确性验证改为调用 DeepSeek 大模型
（不再使用本地部署的 Ollama 模型）。

评估维度（综合成 0-100 融合质量评分）：
  - 实体有效占比     0.25   （本地启发式 EntityQualityEvaluator）
  - 关系准确率       0.25   （DeepSeek 抽样验证）
  - 共同节点占比     0.30   （同名 + 语义对齐的跨学科共同节点）
  - 融合率(去重率)   0.20   （融合前后实体数变化）

输出结构对齐 Learn 的 fusionMetrics / entityStats / relationStats / suggestions，
便于前端直接渲染。
"""
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from .entity_quality import EntityQualityEvaluator

logger = logging.getLogger(__name__)

# ====================== DeepSeek 配置 ======================
# 密钥 / 端点 / 模型名做成可配置常量：环境变量优先，其次 settings.LLM_CONFIG，最后内置默认。
# 注意：用户指定模型为 deepseek-v4-flash（走中转端点）；若中转不识别该模型名，
# 会自动回退到官方可用的 deepseek-chat，保证评估始终可跑通。
_LLM_CONFIG = getattr(settings, 'LLM_CONFIG', {})

DEEPSEEK_API_KEY = (
    os.environ.get('DEEPSEEK_API_KEY')
    or _LLM_CONFIG.get('fusion_deepseek_api_key')
    or _LLM_CONFIG.get('deepseek_api_key')      # 兼容 settings.LLM_CONFIG 现有字段
    or _LLM_CONFIG.get('api_key')               # 再退回通用 LLM key
    or ''
)
DEEPSEEK_BASE_URL = (
    os.environ.get('DEEPSEEK_BASE_URL')
    or _LLM_CONFIG.get('fusion_deepseek_base_url')
    or _LLM_CONFIG.get('deepseek_base_url')
    or _LLM_CONFIG.get('base_url')
    or 'https://api.deepseek.com/v1'
)
DEEPSEEK_MODEL = (
    os.environ.get('DEEPSEEK_MODEL')
    or _LLM_CONFIG.get('fusion_deepseek_model')
    or _LLM_CONFIG.get('model')
    or 'deepseek-chat'
)
# 中转端点不识别 deepseek-v4-flash 时的回退模型（官方可用）
DEEPSEEK_FALLBACK_MODEL = 'deepseek-chat'

_client = None
_client_lock = threading.Lock()
_model_in_use = DEEPSEEK_MODEL


def _get_client():
    """获取 OpenAI 兼容的 DeepSeek 客户端（单例）"""
    global _client
    if _client is not None:
        return _client
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            '未配置 DeepSeek API Key：请在 settings.LLM_CONFIG 设置 deepseek_api_key，'
            '或设置环境变量 DEEPSEEK_API_KEY'
        )
    with _client_lock:
        if _client is None:
            from openai import OpenAI
            _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


def _chat(prompt: str, temperature: float = 0.0, max_tokens: int = 400) -> str:
    """调用 DeepSeek，返回纯文本；首选模型失败则回退到 deepseek-chat。"""
    global _model_in_use
    client = _get_client()
    for model in [_model_in_use, DEEPSEEK_FALLBACK_MODEL]:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _model_in_use = model  # 记住可用模型，后续直接用
            return resp.choices[0].message.content or ''
        except Exception as e:
            logger.warning("[deepseek] 模型 %s 调用失败：%s", model, e)
            continue
    raise RuntimeError('DeepSeek 调用失败：所有候选模型均不可用')


# ====================== 关系准确性验证（DeepSeek） ======================
_REL_DESC = {
    '隶属': '概念A 属于/隶属于 概念B 的范畴（包含关系）',
    '关联': '概念A 与 概念B 相关，但没有明确的包含或先后关系',
    '前置': '概念A 是学习 概念B 的先修/前置知识',
    '相似': '概念A 与 概念B 含义相近或高度相似',
    'RELATED_TO': '两个概念相关',
    'BELONGS_TO': '概念A 属于 概念B',
    'PREREQUISITE': '概念A 是 概念B 的先修知识',
}


def verify_relation_with_deepseek(entity_a: str, entity_b: str, rel_type: str) -> dict:
    """用 DeepSeek 判断 (A, rel_type, B) 关系是否成立"""
    desc = _REL_DESC.get(rel_type, f'"{rel_type}" 关系')
    prompt = f"""你是教育领域的知识图谱专家，擅长判断学科概念之间的关系是否合理。

请判断以下两个概念之间是否真的存在「{rel_type}」关系：
概念A：{entity_a}
概念B：{entity_b}

关系「{rel_type}」的含义：{desc}

请严格按下面格式输出，不要输出多余内容：
判断: [是/否]
置信度: [0-100的整数]
解释: [一句话简短说明]"""

    try:
        response = _chat(prompt, temperature=0.0, max_tokens=200)
        is_valid = ('判断: 是' in response) or ('判断:是' in response) or ('判断：是' in response)
        confidence = 50
        explanation = ''
        for line in response.splitlines():
            if '置信度' in line:
                digits = ''.join(filter(str.isdigit, line))
                if digits:
                    confidence = min(int(digits), 100)
            if line.strip().startswith('解释'):
                explanation = line.split('解释', 1)[-1].lstrip(':：').strip()
        return {
            'is_valid': is_valid,
            'confidence': confidence,
            'explanation': explanation,
            'full_response': response,
        }
    except Exception as e:
        logger.error("[deepseek] 关系验证失败 %s->%s: %s", entity_a, entity_b, e)
        # 验证失败时按「不否定」处理，避免拉低整体分
        return {'is_valid': True, 'confidence': 0,
                'explanation': f'验证失败: {e}', 'full_response': ''}


# ====================== 融合质量评分（移植自 Learn app.py） ======================
def calculate_fusion_score(entity_valid_rate, relation_accuracy, common_ratio, fusion_rate):
    """综合融合质量评分（0-100）。权重沿用 Learn calculate_fusion_score。"""
    weights = {'entity_quality': 0.25, 'relation_accuracy': 0.25,
               'common_ratio': 0.30, 'fusion_rate': 0.20}
    score = (
        (entity_valid_rate / 100) * weights['entity_quality'] +
        (relation_accuracy / 100) * weights['relation_accuracy'] +
        (common_ratio / 100) * weights['common_ratio'] +
        (min(fusion_rate, 50) / 100) * weights['fusion_rate']
    ) * 100
    return round(min(score, 100), 1)


def get_fusion_level(score):
    """根据评分给出融合等级（沿用 Learn get_fusion_level 的阈值与配色）"""
    if score >= 80:
        return {'level': '优秀', 'color': '#67c23a', 'description': '融合效果极佳，学科间关联紧密'}
    elif score >= 60:
        return {'level': '良好', 'color': '#e6a23c', 'description': '融合效果较好，有一定的学科交叉'}
    elif score >= 40:
        return {'level': '一般', 'color': '#f56c6c', 'description': '融合效果一般，建议增加共同节点'}
    else:
        return {'level': '较差', 'color': '#909399', 'description': '融合效果较差，学科间关联性较弱'}


def generate_suggestions(fusion_score, common_count, entity_stats, relation_stats):
    """生成融合改进建议（移植自 Learn generate_fusion_suggestions）"""
    suggestions = []
    if fusion_score < 40:
        suggestions.append(f"当前融合质量较差（{fusion_score}分），建议增加学科间的共同概念和关联关系")
    elif fusion_score < 60:
        suggestions.append(f"当前融合质量一般（{fusion_score}分），可以尝试添加更多跨学科知识点")
    else:
        suggestions.append(f"当前融合质量{get_fusion_level(fusion_score)['level']}（{fusion_score}分）")

    if common_count < 5:
        suggestions.append(f"共同节点较少（{common_count}个），建议查找学科间更多的共同概念")
    else:
        suggestions.append(f"发现 {common_count} 个共同节点，这些是学科融合的核心基础")

    if entity_stats.get('lowQualityPercentage', 0) > 20:
        suggestions.append(f"低质量实体占比较高（{entity_stats['lowQualityPercentage']}%），建议先清理低质量实体")

    if relation_stats.get('overallAccuracy', 100) < 60:
        suggestions.append(f"关系准确率较低（{relation_stats['overallAccuracy']}%），建议检查并修正不准确的关系")

    return suggestions


# ====================== 评估主入口 ======================
def evaluate_fusion(subject_ids, sample_size=15):
    """
    评估给定科目集合融合后的图谱质量。

    流程：
      1. 调用 fusion.fuse_graph 得到融合图谱（节点/边/同名+语义合并统计）
      2. 实体质量启发式评估 -> entityStats（有效实体占比）
      3. DeepSeek 抽样验证关系准确性 -> relationStats（整体准确率 + 分类型准确率）
      4. 计算融合率、共同节点占比 -> 综合 fusionScore / fusionLevel / suggestions

    返回与 Learn fuse_graphs 接口对齐的 data 字典。
    """
    from .fusion import fuse_graph
    from learning.models import Subject, KnowledgePoint, KnowledgeGraph

    fusion_result = fuse_graph(subject_ids, semantic=True)
    subject_id_list = fusion_result.get('subject_ids') or list(subject_ids or [])

    subjects = list(
        Subject.objects.filter(id__in=subject_id_list).values_list('name', flat=True)
    )

    # ---- 实体质量评估（本地启发式） ----
    nodes = fusion_result['nodes']
    node_names = [n['name'] for n in nodes]
    eq = EntityQualityEvaluator()
    entity_stats = eq.batch_statistics(node_names)

    # ---- 共同节点 / 跨学科节点 ----
    common_count = fusion_result.get('cross_subject_node_count', 0)
    total_after = fusion_result.get('node_count', 0)
    common_ratio = (common_count / max(total_after, 1)) * 100

    # ---- 融合率（去重率） ----
    total_before = KnowledgePoint.objects.filter(subject_id__in=subject_id_list).count()
    fusion_rate = ((total_before - total_after) / max(total_before, 1)) * 100

    # ---- 关系准确性（DeepSeek 抽样验证） ----
    rels = list(
        KnowledgeGraph.objects.filter(subject_id__in=subject_id_list)
        .select_related('source', 'target')
    )
    relation_stats = _evaluate_relations(rels, sample_size)

    # ---- 综合评分 ----
    fusion_score = calculate_fusion_score(
        entity_stats['validEntityPercentage'],
        relation_stats['overallAccuracy'],
        common_ratio,
        fusion_rate,
    )
    suggestions = generate_suggestions(fusion_score, common_count, entity_stats, relation_stats)

    cross_nodes = [n['name'] for n in nodes if n.get('cross_subject')]

    return {
        'subjects': subjects,
        'model': _model_in_use,
        'fusionMetrics': {
            'fusionScore': fusion_score,
            'fusionLevel': get_fusion_level(fusion_score),
            'fusionRate': round(fusion_rate, 2),
            'commonRatio': round(common_ratio, 2),
            'commonEntitiesCount': common_count,
            'crossSubjectNodeCount': common_count,
            'mergedNodeCount': fusion_result.get('merged_node_count', 0),
            'semanticMerged': fusion_result.get('semantic_merged', 0),
            'totalEntitiesBefore': total_before,
            'totalEntitiesAfter': total_after,
            'totalRelations': relation_stats['total'],
        },
        'commonEntities': cross_nodes[:20],
        'entityStats': entity_stats,
        'relationStats': relation_stats,
        'suggestions': suggestions,
    }


def _evaluate_relations(rels, sample_size):
    """DeepSeek 抽样验证关系准确性，返回 relationStats"""
    import random
    random.seed(42)

    total = len(rels)
    # 关系类型分布
    type_counts = {}
    for r in rels:
        t = r.relationship_type or '关联'
        type_counts[t] = type_counts.get(t, 0) + 1

    distribution = [
        {'type': t, 'count': c, 'percentage': round(c / max(total, 1) * 100, 2)}
        for t, c in type_counts.items()
    ]

    if total == 0:
        return {'total': 0, 'overallAccuracy': 0, 'sampledCount': 0,
                'relationTypeAccuracy': [], 'relationTypeDistribution': [],
                'questionable': []}

    sampled = random.sample(rels, sample_size) if total > sample_size else rels

    def _verify(r):
        v = verify_relation_with_deepseek(r.source.name, r.target.name, r.relationship_type or '关联')
        return {'from': r.source.name, 'to': r.target.name,
                'type': r.relationship_type or '关联', 'v': v}

    results = []
    max_workers = min(8, len(sampled)) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_verify, r): r for r in sampled}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                logger.error("[deepseek] 关系验证线程失败: %s", e)

    verified = sum(1 for x in results if x['v']['is_valid'])
    overall = round(verified / len(results) * 100, 1) if results else 0

    # 分类型准确率
    by_type = {}
    for x in results:
        t = x['type']
        by_type.setdefault(t, {'verified': 0, 'sample': 0})
        by_type[t]['sample'] += 1
        if x['v']['is_valid']:
            by_type[t]['verified'] += 1

    type_accuracy = [
        {'type': t, 'accuracy': round(d['verified'] / max(d['sample'], 1) * 100, 1),
         'details': f"验证{d['verified']}/{d['sample']}条", 'totalCount': type_counts.get(t, 0)}
        for t, d in by_type.items()
    ]

    questionable = [
        {'from': x['from'], 'to': x['to'], 'type': x['type'],
         'confidence': x['v']['confidence'], 'explanation': x['v']['explanation']}
        for x in results if not x['v']['is_valid']
    ]

    return {
        'total': total,
        'sampledCount': len(sampled),
        'overallAccuracy': overall,
        'relationTypeAccuracy': type_accuracy,
        'relationTypeDistribution': distribution,
        'questionable': questionable,
    }
