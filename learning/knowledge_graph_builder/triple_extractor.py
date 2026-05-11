"""
知识三元组抽取模块
使用LLM（DeepSeek）对教材文本进行知识抽取，生成结构化的三元组数据
"""
import json
import csv
import os
import time
import sys
import io

_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout

from openai import OpenAI
from django.conf import settings

# 知识三元组CSV字段
TRIPLE_HEADERS = [
    "subject", "sub_type", "predicate", "object",
    "obj_type", "subject_desc", "object_desc",
]

BATCH_SIZE = 200


def get_llm_client():
    config = getattr(settings, 'LLM_CONFIG', {})
    api_key = os.environ.get('DEEPSEEK_API_KEY') or config.get('deepseek_api_key', '') or config.get('api_key', '')
    base_url = os.environ.get('DEEPSEEK_BASE_URL') or config.get('deepseek_base_url', 'https://api.deepseek.com')
    return OpenAI(api_key=api_key, base_url=base_url)


def extract_triples_from_text(full_text: str, subject_name: str = "") -> list:
    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
    client = get_llm_client()

    if not client.api_key:
        print("[WARN] 未配置LLM API密钥，跳过知识抽取")
        return []

    scope_keywords = _identify_scope(lines, client)

    all_results = []
    total = len(lines)

    for i in range(0, total, BATCH_SIZE):
        batch = lines[i:i + BATCH_SIZE]
        current_range = f"{i + 1}-{min(i + BATCH_SIZE, total)}"
        print(f"  正在处理第 {current_range} / {total} 段...", end=" ", flush=True)

        start = time.time()
        results = _extract_batch("\n".join(batch), scope_keywords, subject_name, client)

        if results:
            all_results.extend(results)
            cost = time.time() - start
            print(f"[OK] 成功 (获取 {len(results)} 条, 耗时 {cost:.1f}s)")
        else:
            print(f"[WARN] 未抽取到内容")

        if i + BATCH_SIZE < total:
            time.sleep(0.5)

    print(f"\n[INFO] 共抽取 {len(all_results)} 条知识三元组")
    return all_results


def _identify_scope(lines, client) -> set:
    text_sample = "\n".join(lines[:20])[:1000]

    prompt = f"""
    请分析以下教材文本片段，严格按以下步骤执行：
    1. 识别章节：阅读文本，找出本章节的标题（通常在最开始）。
    2. 提取核心概念：提取出本章节最核心的 5~10 个专有名词或概念（必须是本章独有的）。
    3. 输出JSON：{{"chapter_title": "...", "core_concepts": ["概念1", "概念2", ...]}}

    文本片段：
    {text_sample}
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        title = result.get("chapter_title", "")
        concepts = result.get("core_concepts", [])
        print(f"[INFO] 识别到章节: {title}")
        print(f"[INFO] 核心词: {', '.join(concepts)}")
        return set(
            [title.lower()] + [c.lower() for c in concepts]
        )
    except Exception as e:
        print(f"[WARN] 章节识别失败: {e}")
        return set()


def _extract_batch(text_batch, scope_keywords, subject_name, client) -> list:
    system_prompt = "你是一个严谨的在线教育知识图谱专家。请严格按JSON格式抽取五元组。"

    user_prompt = f"""
    ### 任务指令
    请从以下教材文本中抽取知识图谱三元组。课程名称：{subject_name or '未知'}

    ### 核心约束
    1. 章节聚焦：仅抽取与当前章节核心概念高度相关的实体。
    2. 忠实原文：严禁编造原文中不存在的通用常识。
    3. 关系类型：知识点之间的关系为：隶属、关联、前置、相似，根据上下文准确判断。

    ### 输出格式
    {{"data": [["头实体", "头类型", "关系", "尾实体", "尾类型", "头实体描述", "尾实体描述"], ...]}}

    ### 待处理文本
    {text_batch}
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw_data = json.loads(response.choices[0].message.content)
        items = raw_data.get("data", [])

        results = []
        for item in items:
            if isinstance(item, list) and len(item) >= 5:
                results.append({
                    "subject": item[0].strip(),
                    "sub_type": item[1].strip() if len(item) > 1 else "概念",
                    "predicate": item[2].strip() if len(item) > 2 else "关联",
                    "object": item[3].strip(),
                    "obj_type": item[4].strip() if len(item) > 4 else "概念",
                    "subject_desc": item[5].strip() if len(item) > 5 and item[5] else "",
                    "object_desc": item[6].strip() if len(item) > 6 and item[6] else "",
                })
        return results
    except Exception as e:
        print(f"[ERROR] 抽取错误: {e}")
        return []


def save_triples_to_csv(triples: list, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=TRIPLE_HEADERS)
        writer.writeheader()
        writer.writerows(triples)

    print(f"[INFO] 三元组已保存至: {output_path}")
