"""
知识图谱构建管线（Pipeline）
将PDF课本 -> 文本提取 -> LLM三元组抽取 -> 别名映射 -> 实体标准化 -> 存储的完整流程
"""
import os
import sys
import io
import tempfile
from pathlib import Path

_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout

from .pdf_extractor import extract_text_from_pdf
from .triple_extractor import extract_triples_from_text, save_triples_to_csv
from .alias_builder import build_alias_map
from .entity_standardizer import load_alias_map, standardize_triples
from .graph_storage import save_to_django, save_to_neo4j


class KnowledgeGraphPipeline:
    """知识图谱构建管线"""

    def __init__(self, textbook_builder=None, output_dir=None):
        self.builder = textbook_builder
        self.output_dir = output_dir

    def run(self, pdf_path: str = "", subject=None, subject_name: str = "",
            text: str = "", source: str = '教材', resource_file=None) -> dict:
        result = {"success": False, "kp_count": 0, "rel_count": 0, "error": ""}

        try:
            # ===== Step 1: 文本提取（从PDF或直接传入） =====
            if text:
                full_text = text
                print(f"[INFO] 使用传入文本，长度: {len(full_text)} 字符")
            elif pdf_path:
                print("\n" + "=" * 50)
                print("Step 1/5: PDF文本提取")
                print("=" * 50)
                self._update_status('extracting_text')
                full_text = extract_text_from_pdf(pdf_path)
                print(f"[INFO] 提取文本长度: {len(full_text)} 字符")
            else:
                raise ValueError("必须提供 pdf_path 或 text 参数")

            if not full_text.strip():
                raise ValueError("PDF文本提取失败，未能获取到任何文字内容")

            if self.builder:
                self.builder.extracted_text = full_text[:10000]

            # ===== Step 2: LLM三元组抽取 =====
            print("\n" + "=" * 50)
            print("Step 2/5: 知识三元组抽取")
            print("=" * 50)
            self._update_status('extracting_knowledge')

            triples = extract_triples_from_text(full_text, subject_name)
            if not triples:
                print("[WARN] 未抽取到有效三元组，跳过后续步骤")
                result["success"] = True
                return result

            # ===== Step 3: 构建别名映射 =====
            print("\n" + "=" * 50)
            print("Step 3/5: 构建别名映射")
            print("=" * 50)
            self._update_status('analyzing_content')

            alias_path = self._get_output_path("别名库.csv") if self.output_dir else None
            alias_dict = build_alias_map(triples, output_path=alias_path)

            # ===== Step 4: 实体名称标准化 =====
            print("\n" + "=" * 50)
            print("Step 4/5: 实体名称标准化")
            print("=" * 50)

            alias_map = load_alias_map(alias_dict)
            triples = standardize_triples(triples, alias_map)

            csv_path = self._get_output_path("知识抽取结果.csv") if self.output_dir else None
            if csv_path:
                os.makedirs(os.path.dirname(csv_path), exist_ok=True)
                save_triples_to_csv(triples, csv_path)

            # ===== Step 5: 存储到Django模型和Neo4j =====
            print("\n" + "=" * 50)
            print("Step 5/5: 存储知识图谱")
            print("=" * 50)
            self._update_status('building_graph')

            storage_result = save_to_django(triples, subject, relation_source=source, resource_file=resource_file)

            # Neo4j存储已弃用，图谱数据直接由MySQL提供

            print("\n" + "=" * 50)
            print("知识图谱构建完成！")
            print(f"知识点: {storage_result['kp_count']} 个")
            print(f"关系: {storage_result['rel_count']} 条")
            print("=" * 50)

            result["success"] = True
            result["kp_count"] = storage_result["kp_count"]
            result["rel_count"] = storage_result["rel_count"]
            result["entity_map"] = storage_result.get("entity_map", {})
            result["created_kps"] = storage_result.get("created_kps", [])
            result["created_rels"] = storage_result.get("created_rels", [])

        except Exception as e:
            import traceback
            error_msg = f"{e}\n{traceback.format_exc()}"
            print(f"[ERROR] 管线执行失败: {error_msg}")
            result["success"] = False
            result["error"] = str(e)

        return result

    def _update_status(self, status):
        if self.builder:
            try:
                self.builder.status = status
                self.builder.save(update_fields=['status'])
            except Exception:
                pass

    def _get_output_path(self, filename):
        if self.output_dir:
            return str(Path(self.output_dir) / filename)
        return None
