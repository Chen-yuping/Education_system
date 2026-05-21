"""
实体名称标准化模块
使用别名映射表对抽取结果中的实体名称进行标准化
"""
import csv
import sys
import io

_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout


def load_alias_map(alias_dict: dict = None, csv_path: str = None) -> dict:
    alias_to_canonical = {}

    if alias_dict:
        for canonical, aliases in alias_dict.items():
            alias_to_canonical[canonical] = canonical
            for alias in aliases:
                alias_to_canonical[alias] = canonical

    if csv_path:
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    canonical = row["canonical_name"]
                    alias = row["alias"]
                    alias_to_canonical[alias] = canonical
                    alias_to_canonical[canonical] = canonical
        except FileNotFoundError:
            print(f"[WARN] 映射表文件 {csv_path} 未找到")

    print(f"[INFO] 加载 {len(alias_to_canonical)} 条别名映射规则")
    return alias_to_canonical


def standardize_triples(triples: list, alias_map: dict) -> list:
    standardized = []
    count = 0

    for t in triples:
        new_t = dict(t)
        orig_subj = t["subject"]
        orig_obj = t["object"]

        new_t["subject"] = alias_map.get(orig_subj, orig_subj)
        new_t["object"] = alias_map.get(orig_obj, orig_obj)

        if new_t["subject"] != orig_subj or new_t["object"] != orig_obj:
            count += 1

        standardized.append(new_t)

    if count > 0:
        print(f"[INFO] 标准化了 {count} 条三元组中的实体名称")
    return standardized
