"""
别称映射表构建模块
调用LLM为抽取到的实体生成同义词、别称或英文缩写映射
"""
import json
import csv
import os
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


def get_llm_client():
    config = getattr(settings, 'LLM_CONFIG', {})
    api_key = os.environ.get('DEEPSEEK_API_KEY') or config.get('deepseek_api_key', '') or config.get('api_key', '')
    base_url = os.environ.get('DEEPSEEK_BASE_URL') or config.get('deepseek_base_url', 'https://api.deepseek.com')
    return OpenAI(api_key=api_key, base_url=base_url)


def build_alias_map(triples: list, output_path: str = None) -> dict:
    entities = set()
    for t in triples:
        entities.add(t["subject"])
        entities.add(t["object"])

    print(f"[INFO] 共提取 {len(entities)} 个唯一实体")
    if not entities:
        return {}

    if not get_llm_client().api_key:
        print("[WARN] 未配置LLM API密钥，跳过别名映射构建")
        return {}

    system_prompt = (
        "你是一位精通计算机科学领域的专家。请为以下专业术语提供其在中文教材、"
        "论文或教学中常见的同义词、别称或英文缩写。"
        '只返回JSON格式，结构为: {"aliases": {"术语1": ["别称1", "别称2", ...], ...}}'
    )

    try:
        response = get_llm_client().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"需要处理的术语列表: {list(entities)}"},
            ],
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content)
        alias_dict = raw.get("aliases", {})

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["canonical_name", "alias"])
                for canonical, aliases in alias_dict.items():
                    for alias in aliases:
                        if alias != canonical:
                            writer.writerow([canonical, alias])

        print(f"[INFO] 别名映射构建完成，共 {len(alias_dict)} 个实体有别名")
        return alias_dict

    except Exception as e:
        print(f"[ERROR] 构建别名映射失败: {e}")
        return {}
