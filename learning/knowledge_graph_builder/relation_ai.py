"""使用大模型优化或检查课程知识点关系。"""

import json

from .triple_extractor import get_llm_client


VALID_RELATION_TYPES = {"前置", "隶属", "相似", "关联"}


def _call_relation_ai(subject_name, knowledge_points, relationships, mode):
    client = get_llm_client()
    if not client.api_key:
        raise RuntimeError("未配置大模型 API 密钥（DEEPSEEK_API_KEY）")

    graph_data = {
        "course": subject_name,
        "knowledge_points": knowledge_points,
        "existing_relationships": relationships,
    }

    rules = """
关系方向和类型必须严格遵守：
1. 前置：a -> b 表示先学 a，再学 b。
2. 隶属（即层级关系）：a -> b 表示 a 是粗粒度知识点，b 是 a 下更细粒度的知识点；例如 函数 -> 三角函数。
3. 相似：a 与 b 在概念或学习内容上相似。相似关系使用一个确定方向表示即可，不要同时输出 a->b 和 b->a。
4. 关联：存在明确联系，但不属于以上三种关系。
只能使用输入中已有的知识点 ID，不能创造新知识点，不能让节点指向自身。宁缺毋滥。
"""

    if mode == "optimize":
        task = """
请检查现有关系，并给出需要修改的现有关系及值得补充的缺失关系。
updates 中 relationship_id 必须来自 existing_relationships；可修正 source_id、target_id 或 relationship_type。
additions 只放当前不存在且确信合理的关系。不要删除关系，不要把无需修改的关系放入 updates。
输出 JSON：
{
  "summary": "简要说明",
  "updates": [{"relationship_id": 1, "source_id": 2, "target_id": 3, "relationship_type": "前置", "reason": "原因"}],
  "additions": [{"source_id": 2, "target_id": 4, "relationship_type": "隶属", "reason": "原因"}]
}
"""
    else:
        task = """
只检查现有关系合理性，绝对不要修改数据。检查关系类型和方向，并指出重要的缺失关系。
score 为 0 到 100 的整数。relationship_id 必须来自 existing_relationships。
输出 JSON：
{
  "overall": "总体评价",
  "score": 85,
  "issues": [{"relationship_id": 1, "severity": "高/中/低", "problem": "问题", "suggestion": "建议"}],
  "missing_relations": [{"source_id": 2, "target_id": 4, "relationship_type": "前置", "reason": "原因"}]
}
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": "你是严谨的课程知识图谱专家，只输出符合要求的 JSON。",
            },
            {
                "role": "user",
                "content": rules + task + "\n待分析数据：\n" + json.dumps(graph_data, ensure_ascii=False),
            },
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("大模型返回的数据格式无效")
    return result


def optimize_relations(subject_name, knowledge_points, relationships):
    return _call_relation_ai(subject_name, knowledge_points, relationships, "optimize")


def check_relations(subject_name, knowledge_points, relationships):
    return _call_relation_ai(subject_name, knowledge_points, relationships, "check")
