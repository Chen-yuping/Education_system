import hashlib
import importlib.util
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
from django.db import transaction
from django.utils import timezone

from learning.models import (
    AnswerLog,
    DiagnosisModel,
    Exercise,
    KnowledgeGraph,
    KnowledgePoint,
    QMatrix,
    StudentDiagnosis,
    Subject,
    User,
)

# 对外暴露给页面/数据库使用的 CDF 模型名。
# 这里统一成新命名，后续所有训练和推理入口都先经过这层校验。
CDF_MODEL_NAMES = {"IdpCDF", "HierCDF", "ConCDF", "PCG-CDF"}
DIAGNOSIS_ROOT = Path(__file__).resolve().parent
CMD_SURVEY_DATA_ROOT = DIAGNOSIS_ROOT / "CMD_survey" / "data"
GRAPH_CACHE_ROOT = DIAGNOSIS_ROOT / "corseinfo"
CHECKPOINT_ROOT = DIAGNOSIS_ROOT / "checkpoints"
LOG_ROOT = DIAGNOSIS_ROOT / "cdflogs"
_CMD_SURVEY_MODULE_CACHE: Dict[str, Any] = {}


# 统一校验并规范化 CDF 模型名，避免后续分支重复判断。
def normalize_cdf_model_name(model_name: str) -> str:
    # 先把外部传入的模型名规范化，避免后面分支里到处写重复判断。
    normalized = (model_name or "").strip()
    if normalized not in CDF_MODEL_NAMES:
        raise ValueError(f"Unsupported CDF model: {model_name}")
    return normalized


# 判断当前模型是否属于 CDF 桥接链路，便于训练/推理分流。
def is_cdf_model(model_name: str) -> bool:
    # 用于快速判断某个模型是否属于 CDF 桥接链路。
    return (model_name or "").strip() in CDF_MODEL_NAMES


# 生成 CDF 训练时使用的数据集标识，优先使用课程自己的 dataset。
def _cdf_dataset_name(subject_id: int, model_name: str) -> str:
    # 生成 CDF 训练时使用的数据集标识，优先使用课程自身配置的 dataset。
    subject = Subject.objects.filter(id=subject_id).only("dataset", "name").first()
    if subject and subject.dataset:
        return subject.dataset.strip()
    return f"subject_{subject_id}_{model_name}"


# 拼接学生展示名，优先真实姓名，没有就回退到用户名。
def _student_display_name(student: User) -> str:
    # 拼接学生展示名，优先使用真实姓名，没有就回退到用户名。
    full_name = f"{student.first_name or ''}{student.last_name or ''}".strip()
    return full_name or student.username


# 安全转换为浮点数，避免 NaN/inf 影响后续计算。
def _safe_float(value: Any, default: float = 0.0) -> float:
    # 把外部输入安全转成浮点数，避免 NaN/inf 影响后续计算。
    try:
        result = float(value)
    except Exception:
        return default
    if np.isnan(result) or np.isinf(result):
        return default
    return result


# 安全转换为整数，失败时回退到默认值。
def _safe_int(value: Any, default: int = 0) -> int:
    # 把外部输入安全转成整数，失败时回退到默认值。
    try:
        return int(value)
    except Exception:
        return default


# 汇总课程的习题、知识点、Q 矩阵和答题日志，拼成 CDF 可直接训练的数据包。
def build_cdf_diagnosis_data(subject_id: int) -> Dict[str, Any]:
    # 把课程中的习题、知识点、Q 矩阵和答题日志整理成 CDF 可直接使用的数据包。
    exercises = list(
        Exercise.objects.filter(subject_id=subject_id).only("id").order_by("id")
    )
    knowledge_points = list(
        KnowledgePoint.objects.filter(subject_id=subject_id).only("id", "name", "subject_id").order_by("id")
    )

    if not exercises:
        return {"error": f"Subject {subject_id} has no exercises"}
    if not knowledge_points:
        return {"error": f"Subject {subject_id} has no knowledge points"}

    exercise_id_map = {exercise.id: idx for idx, exercise in enumerate(exercises)}
    kp_id_map = {kp.id: idx for idx, kp in enumerate(knowledge_points)}

    q_matrix = np.zeros((len(exercises), len(knowledge_points)), dtype=np.float32)
    q_rows = QMatrix.objects.filter(exercise__subject_id=subject_id).values_list(
        "exercise_id", "knowledge_point_id", "weight"
    )
    for exercise_id, kp_id, weight in q_rows:
        exercise_idx = exercise_id_map.get(exercise_id)
        kp_idx = kp_id_map.get(kp_id)
        if exercise_idx is None or kp_idx is None:
            continue
        q_matrix[exercise_idx, kp_idx] = float(weight or 1.0)

    answer_logs = list(
        AnswerLog.objects.filter(
            exercise__subject_id=subject_id,
            is_correct__isnull=False,
        )
        .select_related("student", "exercise")
        .order_by("student_id", "submitted_at", "id")
    )
    if not answer_logs:
        return {"error": f"Subject {subject_id} has no answer logs"}

    student_ids = sorted({log.student_id for log in answer_logs})
    students = {
        student.id: student
        for student in User.objects.filter(id__in=student_ids, user_type="student").only(
            "id", "username", "first_name", "last_name"
        )
    }

    students_data: Dict[int, Dict[str, Any]] = {}
    for student_id in student_ids:
        student = students.get(student_id)
        if not student:
            continue
        students_data[student_id] = {
            "id": student_id,
            "username": student.username,
            "first_name": _student_display_name(student),
            "answer_logs": [],
            "exercise_scores": {},
        }

    for log in answer_logs:
        if log.student_id not in students_data:
            continue
        exercise_idx = exercise_id_map.get(log.exercise_id)
        if exercise_idx is None:
            continue
        students_data[log.student_id]["answer_logs"].append(
            {
                "exercise_id": log.exercise_id,
                "exercise_idx": exercise_idx,
                "is_correct": bool(log.is_correct),
                "time_spent": log.time_spent,
            }
        )
        students_data[log.student_id]["exercise_scores"][log.exercise_id] = bool(log.is_correct)

    return {
        "subject_id": subject_id,
        "students": students_data,
        "exercises": exercises,
        "knowledge_points": knowledge_points,
        "Q_matrix": q_matrix,
        "exercise_id_map": exercise_id_map,
        "kp_id_map": kp_id_map,
    }


# 根据关系类型返回对应缓存文件、提示词和版本号配置。
def _graph_kind_config(relation_kind: str) -> Dict[str, str]:
    # 根据关系类型返回对应的图谱文件名、提示词规则和缓存版本号。
    kind = (relation_kind or "prereq").lower()
    if kind in {"containment", "contain", "con"}:
        return {
            "kind": "containment",
            "edge_file": "knowledge_edges_ids.csv",
            "cycle_file": "removed_cycles_containment.csv",
            "graph_alias": "knowledge_graphs_containment.csv",
            "prompt_name": "containment graph",
            "prompt_rule": "source is the contained child concept and target is the containing parent concept",
            "graph_version": "containment_child_to_parent_v3",
        }
    return {
        "kind": "prereq",
        "edge_file": "knowledge_graphs_prereq.csv",
        "cycle_file": "removed_cycles_prereq.csv",
        "graph_alias": "knowledge_graphs_prereq.csv",
        "prompt_name": "prerequisite graph",
        "prompt_rule": "source is the prerequisite concept and target is the dependent concept",
        "graph_version": "prereq_v1",
    }


# 获取课程知识图谱缓存目录。
def _graph_base_dir(subject_id: int) -> Path:
    # 所有课程图谱缓存都统一放在这个目录下。
    return GRAPH_CACHE_ROOT / f"subject_{subject_id}"


# 把知识点转成图节点表，并建立 id/name 到节点编号的映射。
def _build_node_rows(knowledge_points: List[KnowledgePoint]) -> Tuple[List[Dict[str, Any]], Dict[int, int], Dict[str, int]]:
    # 把知识点转换成图节点表，同时建立 id/name 到节点编号的映射。
    node_rows: List[Dict[str, Any]] = []
    kp_id_to_node_id: Dict[int, int] = {}
    kp_name_to_id: Dict[str, int] = {}

    for node_id, kp in enumerate(sorted(knowledge_points, key=lambda item: item.id)):
        kp_id_to_node_id[kp.id] = node_id
        kp_name_to_id[kp.name.strip()] = kp.id
        node_rows.append(
            {
                "node_id": node_id,
                "knowledge_point_id": kp.id,
                "knowledge_point_name": kp.name,
                "subject_id": kp.subject_id,
            }
        )
    return node_rows, kp_id_to_node_id, kp_name_to_id


# 对当前知识点集合做快照哈希，用来判断缓存图谱是否可复用。
def _snapshot_hash(knowledge_points: List[KnowledgePoint], relation_kind: str = "prereq") -> str:
    # 对当前知识点集合做快照哈希，用于判断缓存图谱是否还能复用。
    import hashlib

    version = _graph_kind_config(relation_kind).get("graph_version", relation_kind)
    payload = "||".join(f"{kp.id}:{kp.name}" for kp in sorted(knowledge_points, key=lambda item: item.id))
    payload = f"{version}||{payload}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# 统一写出 CSV 文件，保持编码和列顺序一致。
def _write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    # 统一写 CSV，避免各处重复处理编码和列顺序。
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


# 读取 CSV 缓存，文件不存在时返回空列表。
def _read_csv(path: Path) -> List[Dict[str, Any]]:
    # 读取 CSV 缓存，找不到文件时直接返回空列表。
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict("records")


# 从大模型返回文本中剥离 JSON 主体，兼容代码块和夹杂说明的输出。
def _extract_json_payload(raw_text: str) -> Any:
    text = (raw_text or "").strip().replace("```json", "").replace("```", "").strip()
    if not text:
        return []

    start_array = text.find("[")
    end_array = text.rfind("]")
    if start_array != -1 and end_array != -1 and end_array > start_array:
        text = text[start_array : end_array + 1]
    else:
        start_obj = text.find("{")
        end_obj = text.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            text = text[start_obj : end_obj + 1]

    return json.loads(text)


# 统一调用大模型接口，当前用于生成知识图谱关系候选。
def _call_llm(prompt: str) -> Any:
    try:
        import dashscope
        from dashscope import Generation

        api_key = getattr(dashscope, "api_key", None)
        if not api_key:
            try:
                from learning import utils_ai  # noqa: F401
                api_key = getattr(dashscope, "api_key", None)
            except Exception:
                api_key = None

        if not api_key:
            return None

        return Generation.call(model="qwen-turbo", prompt=prompt, result_format="message")
    except Exception as exc:
        print(f"LLM call failed: {exc}")
        return None


# 根据关系类型拼接提示词，明确告诉大模型要生成哪种知识关系。
def _build_relation_prompt(knowledge_points: List[KnowledgePoint], relation_kind: str) -> str:
    config = _graph_kind_config(relation_kind)
    kp_lines = "\n".join(
        f"- kp_id={kp.id}, name={kp.name}" for kp in sorted(knowledge_points, key=lambda item: item.id)
    )
    return f"""
You are helping to build a {config['prompt_name']} for an education system.
Rules:
1. Only use the knowledge points listed below.
2. Output a pure JSON array, no markdown, no extra explanation.
3. Each item must include source_kp_id, target_kp_id, score, reason.
4. Each edge must follow this rule: {config['prompt_rule']}.
5. Keep the graph sparse and meaningful.

Knowledge points:
{kp_lines}

Return format example:
[
  {{
    "source_kp_id": 1,
    "target_kp_id": 2,
    "score": 0.92,
    "reason": "..."
  }}
]
""".strip()


# 将大模型返回的一条关系记录标准化成系统内部结构。
def _normalize_relation_item(
    item: Dict[str, Any],
    kp_id_to_node_id: Dict[int, int],
    kp_name_to_id: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    def _pick_int(*keys: str) -> Optional[int]:
        for key in keys:
            value = item.get(key)
            if value is None or value == "":
                continue
            try:
                return int(value)
            except Exception:
                continue
        return None

    def _pick_name(*keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value:
                return str(value).strip()
        return ""

    source_kp_id = _pick_int("source_kp_id", "source_id", "source", "from_kp_id", "from")
    target_kp_id = _pick_int("target_kp_id", "target_id", "target", "to_kp_id", "to")

    if source_kp_id is None:
        source_kp_id = kp_name_to_id.get(_pick_name("source_name", "from_name", "source_label", "from_label"))
    if target_kp_id is None:
        target_kp_id = kp_name_to_id.get(_pick_name("target_name", "to_name", "target_label", "to_label"))

    if source_kp_id is None or target_kp_id is None or source_kp_id == target_kp_id:
        return None

    score = _safe_float(item.get("score", item.get("confidence", 0.5)), default=0.5)
    return {
        "source_kp_id": source_kp_id,
        "target_kp_id": target_kp_id,
        "source_node_id": kp_id_to_node_id.get(source_kp_id),
        "target_node_id": kp_id_to_node_id.get(target_kp_id),
        "source_name": _pick_name("source_name", "from_name", "source_label", "from_label"),
        "target_name": _pick_name("target_name", "to_name", "target_label", "to_label"),
        "score": round(score, 4),
        "reason": str(item.get("reason", "")).strip(),
    }


# 调用大模型抽取候选关系，并完成去重和基础清洗。
def _generate_relation_candidates(
    knowledge_points: List[KnowledgePoint],
    relation_kind: str,
    kp_id_to_node_id: Dict[int, int],
    kp_name_to_id: Dict[str, int],
) -> List[Dict[str, Any]]:
    response = _call_llm(_build_relation_prompt(knowledge_points, relation_kind))
    if not response or getattr(response, "status_code", None) != 200:
        return []

    try:
        content = response.output.choices[0].message.content
        payload = _extract_json_payload(content)
    except Exception as exc:
        print(f"LLM graph parsing failed: {exc}")
        return []

    if isinstance(payload, dict):
        payload = payload.get("relations") or payload.get("edges") or []
    if not isinstance(payload, list):
        return []

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        relation = _normalize_relation_item(item, kp_id_to_node_id, kp_name_to_id)
        if not relation:
            continue
        key = (relation["source_kp_id"], relation["target_kp_id"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(relation)
    return normalized


# 当大模型没有返回结果时，退回使用数据库中已有的知识关系。
def _db_knowledge_relations(knowledge_points: List[KnowledgePoint], relation_kind: str) -> List[Dict[str, Any]]:
    relations: List[Dict[str, Any]] = []
    kp_id_set = {kp.id for kp in knowledge_points}
    if not kp_id_set:
        return relations

    subject_id = knowledge_points[0].subject_id
    db_relations = KnowledgeGraph.objects.filter(
        subject_id=subject_id,
        source_id__in=kp_id_set,
        target_id__in=kp_id_set,
    ).values_list("source_id", "target_id")

    if relation_kind == "containment":
        seen = set()
        for source_id, target_id in db_relations:
            key = (target_id, source_id)
            if source_id == target_id or key in seen:
                continue
            seen.add(key)
            relations.append(
                {
                    "source": target_id,
                    "target": source_id,
                    "score": 0.5,
                    "reason": "fallback child_to_parent",
                }
            )
        return relations

    seen = set()
    for source_id, target_id in db_relations:
        key = (source_id, target_id)
        if source_id == target_id or key in seen:
            continue
        seen.add(key)
        relations.append(
            {
                "source": source_id,
                "target": target_id,
                "score": 0.5,
                "reason": "fallback db relation",
            }
        )

    if relations:
        return relations

    parent_relations = KnowledgePoint.objects.filter(
        subject_id=subject_id,
        id__in=kp_id_set,
        parent_id__isnull=False,
    ).values_list("parent_id", "id")

    seen = set()
    for parent_id, child_id in parent_relations:
        if relation_kind == "containment":
            key = (child_id, parent_id)
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                {
                    "source": child_id,
                    "target": parent_id,
                    "score": 0.5,
                    "reason": "fallback parent relation",
                }
            )
        else:
            key = (parent_id, child_id)
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                {
                    "source": parent_id,
                    "target": child_id,
                    "score": 0.5,
                    "reason": "fallback parent relation",
                }
            )

    return relations


# 去掉关系图中的环，保证最终图结构可用于层次诊断。
def _remove_cycles(
    relations: List[Dict[str, Any]],
    relation_kind: str,
    kp_id_to_node_id: Dict[int, int],
    knowledge_points: List[KnowledgePoint],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    import networkx as nx

    kp_map = {kp.id: kp for kp in knowledge_points}
    graph = nx.DiGraph()
    edge_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}

    for relation in relations:
        source = _safe_int(relation.get("source"), default=-1)
        target = _safe_int(relation.get("target"), default=-1)
        if source == target or source < 0 or target < 0:
            continue
        key = (source, target)
        if key in edge_meta:
            if _safe_float(relation.get("score"), default=0.0) > _safe_float(edge_meta[key].get("score"), default=0.0):
                edge_meta[key] = relation
            continue
        edge_meta[key] = relation
        graph.add_edge(source, target)

    graph.add_nodes_from(kp_map.keys())
    removed_cycles: List[Dict[str, Any]] = []

    while True:
        try:
            cycle = next(nx.simple_cycles(graph))
        except StopIteration:
            break
        if len(cycle) < 2:
            break

        cycle_edges = list(zip(cycle, cycle[1:] + [cycle[0]]))

        def _edge_score(edge: Tuple[int, int]) -> Tuple[float, int, int]:
            meta = edge_meta.get(edge, {})
            return _safe_float(meta.get("score"), default=0.0), edge[0], edge[1]

        edge_to_remove = min(cycle_edges, key=_edge_score)
        removed_meta = edge_meta.pop(edge_to_remove, {})
        if graph.has_edge(*edge_to_remove):
            graph.remove_edge(*edge_to_remove)

        source_kp = kp_map.get(edge_to_remove[0])
        target_kp = kp_map.get(edge_to_remove[1])
        removed_cycles.append(
            {
                "relation_kind": relation_kind,
                "cycle_nodes": json.dumps(cycle, ensure_ascii=False),
                "removed_source_kp_id": edge_to_remove[0],
                "removed_target_kp_id": edge_to_remove[1],
                "removed_source_node_id": kp_id_to_node_id.get(edge_to_remove[0]),
                "removed_target_node_id": kp_id_to_node_id.get(edge_to_remove[1]),
                "removed_source_name": source_kp.name if source_kp else "",
                "removed_target_name": target_kp.name if target_kp else "",
                "score": removed_meta.get("score", 0.0),
                "reason": removed_meta.get("reason", ""),
            }
        )

    acyclic_relations: List[Dict[str, Any]] = []
    for source, target in graph.edges():
        meta = edge_meta.get((source, target), {})
        source_kp = kp_map.get(source)
        target_kp = kp_map.get(target)
        acyclic_relations.append(
            {
                "source": source,
                "target": target,
                "source_node_id": kp_id_to_node_id.get(source),
                "target_node_id": kp_id_to_node_id.get(target),
                "score": meta.get("score", 0.5),
                "reason": meta.get("reason", ""),
                "source_name": meta.get("source_name", source_kp.name if source_kp else ""),
                "target_name": meta.get("target_name", target_kp.name if target_kp else ""),
            }
        )

    acyclic_relations.sort(
        key=lambda item: (
            item["source_node_id"] if item["source_node_id"] is not None else -1,
            item["target_node_id"] if item["target_node_id"] is not None else -1,
        )
    )
    return acyclic_relations, removed_cycles


# 将当前关系图缓存成 CSV，并返回缓存路径和关系列表。
def _save_relation_bundle(
    subject_id: int,
    relation_kind: str,
    knowledge_points: List[KnowledgePoint],
    node_rows: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
    removed_cycles: List[Dict[str, Any]],
    snapshot_hash: str,
) -> Dict[str, Any]:
    base_dir = _graph_base_dir(subject_id)
    base_dir.mkdir(parents=True, exist_ok=True)

    config = _graph_kind_config(relation_kind)
    node_path = base_dir / "knowledge_points.csv"
    edge_path = base_dir / config["edge_file"]
    alias_path = base_dir / config["graph_alias"]
    cycle_path = base_dir / config["cycle_file"]
    meta_path = base_dir / "graph_meta.csv"

    _write_csv(node_path, node_rows, ["node_id", "knowledge_point_id", "knowledge_point_name", "subject_id"])

    edge_rows = []
    kp_map = {kp.id: kp for kp in knowledge_points}
    for relation in relations:
        source_kp = kp_map.get(relation["source"])
        target_kp = kp_map.get(relation["target"])
        edge_rows.append(
            {
                "from": relation["source_node_id"],
                "to": relation["target_node_id"],
                "from_knowledge_point_id": relation["source"],
                "to_knowledge_point_id": relation["target"],
                "from_knowledge_point_name": source_kp.name if source_kp else relation.get("source_name", ""),
                "to_knowledge_point_name": target_kp.name if target_kp else relation.get("target_name", ""),
                "score": relation.get("score", 0.5),
                "reason": relation.get("reason", ""),
                "relation_kind": config["kind"],
            }
        )

    edge_columns = [
        "from",
        "to",
        "from_knowledge_point_id",
        "to_knowledge_point_id",
        "from_knowledge_point_name",
        "to_knowledge_point_name",
        "score",
        "reason",
        "relation_kind",
    ]
    _write_csv(edge_path, edge_rows, edge_columns)
    if alias_path != edge_path:
        _write_csv(alias_path, edge_rows, edge_columns)

    _write_csv(
        cycle_path,
        removed_cycles,
        [
            "relation_kind",
            "cycle_nodes",
            "removed_source_kp_id",
            "removed_target_kp_id",
            "removed_source_node_id",
            "removed_target_node_id",
            "removed_source_name",
            "removed_target_name",
            "score",
            "reason",
        ],
    )

    _write_csv(
        meta_path,
        [
            {
                "subject_id": subject_id,
                "relation_kind": config["kind"],
                "snapshot_hash": snapshot_hash,
                "node_count": len(node_rows),
                "edge_count": len(edge_rows),
                "removed_cycle_count": len(removed_cycles),
                "node_file": node_path.name,
                "edge_file": edge_path.name,
                "cycle_file": cycle_path.name,
                "generated_at": timezone.now().isoformat(),
            }
        ],
        [
            "subject_id",
            "relation_kind",
            "snapshot_hash",
            "node_count",
            "edge_count",
            "removed_cycle_count",
            "node_file",
            "edge_file",
            "cycle_file",
            "generated_at",
        ],
    )

    return {
        "base_dir": base_dir,
        "node_path": node_path,
        "edge_path": edge_path,
        "cycle_path": cycle_path,
        "meta_path": meta_path,
        "edge_rows": edge_rows,
        "relations": [
            {
                "source": row["from_knowledge_point_id"],
                "target": row["to_knowledge_point_id"],
                "score": row.get("score", 0.5),
                "reason": row.get("reason", ""),
            }
            for row in edge_rows
        ],
    }


# 获取某一类关系图的缓存包，有缓存就复用，没有就现场生成。
def get_relation_bundle(
    knowledge_points: List[KnowledgePoint],
    relation_kind: str = "prereq",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    if not knowledge_points:
        return {
            "relations": [],
            "node_rows": [],
            "removed_cycles": [],
            "graph_dir": None,
        }

    relation_kind = _graph_kind_config(relation_kind)["kind"]
    subject_id = knowledge_points[0].subject_id
    snapshot_hash = _snapshot_hash(knowledge_points, relation_kind=relation_kind)
    base_dir = _graph_base_dir(subject_id)
    config = _graph_kind_config(relation_kind)
    edge_path = base_dir / config["edge_file"]
    meta_path = base_dir / "graph_meta.csv"

    node_rows, kp_id_to_node_id, kp_name_to_id = _build_node_rows(knowledge_points)

    if not force_refresh and edge_path.exists() and meta_path.exists():
        try:
            meta_df = pd.read_csv(meta_path)
            meta_row = meta_df.loc[meta_df["relation_kind"] == relation_kind].iloc[0]
            if str(meta_row.get("snapshot_hash", "")) == snapshot_hash:
                edge_rows = pd.read_csv(edge_path).to_dict("records")
                cycle_path = base_dir / config["cycle_file"]
                removed_cycles = _read_csv(cycle_path)
                relations = []
                for row in edge_rows:
                    source = row.get("from_knowledge_point_id")
                    target = row.get("to_knowledge_point_id")
                    if pd.isna(source) or pd.isna(target):
                        continue
                    relations.append(
                        {
                            "source": int(source),
                            "target": int(target),
                            "score": float(row.get("score", 0.5) or 0.5),
                            "reason": row.get("reason", ""),
                        }
                    )
                return {
                    "relations": relations,
                    "node_rows": node_rows,
                    "removed_cycles": removed_cycles,
                    "graph_dir": base_dir,
                    "node_path": base_dir / "knowledge_points.csv",
                    "edge_path": edge_path,
                    "cycle_path": cycle_path,
                    "meta_path": meta_path,
                    "cache_hit": True,
                }
        except Exception:
            pass

    relations = _generate_relation_candidates(
        knowledge_points,
        relation_kind,
        kp_id_to_node_id,
        kp_name_to_id,
    )
    if not relations:
        relations = _db_knowledge_relations(knowledge_points, relation_kind)

    acyclic_relations, removed_cycles = _remove_cycles(
        relations,
        relation_kind,
        kp_id_to_node_id,
        knowledge_points,
    )

    bundle = _save_relation_bundle(
        subject_id=subject_id,
        relation_kind=relation_kind,
        knowledge_points=knowledge_points,
        node_rows=node_rows,
        relations=acyclic_relations,
        removed_cycles=removed_cycles,
        snapshot_hash=snapshot_hash,
    )
    bundle["node_rows"] = node_rows
    bundle["removed_cycles"] = removed_cycles
    bundle["graph_dir"] = base_dir
    bundle["cache_hit"] = False
    return bundle


# 统计每个知识点关联的题目数量，供诊断汇总使用。
def _count_exercises_per_kp(knowledge_points: List[KnowledgePoint]) -> Dict[int, int]:
    counts = defaultdict(int)
    for kp_id, count in QMatrix.objects.filter(knowledge_point__in=knowledge_points).values_list("knowledge_point_id").annotate():
        counts[kp_id] += 1
    return counts


# 汇总每个知识点的平均掌握度和题量，便于前端展示。
def _build_knowledge_point_summary(knowledge_points: List[KnowledgePoint], diagnosis_results: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    exercise_counts = defaultdict(int)
    for kp_id in QMatrix.objects.filter(knowledge_point__in=knowledge_points).values_list("knowledge_point_id", flat=True):
        exercise_counts[kp_id] += 1

    kp_mastery_sum = defaultdict(float)
    kp_mastery_count = defaultdict(int)
    for result in diagnosis_results.values():
        for kp_id_str, mastery in result.get("knowledge_mastery", {}).items():
            kp_id = _safe_int(kp_id_str, default=-1)
            if kp_id < 0:
                continue
            kp_mastery_sum[kp_id] += _safe_float(mastery, default=0.0)
            kp_mastery_count[kp_id] += 1

    summary = []
    for kp in knowledge_points:
        count = kp_mastery_count.get(kp.id, 0)
        avg_mastery = (kp_mastery_sum.get(kp.id, 0.0) / count * 100.0) if count > 0 else 0.0
        summary.append(
            {
                "id": kp.id,
                "name": kp.name,
                "avg_mastery": round(avg_mastery, 3),
                "exercise_count": exercise_counts.get(kp.id, 0),
            }
        )
    return summary


# 组装给前端或数据库使用的知识图谱元信息。
def _build_graph_info(bundle: Dict[str, Any], relation_kind: str) -> Dict[str, Any]:
    return {
        "relation_kind": relation_kind,
        "cache_hit": bundle.get("cache_hit", False),
        "graph_dir": str(bundle["graph_dir"]) if bundle.get("graph_dir") else "",
        "node_file": str(bundle["node_path"]) if bundle.get("node_path") else "",
        "edge_file": str(bundle["edge_path"]) if bundle.get("edge_path") else "",
        "cycle_file": str(bundle["cycle_path"]) if bundle.get("cycle_path") else "",
    }


# 在模型原始诊断结果上补充课程统计、知识点汇总和图谱信息。
def _augment_cdf_result(
    subject_id: int,
    model_name: str,
    base_data: Dict[str, Any],
    result: Dict[str, Any],
    prereq_bundle: Optional[Dict[str, Any]] = None,
    containment_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if "error" in result:
        return result

    knowledge_points = base_data["knowledge_points"]
    diagnosis_results = result.get("diagnosis_results", {})

    result["subject_id"] = subject_id
    result["model_type"] = model_name
    result["knowledge_points"] = _build_knowledge_point_summary(knowledge_points, diagnosis_results)
    result["total_students"] = len(base_data["students"])
    result["diagnosed_students"] = len(diagnosis_results)
    result["total_kp_count"] = len(knowledge_points)
    result["diagnosis_time"] = timezone.now().isoformat()

    if model_name == "ConCDF":
        bundle = containment_bundle
        result["knowledge_relations"] = (containment_bundle or {}).get("relations", [])
        result["knowledge_graph_info"] = _build_graph_info(bundle or {}, "containment")
    elif model_name == "PCG-CDF":
        result["knowledge_relations"] = (prereq_bundle or {}).get("relations", [])
        result["containment_knowledge_relations"] = (containment_bundle or {}).get("relations", [])
        result["knowledge_graph_info"] = {
            "relation_kind": "mix",
            "cache_hit": (prereq_bundle or {}).get("cache_hit", False) and (containment_bundle or {}).get("cache_hit", False),
            "graph_dir": str((prereq_bundle or {}).get("graph_dir", "")),
            "prereq_edge_file": str((prereq_bundle or {}).get("edge_path", "")),
            "containment_edge_file": str((containment_bundle or {}).get("edge_path", "")),
            "prereq_cycle_file": str((prereq_bundle or {}).get("cycle_path", "")),
            "containment_cycle_file": str((containment_bundle or {}).get("cycle_path", "")),
        }
    else:
        bundle = prereq_bundle or containment_bundle
        result["knowledge_relations"] = (bundle or {}).get("relations", [])
        result["knowledge_graph_info"] = _build_graph_info(bundle or {}, "prereq")

    return result


# 统一补齐 CDF 结果结构。
# 新训练结果和历史缓存结果都应整理成教师端当前所需的返回格式，
# 避免视图层因为缺少 total_kp_count / knowledge_points 等字段而报错。
def _normalize_cdf_result(
    subject_id: int,
    model_name: str,
    base_data: Dict[str, Any],
    result: Dict[str, Any],
    prereq_bundle: Optional[Dict[str, Any]] = None,
    containment_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = _augment_cdf_result(
        subject_id=subject_id,
        model_name=model_name,
        base_data=base_data,
        result=result,
        prereq_bundle=prereq_bundle,
        containment_bundle=containment_bundle,
    )

    # 历史缓存文件里可能没有 model_info，或字段不完整。
    # 这里补一个最小结构，保证后续需要读取模型信息时行为一致。
    model_info = result.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
        result["model_info"] = model_info
    model_info.setdefault("subject_id", subject_id)
    model_info.setdefault("model_name", model_name)

    return result


# 异步把诊断结果写回数据库，避免阻塞主流程。
def _save_cdf_results_to_database_async(subject_id: int, model_id: int, diagnosis_data: Dict[str, Any]) -> int:
    try:
        subject = Subject.objects.get(id=subject_id)
        diagnosis_model = DiagnosisModel.objects.get(id=model_id)
        knowledge_points = {
            kp.id: kp for kp in KnowledgePoint.objects.filter(subject=subject)
        }
        student_ids = [int(student_id) for student_id in diagnosis_data.get("diagnosis_results", {}).keys()]
        students = {
            student.id: student
            for student in User.objects.filter(id__in=student_ids, user_type="student")
        }

        records_to_save = []
        saved_students = set()
        for student_id_str, result_data in diagnosis_data.get("diagnosis_results", {}).items():
            student_id = int(student_id_str)
            student = students.get(student_id)
            if not student:
                continue

            for kp_str, mastery in result_data.get("knowledge_mastery", {}).items():
                kp_id = int(kp_str)
                knowledge_point = knowledge_points.get(kp_id)
                if not knowledge_point:
                    continue

                records_to_save.append(
                    {
                        "student_id": student_id,
                        "student": student,
                        "knowledge_point_id": kp_id,
                        "knowledge_point": knowledge_point,
                        "mastery": _safe_float(mastery, default=0.0),
                        "practice_count": _safe_int(result_data.get("practice_counts", {}).get(kp_str), default=0),
                        "correct_count": _safe_int(result_data.get("correct_counts", {}).get(kp_str), default=0),
                    }
                )
                saved_students.add(student_id)

        records_to_save.sort(key=lambda item: (item["student_id"], item["knowledge_point_id"]))
        existing_records = {}
        if records_to_save:
            existing = StudentDiagnosis.objects.filter(
                student_id__in=[record["student_id"] for record in records_to_save],
                knowledge_point_id__in=[record["knowledge_point_id"] for record in records_to_save],
                diagnosis_model=diagnosis_model,
            )
            for record in existing:
                existing_records[(record.student_id, record.knowledge_point_id)] = record

        current_time = timezone.now()
        batch_size = 20
        for start in range(0, len(records_to_save), batch_size):
            batch = records_to_save[start : start + batch_size]
            with transaction.atomic():
                to_create = []
                to_update = []
                for record in batch:
                    key = (record["student_id"], record["knowledge_point_id"])
                    if key in existing_records:
                        existing = existing_records[key]
                        existing.mastery_level = record["mastery"]
                        existing.practice_count = record["practice_count"]
                        existing.correct_count = record["correct_count"]
                        existing.last_practiced = current_time
                        to_update.append(existing)
                    else:
                        to_create.append(
                            StudentDiagnosis(
                                student=record["student"],
                                knowledge_point=record["knowledge_point"],
                                diagnosis_model=diagnosis_model,
                                mastery_level=record["mastery"],
                                practice_count=record["practice_count"],
                                correct_count=record["correct_count"],
                                last_practiced=current_time,
                            )
                        )

                if to_create:
                    StudentDiagnosis.objects.bulk_create(to_create, ignore_conflicts=True)
                if to_update:
                    StudentDiagnosis.objects.bulk_update(
                        to_update,
                        ["mastery_level", "practice_count", "correct_count", "last_practiced"],
                    )
        return len(saved_students)
    except Exception as exc:
        print(f"Failed to save CDF diagnosis results: {exc}")
        return 0


# 把 Path / numpy / datetime 等对象统一转成 JSON 可序列化的类型。
def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.int32, np.int64)):
        return int(value)
    if isinstance(value, (np.floating, np.float32, np.float64)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# 为任意可序列化对象生成稳定的哈希，用于区分不同训练任务。
def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_json_default)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


# 为 DataFrame 生成稳定哈希，数据一旦变化就不再复用旧缓存。
def _hash_dataframe(dataframe: Optional[pd.DataFrame]) -> str:
    if dataframe is None:
        return "none"
    if dataframe.empty:
        return "empty"
    payload = dataframe.to_json(orient="split", index=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# 为 Q 矩阵生成稳定哈希，便于判断训练输入是否发生变化。
def _hash_matrix(matrix: np.ndarray) -> str:
    array = np.asarray(matrix, dtype=np.float32)
    return hashlib.md5(array.tobytes()).hexdigest()


# 固定随机种子，降低不同环境下的训练波动。
def _set_random_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# 动态加载当前项目内的 CMD_survey 模型模块，不再依赖备份项目。
def _load_local_cmd_survey_module(model_dir_name: str, module_file_name: str, cache_key: str):
    if cache_key in _CMD_SURVEY_MODULE_CACHE:
        return _CMD_SURVEY_MODULE_CACHE[cache_key]

    module_dir = DIAGNOSIS_ROOT / "CMD_survey" / "model" / model_dir_name
    module_path = module_dir / module_file_name
    if not module_path.exists():
        raise FileNotFoundError(f"Cannot find local CMD_survey module: {module_path}")

    helper_module_names = ("dataloader", "itf", "tools")
    helper_backups = {name: sys.modules.get(name) for name in helper_module_names}
    for name in helper_module_names:
        sys.modules.pop(name, None)

    sys.path.insert(0, str(module_dir))
    try:
        spec = importlib.util.spec_from_file_location(f"local_cdf_bridge_{cache_key}", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load local module from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(module_dir))
        except ValueError:
            pass

        for name in helper_module_names:
            sys.modules.pop(name, None)
            backup = helper_backups.get(name)
            if backup is not None:
                sys.modules[name] = backup

    _CMD_SURVEY_MODULE_CACHE[cache_key] = module
    return module


# 把图谱缓存包转换成模型训练需要的 from/to DataFrame。
def _build_cdf_relation_frame(bundle: Optional[Dict[str, Any]]) -> pd.DataFrame:
    empty_frame = pd.DataFrame(columns=["from", "to"])
    if not bundle:
        return empty_frame

    edge_path = bundle.get("edge_path")
    if edge_path and Path(edge_path).exists():
        relation_df = pd.read_csv(edge_path)
        if {"from", "to"}.issubset(relation_df.columns):
            relation_df = relation_df.loc[:, ["from", "to"]].dropna(subset=["from", "to"]).copy()
            if relation_df.empty:
                return empty_frame
            relation_df["from"] = relation_df["from"].astype(int)
            relation_df["to"] = relation_df["to"].astype(int)
            return relation_df.reset_index(drop=True)

    edge_rows = bundle.get("edge_rows", [])
    if edge_rows:
        relation_df = pd.DataFrame(edge_rows)
        if {"from", "to"}.issubset(relation_df.columns):
            relation_df = relation_df.loc[:, ["from", "to"]].dropna(subset=["from", "to"]).copy()
            if relation_df.empty:
                return empty_frame
            relation_df["from"] = relation_df["from"].astype(int)
            relation_df["to"] = relation_df["to"].astype(int)
            return relation_df.reset_index(drop=True)

    return empty_frame


# 把学生答题日志整理成 CDF 模型可直接使用的训练/验证表。
def _build_cdf_training_dataset(
    students_data: Dict[int, Dict[str, Any]],
    knowledge_points: List[KnowledgePoint],
    q_matrix: np.ndarray,
) -> Dict[str, Any]:
    q_matrix = np.asarray(q_matrix, dtype=np.float32)
    student_ids = sorted(int(student_id) for student_id in students_data.keys())
    student_id_to_index = {student_id: index for index, student_id in enumerate(student_ids)}
    user_index_to_student_id = {index: student_id for student_id, index in student_id_to_index.items()}

    train_rows: List[Dict[str, int]] = []
    valid_rows: List[Dict[str, int]] = []
    log_rows: List[Dict[str, int]] = []
    practice_counts = defaultdict(lambda: defaultdict(int))
    correct_counts = defaultdict(lambda: defaultdict(int))
    answer_counts: Dict[int, int] = {}
    student_meta: Dict[int, Dict[str, str]] = {}

    for student_id in student_ids:
        student_data = students_data.get(student_id, {})
        answer_logs = list(student_data.get("answer_logs") or [])
        answer_counts[student_id] = len(answer_logs)
        student_meta[student_id] = {
            "student_name": str(student_data.get("first_name") or student_data.get("username") or student_id),
            "username": str(student_data.get("username") or student_id),
        }

        split_index = int(len(answer_logs) * 0.8)
        for order_index, log in enumerate(answer_logs):
            exercise_index = _safe_int(log.get("exercise_idx"), default=-1)
            if exercise_index < 0 or exercise_index >= q_matrix.shape[0]:
                continue

            score = 1 if bool(log.get("is_correct")) else 0
            row = {
                "user_id": student_id_to_index[student_id],
                "exercise_id": exercise_index,
                "score": score,
            }
            log_rows.append(dict(row))
            if order_index < split_index:
                train_rows.append(dict(row))
            else:
                valid_rows.append(dict(row))

            kp_indices = np.where(q_matrix[exercise_index] > 0)[0]
            for kp_index in kp_indices:
                kp_id = knowledge_points[int(kp_index)].id
                practice_counts[student_id][kp_id] += 1
                if score > 0:
                    correct_counts[student_id][kp_id] += 1

    train_df = pd.DataFrame(train_rows, columns=["user_id", "exercise_id", "score"])
    valid_df = pd.DataFrame(valid_rows, columns=["user_id", "exercise_id", "score"])
    log_df = pd.DataFrame(log_rows, columns=["user_id", "exercise_id", "score"])

    if train_df.empty:
        raise ValueError("No training logs available for the selected subject")
    if valid_df.empty:
        valid_df = None

    return {
        "train_df": train_df,
        "valid_df": valid_df,
        "log_df": log_df,
        "q_matrix": q_matrix,
        "n_user": len(student_ids),
        "n_item": int(q_matrix.shape[0]),
        "n_know": int(q_matrix.shape[1]),
        "user_index_to_student_id": user_index_to_student_id,
        "practice_counts": {student_id: dict(counts) for student_id, counts in practice_counts.items()},
        "correct_counts": {student_id: dict(counts) for student_id, counts in correct_counts.items()},
        "answer_counts": answer_counts,
        "student_meta": student_meta,
    }


# 统一构建本地 CDF 模型训练参数，尽量保持与现有日志结构一致。
def _build_cdf_hparams(
    n_user: int,
    n_item: int,
    n_know: int,
    checkpoint_file: Path,
    log_base_dir: Path,
) -> Dict[str, Any]:
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    log_base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "n_user": n_user,
        "n_item": n_item,
        "n_know": n_know,
        "hidden_dim": 1,
        "lr": 0.005,
        "mixed_lr": 0.001,
        "weight_decay": 1e-5,
        "epoch": 30,
        "batch_size": 512,
        "logger_mode": "file",
        "loss_factor": 0.001,
        "device": device,
        "batch_show": 10,
        "train_ratio": 0.8,
        "itf_type": "irt",
        "max_exercise_id": n_item,
        "base_log_path": str(log_base_dir),
        "Con_log_path": str(log_base_dir),
        "Hier_log_path": str(log_base_dir),
        "Mixed_log_path": str(log_base_dir),
        "model_name": str(checkpoint_file),
    }


# 把 state_dict 拷贝到 CPU 后再保存，避免跨设备加载出错。
def _copy_cdf_state_dict_to_cpu(model: Any) -> Dict[str, Any]:
    cpu_state = {}
    for key, value in model.state_dict().items():
        cpu_state[key] = value.detach().cpu() if torch.is_tensor(value) else value
    return cpu_state


# 统一保存模型 checkpoint。
def _save_cdf_model_checkpoint(model: Any, checkpoint_file: Path) -> None:
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    torch.save(_copy_cdf_state_dict_to_cpu(model), checkpoint_file)


# 获取模型 logger 实际落盘的日志目录。
def _resolve_cdf_model_log_dir(model: Any, fallback_log_dir: Path) -> str:
    logger = getattr(model, "logger", None)
    if logger is not None and getattr(logger, "path", None):
        return str(logger.path)
    return str(fallback_log_dir)


# 把掌握度矩阵组装成前端和数据库共用的诊断结果结构。
def _build_cdf_student_results(
    mastery_matrix: np.ndarray,
    knowledge_points: List[KnowledgePoint],
    dataset_context: Dict[str, Any],
) -> Dict[str, Any]:
    diagnosis_results: Dict[str, Any] = {}

    for user_index, student_id in dataset_context["user_index_to_student_id"].items():
        mastery_row = mastery_matrix[user_index] if user_index < mastery_matrix.shape[0] else np.zeros(len(knowledge_points))
        student_meta = dataset_context["student_meta"].get(student_id, {})
        student_practice = dataset_context["practice_counts"].get(student_id, {})
        student_correct = dataset_context["correct_counts"].get(student_id, {})

        knowledge_mastery: Dict[str, float] = {}
        practice_counts: Dict[str, int] = {}
        correct_counts: Dict[str, int] = {}
        knowledge_rows: List[Dict[str, Any]] = []

        for kp_index, kp in enumerate(knowledge_points):
            mastery_value = round(float(mastery_row[kp_index]), 4)
            kp_key = str(kp.id)
            practice_count = int(student_practice.get(kp.id, 0))
            correct_count = int(student_correct.get(kp.id, 0))

            knowledge_mastery[kp_key] = mastery_value
            practice_counts[kp_key] = practice_count
            correct_counts[kp_key] = correct_count
            knowledge_rows.append(
                {
                    "id": kp_key,
                    "name": kp.name,
                    "mastery": mastery_value,
                    "practice_count": practice_count,
                    "correct_count": correct_count,
                }
            )

        weak_points = sorted(
            [row for row in knowledge_rows if row["mastery"] < 0.6],
            key=lambda item: item["mastery"],
        )
        strong_points = sorted(
            [row for row in knowledge_rows if row["mastery"] >= 0.8],
            key=lambda item: item["mastery"],
            reverse=True,
        )

        diagnosis_results[str(student_id)] = {
            "student_id": int(student_id),
            "student_name": student_meta.get("student_name", str(student_id)),
            "username": student_meta.get("username", str(student_id)),
            "knowledge_mastery": knowledge_mastery,
            "practice_counts": practice_counts,
            "correct_counts": correct_counts,
            "overall_score": round(float(np.mean(mastery_row)) if len(mastery_row) > 0 else 0.0, 4),
            "weak_points": weak_points,
            "strong_points": strong_points,
            "answer_count": int(dataset_context["answer_counts"].get(student_id, 0)),
        }

    return diagnosis_results


# 本地 CDF 模型统一训练服务基类，负责数据准备、缓存判断、训练和结果落盘。
class _TrainableCDFDiagnosisService:
    model_name = ""
    method_name = ""
    model_dir_name = ""
    module_file_name = ""
    module_cache_key = ""
    model_class_name = ""
    metric_key = "mse"

    # 根据不同模型需要，返回参与训练的关系图帧。
    def _normalize_relations(
        self,
        prereq_frame: pd.DataFrame,
        containment_frame: pd.DataFrame,
    ) -> Dict[str, pd.DataFrame]:
        return {}

    # 子类负责实例化具体模型。
    def _build_model(self, context: Dict[str, Any]):
        raise NotImplementedError

    # 默认走 validate 获取验证指标，子类可以覆盖。
    def _evaluate_model(self, model: Any, context: Dict[str, Any]) -> Dict[str, float]:
        valid_df = context["dataset_context"]["valid_df"]
        if valid_df is None or valid_df.empty:
            return {}
        if hasattr(model, "validate"):
            try:
                metrics = model.validate(
                    valid_df,
                    context["dataset_context"]["q_matrix"],
                    context["hparams"]["device"],
                    context["hparams"]["logger_mode"],
                )
                return {key: float(value) for key, value in metrics.items()}
            except Exception:
                return {}
        return {}

    # 统一组装本次训练任务上下文，后续缓存判断和训练都基于它。
    def _build_context(
        self,
        students_data: Dict[int, Dict[str, Any]],
        knowledge_points: List[KnowledgePoint],
        q_matrix: np.ndarray,
        prereq_bundle: Optional[Dict[str, Any]] = None,
        containment_bundle: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        if not knowledge_points:
            raise ValueError("Knowledge points are required for CDF training")

        dataset_context = _build_cdf_training_dataset(students_data, knowledge_points, q_matrix)
        subject_id = int(knowledge_points[0].subject_id)
        prereq_frame = _build_cdf_relation_frame(prereq_bundle)
        containment_frame = _build_cdf_relation_frame(containment_bundle)
        relation_frames = self._normalize_relations(prereq_frame, containment_frame)
        relation_counts = {
            relation_name: int(frame.shape[0])
            for relation_name, frame in relation_frames.items()
            if frame is not None and not frame.empty
        }

        task_signature = _stable_hash(
            {
                "subject_id": subject_id,
                "model_name": self.model_name,
                "train_hash": _hash_dataframe(dataset_context["train_df"]),
                "valid_hash": _hash_dataframe(dataset_context["valid_df"]),
                "log_hash": _hash_dataframe(dataset_context["log_df"]),
                "q_hash": _hash_matrix(dataset_context["q_matrix"]),
                "relation_hashes": {
                    relation_name: _hash_dataframe(frame)
                    for relation_name, frame in relation_frames.items()
                },
            }
        )

        checkpoint_dir = CHECKPOINT_ROOT / f"subject_{subject_id}" / self.model_name / task_signature
        checkpoint_file = checkpoint_dir / "model.pt"
        result_file = checkpoint_dir / "result.json"
        meta_file = checkpoint_dir / "meta.json"
        log_base_dir = LOG_ROOT / f"subject_{subject_id}" / self.model_name / task_signature

        return {
            "subject_id": subject_id,
            "task_signature": task_signature,
            "checkpoint_dir": checkpoint_dir,
            "checkpoint_file": checkpoint_file,
            "result_file": result_file,
            "meta_file": meta_file,
            "log_base_dir": log_base_dir,
            "knowledge_points": knowledge_points,
            "dataset_context": dataset_context,
            "relation_frames": relation_frames,
            "relation_counts": relation_counts,
            "module": _load_local_cmd_survey_module(self.model_dir_name, self.module_file_name, self.module_cache_key),
            "hparams": _build_cdf_hparams(
                dataset_context["n_user"],
                dataset_context["n_item"],
                dataset_context["n_know"],
                checkpoint_file,
                log_base_dir,
            ),
        }

    # 先按任务签名尝试复用当前项目内已训练好的结果。
    def _load_cached_result(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result_file = context["result_file"]
        checkpoint_file = context["checkpoint_file"]
        if not result_file.exists() or not checkpoint_file.exists():
            return None

        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            return None

        model_info = result.get("model_info")
        if not isinstance(model_info, dict):
            model_info = {}
            result["model_info"] = model_info
        model_info["cache_hit"] = True
        return result

    # 把训练函数返回的 best epoch / auc / acc / mse(rmse) 统一整理。
    def _build_metrics_payload(
        self,
        train_result: Tuple[Any, Any, Any, Any],
        eval_metrics: Dict[str, float],
    ) -> Tuple[int, Dict[str, float]]:
        best_epoch, best_auc, best_acc, best_metric = train_result
        metrics = {key: float(value) for key, value in eval_metrics.items()}

        if best_acc is not None:
            metrics.setdefault("acc", float(best_acc))
        if best_auc is not None:
            metrics.setdefault("auc", float(best_auc))
        if best_metric is not None:
            metrics.setdefault(self.metric_key, float(best_metric))
        metrics.setdefault("f1", float(metrics.get("acc", 0.0)))

        if self.metric_key == "rmse" and "rmse" not in metrics and "mse" in metrics:
            metrics["rmse"] = float(np.sqrt(metrics["mse"])) if metrics["mse"] > 0 else 0.0
        if self.metric_key == "mse" and "mse" not in metrics and "rmse" in metrics:
            metrics["mse"] = float(metrics["rmse"])

        return _safe_int(best_epoch, default=-1), metrics

    # 统一运行训练，训练完成后同步落盘 checkpoint / result / meta。
    def _train_and_cache_result(self, context: Dict[str, Any]) -> Dict[str, Any]:
        dataset_context = context["dataset_context"]
        hparams = context["hparams"]

        _set_random_seed(42)
        context["checkpoint_dir"].mkdir(parents=True, exist_ok=True)
        context["log_base_dir"].mkdir(parents=True, exist_ok=True)

        model = self._build_model(context)
        train_result = model.train(
            hparams=hparams,
            train_data=dataset_context["train_df"],
            Q_matrix=dataset_context["q_matrix"],
            valid_data=dataset_context["valid_df"],
        )

        best_epoch, metrics = self._build_metrics_payload(
            train_result=train_result,
            eval_metrics=self._evaluate_model(model, context),
        )

        _save_cdf_model_checkpoint(model, context["checkpoint_file"])

        # PCG-CDF 自己定义了 eval(test_data, ...) 方法，这里显式调用
        # PyTorch 基类的 eval() 来切换推理模式，避免和其自定义评估接口冲突。
        torch.nn.Module.eval(model)
        if hasattr(model, "_to_device"):
            model._to_device(hparams["device"])
        else:
            model.to(hparams["device"])

        with torch.no_grad():
            user_tensor = torch.arange(dataset_context["n_user"], dtype=torch.long).to(hparams["device"])
            mastery_tensor = model.get_posterior(user_tensor, device=hparams["device"])
            mastery_matrix = mastery_tensor.detach().cpu().numpy()

        diagnosis_results = _build_cdf_student_results(
            mastery_matrix=np.asarray(mastery_matrix, dtype=np.float32),
            knowledge_points=context["knowledge_points"],
            dataset_context=dataset_context,
        )

        model_info = {
            "type": self.model_name,
            "method": self.method_name,
            "relation_count": int(sum(context["relation_counts"].values())),
            "cache_hit": False,
            "task_signature": context["task_signature"],
            "checkpoint_dir": str(context["checkpoint_dir"]),
            "checkpoint_file": str(context["checkpoint_file"]),
            "result_file": str(context["result_file"]),
            "meta_file": str(context["meta_file"]),
            "log_dir": _resolve_cdf_model_log_dir(model, context["log_base_dir"]),
            "best_epoch": best_epoch,
            "best_metrics": metrics,
            "train_sample_count": int(len(dataset_context["train_df"])),
            "valid_sample_count": int(len(dataset_context["valid_df"])) if dataset_context["valid_df"] is not None else 0,
            "relation_counts": context["relation_counts"],
        }

        result = {
            "diagnosis_results": diagnosis_results,
            "model_info": model_info,
        }

        meta_payload = {
            "task_signature": context["task_signature"],
            "subject_id": context["subject_id"],
            "model_name": self.model_name,
            "method_name": self.method_name,
            "checkpoint_file": str(context["checkpoint_file"]),
            "result_file": str(context["result_file"]),
            "meta_file": str(context["meta_file"]),
            "log_dir": model_info["log_dir"],
            "best_epoch": best_epoch,
            "best_metrics": metrics,
            "relation_count": model_info["relation_count"],
            "relation_counts": context["relation_counts"],
            "train_sample_count": model_info["train_sample_count"],
            "valid_sample_count": model_info["valid_sample_count"],
        }

        context["result_file"].write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        context["meta_file"].write_text(
            json.dumps(meta_payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        return result

    # 对外统一暴露的 CDF 诊断入口，先复用缓存，没有再训练。
    def run_diagnosis(self, **kwargs: Any) -> Dict[str, Any]:
        context = self._build_context(**kwargs)
        cached_result = self._load_cached_result(context)
        if cached_result is not None:
            return cached_result
        return self._train_and_cache_result(context)


# IdpCDF 不依赖额外知识图，只使用基础答题数据和 Q 矩阵。
class IdpCDFDiagnosisService(_TrainableCDFDiagnosisService):
    model_name = "IdpCDF"
    method_name = "trained_idpcdf"
    model_dir_name = "IdpCDF"
    module_file_name = "IdpCDF.py"
    module_cache_key = "idpcdf"
    model_class_name = "IRTCDM"
    metric_key = "mse"

    def _build_model(self, context: Dict[str, Any]):
        module = context["module"]
        dataset_context = context["dataset_context"]
        return getattr(module, self.model_class_name)(
            n_user=dataset_context["n_user"],
            n_item=dataset_context["n_item"],
            n_know=dataset_context["n_know"],
            hidden_dim=context["hparams"]["hidden_dim"],
            itf_type=context["hparams"]["itf_type"],
            log_path=str(context["log_base_dir"]),
        )


# HierCDF 需要先修图，用来建模知识点层次依赖。
class HierCDFDiagnosisService(_TrainableCDFDiagnosisService):
    model_name = "HierCDF"
    method_name = "trained_hierarchical_mastery"
    model_dir_name = "HierCDF"
    module_file_name = "HierCDF.py"
    module_cache_key = "hiercdf"
    model_class_name = "HierCDF"
    metric_key = "mse"

    def _normalize_relations(self, prereq_frame: pd.DataFrame, containment_frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        return {"prereq": prereq_frame}

    def _build_model(self, context: Dict[str, Any]):
        module = context["module"]
        dataset_context = context["dataset_context"]
        prereq_frame = context["relation_frames"].get("prereq", pd.DataFrame(columns=["from", "to"]))
        return getattr(module, self.model_class_name)(
            n_user=dataset_context["n_user"],
            n_item=dataset_context["n_item"],
            n_know=dataset_context["n_know"],
            hidden_dim=context["hparams"]["hidden_dim"],
            know_graph=prereq_frame,
            itf_type=context["hparams"]["itf_type"],
            log_path=str(context["log_base_dir"]),
        )


# ConCDF 需要包含图，并基于日志初始化关系强度和知识难度。
class ConCDFDiagnosisService(_TrainableCDFDiagnosisService):
    model_name = "ConCDF"
    method_name = "trained_containment_mastery"
    model_dir_name = "ConCDF"
    module_file_name = "ConCDF.py"
    module_cache_key = "concdf"
    model_class_name = "ConCDF"
    metric_key = "mse"

    def _normalize_relations(self, prereq_frame: pd.DataFrame, containment_frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        return {"containment": containment_frame}

    def _build_model(self, context: Dict[str, Any]):
        module = context["module"]
        dataset_context = context["dataset_context"]
        containment_frame = context["relation_frames"].get("containment", pd.DataFrame(columns=["from", "to"]))
        if containment_frame.empty:
            init_relation = np.zeros(0, dtype=np.float32)
        else:
            init_relation = module.compute_relation_init(
                dataset_context["train_df"],
                dataset_context["q_matrix"],
                containment_frame,
            )
        init_diff = module.compute_know_diff_from_logs(
            dataset_context["log_df"],
            dataset_context["q_matrix"],
            method="inverse_accuracy",
        )
        return getattr(module, self.model_class_name)(
            n_user=dataset_context["n_user"],
            n_item=dataset_context["n_item"],
            n_know=dataset_context["n_know"],
            hidden_dim=context["hparams"]["hidden_dim"],
            know_graph=containment_frame,
            itf_type=context["hparams"]["itf_type"],
            log_path=str(context["log_base_dir"]),
            init_R=init_relation,
            init_diff=init_diff,
        )


# PCG-CDF 同时融合先修图和包含图，因此需要两套关系信息共同训练。
class PCGCDFDiagnosisService(_TrainableCDFDiagnosisService):
    model_name = "PCG-CDF"
    method_name = "trained_pcg_cdf"
    model_dir_name = "PCGCDF"
    module_file_name = "PCGCDF.py"
    module_cache_key = "pcgcdf"
    model_class_name = "MixedModel"
    metric_key = "rmse"

    def _normalize_relations(self, prereq_frame: pd.DataFrame, containment_frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        return {
            "prereq": prereq_frame,
            "containment": containment_frame,
        }

    def _evaluate_model(self, model: Any, context: Dict[str, Any]) -> Dict[str, float]:
        valid_df = context["dataset_context"]["valid_df"]
        if valid_df is None or valid_df.empty:
            return {}
        try:
            metrics = model.eval(
                valid_df,
                context["dataset_context"]["q_matrix"],
                context["hparams"]["batch_size"],
                context["hparams"]["device"],
            )
            return {key: float(value) for key, value in metrics.items()}
        except Exception:
            return {}

    def _build_model(self, context: Dict[str, Any]):
        module = context["module"]
        dataset_context = context["dataset_context"]
        prereq_frame = context["relation_frames"].get("prereq", pd.DataFrame(columns=["from", "to"]))
        containment_frame = context["relation_frames"].get("containment", pd.DataFrame(columns=["from", "to"]))
        if containment_frame.empty:
            init_relation = np.zeros(0, dtype=np.float32)
        else:
            init_relation = module.compute_relation_init(
                dataset_context["train_df"],
                dataset_context["q_matrix"],
                containment_frame,
            )
        init_diff = module.compute_know_diff_from_logs(
            dataset_context["log_df"],
            dataset_context["q_matrix"],
            method="inverse_accuracy",
        )
        return getattr(module, self.model_class_name)(
            n_user=dataset_context["n_user"],
            n_item=dataset_context["n_item"],
            n_know=dataset_context["n_know"],
            hidden_dim=context["hparams"]["hidden_dim"],
            hier_graph=prereq_frame,
            con_graph=containment_frame,
            itf_type=context["hparams"]["itf_type"],
            log_path=str(context["log_base_dir"]),
            init_R=init_relation,
            init_diff=init_diff,
        )


# 动态加载 BP 项目里的 CDF 诊断服务实现，并切换到当前项目路径。
def _load_cdf_services():
    raise RuntimeError("BP-backed CDF services are disabled; use local bridge services instead.")
    bp_path = (
        Path(settings.BASE_DIR).resolve().parent.parent
        / "Education_system_bp"
        / "learning"
        / "diagnosis"
        / "models"
        / "cdf_diagnosis.py"
    )
    if not bp_path.exists():
        raise FileNotFoundError(f"Cannot find BP cdf_diagnosis.py: {bp_path}")

    import importlib.util

    module_name = "bp_cdf_diagnosis_bridge"
    spec = importlib.util.spec_from_file_location(module_name, bp_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {bp_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 外部 BP 代码里仍然使用旧的目录名和文件名，这里统一重定向到当前仓库的新命名。
    original_loader = module._load_cmd_survey_module

    def _load_cmd_survey_module(model_dir_name: str, module_file_name: str, cache_key: str):
        if model_dir_name == "BaseModel":
            model_dir_name = "IdpCDF"
            module_file_name = "IdpCDF.py"
        elif model_dir_name == "MixCDF":
            model_dir_name = "PCGCDF"
            module_file_name = "PCGCDF.py"
        return original_loader(model_dir_name, module_file_name, cache_key)

    module._load_cmd_survey_module = _load_cmd_survey_module
    module.BaseModelDiagnosisService.model_name = "IdpCDF"
    module.BaseModelDiagnosisService.method_name = "trained_idpcdf"
    module.MixCDFDiagnosisService.model_name = "PCG-CDF"
    module.MixCDFDiagnosisService.method_name = "trained_pcg_cdf"
    module.IdpCDFDiagnosisService = module.BaseModelDiagnosisService
    module.PCGCDFDiagnosisService = module.MixCDFDiagnosisService

    # Force the imported BP implementation to use the current repository's
    # diagnosis assets and writable cache directories instead of writing back
    # into the BP reference project.
    module._DIAGNOSIS_ROOT = DIAGNOSIS_ROOT
    module._CMD_SURVEY_MODEL_ROOT = DIAGNOSIS_ROOT / "CMD_survey" / "model"
    module._CHECKPOINT_ROOT = DIAGNOSIS_ROOT / "checkpoints"
    module._LOG_ROOT = DIAGNOSIS_ROOT / "cdflogs"
    module._CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    module._LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return module


# 查找指定课程和模型最近一次可复用的训练结果。
def _find_cached_cdf_result(subject_id: int, model_name: str) -> Optional[Dict[str, Any]]:
    model_dir_map = {
        "IdpCDF": "IdpCDF",
        "HierCDF": "HierCDF",
        "ConCDF": "ConCDF",
        "PCG-CDF": "PCG-CDF",
    }
    model_dir_name = model_dir_map.get(model_name, model_name)
    checkpoint_root = CHECKPOINT_ROOT / f"subject_{subject_id}" / model_dir_name
    if not checkpoint_root.exists():
        return None

    candidates = []
    for result_file in checkpoint_root.rglob("result.json"):
        try:
            stat = result_file.stat()
        except OSError:
            continue
        candidates.append((stat.st_mtime, result_file))

    for _, result_file in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        model_info = result.get("model_info", {})
        checkpoint_file = model_info.get("checkpoint_file")
        if checkpoint_file and Path(checkpoint_file).exists():
            return result

    return None


# 按模型名选择对应的 BP 诊断服务类。
def _select_cdf_service(model_name: str):
    # 根据模型名选择对应的 BP 诊断服务类。
    # 这里仍然复用底层实现类名，只是入口改成新模型名。
    # 改为直接使用当前项目中的本地实现，不再从备份工程动态加载。
    if model_name == "IdpCDF":
        return IdpCDFDiagnosisService()
    if model_name == "HierCDF":
        return HierCDFDiagnosisService()
    if model_name == "ConCDF":
        return ConCDFDiagnosisService()
    if model_name == "PCG-CDF":
        return PCGCDFDiagnosisService()
    raise ValueError(f"Unsupported CDF model: {model_name}")


# 按模型决定需要加载哪几类知识关系图。
def _relation_bundles_for_model(
    model_name: str,
    knowledge_points: List[KnowledgePoint],
    force_graph_refresh: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    # 不同 CDF 模型需要的图关系不同：
    # HierCDF 只要先修图，ConCDF 只要包含图，PCG-CDF 两者都要。
    prereq_bundle = None
    containment_bundle = None

    if model_name in {"HierCDF", "PCG-CDF"}:
        prereq_bundle = get_relation_bundle(
            knowledge_points=knowledge_points,
            relation_kind="prereq",
            force_refresh=force_graph_refresh,
        )
    if model_name in {"ConCDF", "PCG-CDF"}:
        containment_bundle = get_relation_bundle(
            knowledge_points=knowledge_points,
            relation_kind="containment",
            force_refresh=force_graph_refresh,
        )

    return prereq_bundle, containment_bundle


# CDF 模型统一训练入口：准备数据、装配图关系、调用具体诊断服务。
def train_cdf_model(subject_id: int, model_name: str, force_graph_refresh: bool = False) -> Dict[str, Any]:
    # 这是 CDF 模型统一训练入口：
    # 1) 先构造基础数据
    # 2) 再按模型准备关系图
    # 3) 最后把数据喂给对应的诊断服务
    model_name = normalize_cdf_model_name(model_name)
    base_data = build_cdf_diagnosis_data(subject_id)
    if "error" in base_data:
        return base_data

    knowledge_points = base_data["knowledge_points"]
    if not force_graph_refresh:
        cached_result = _find_cached_cdf_result(subject_id, model_name)
        if cached_result:
            print(f"复用已保存的 {model_name} 训练结果")
            prereq_bundle = None
            containment_bundle = None
            if model_name in {"HierCDF", "ConCDF", "PCG-CDF"}:
                prereq_bundle, containment_bundle = _relation_bundles_for_model(
                    model_name=model_name,
                    knowledge_points=knowledge_points,
                    force_graph_refresh=force_graph_refresh,
                )
            return _normalize_cdf_result(
                subject_id=subject_id,
                model_name=model_name,
                base_data=base_data,
                result=cached_result,
                prereq_bundle=prereq_bundle,
                containment_bundle=containment_bundle,
            )

    prereq_bundle, containment_bundle = _relation_bundles_for_model(
        model_name=model_name,
        knowledge_points=knowledge_points,
        force_graph_refresh=force_graph_refresh,
    )

    service = _select_cdf_service(model_name)
    kwargs = {
        "students_data": base_data["students"],
        "exercises": base_data["exercises"],
        "knowledge_points": knowledge_points,
        "q_matrix": base_data["Q_matrix"],
    }
    if model_name == "IdpCDF":
        # IdpCDF 不依赖额外关系图，只使用基础答题数据和 Q 矩阵。
        pass
    elif model_name == "HierCDF":
        # 层次型模型只需要先修关系图。
        kwargs["knowledge_relations"] = (prereq_bundle or {}).get("relations", [])
    elif model_name == "ConCDF":
        # 包含关系模型只需要包含关系图。
        kwargs["knowledge_relations"] = (containment_bundle or {}).get("relations", [])
    elif model_name == "PCG-CDF":
        # PCG-CDF 同时融合先修关系和包含关系，因此要把两类图都传进去。
        kwargs["knowledge_relations"] = (prereq_bundle or {}).get("relations", [])
        kwargs["knowledge_relation_bundles"] = {
            "prereq": (prereq_bundle or {}).get("relations", []),
            "containment": (containment_bundle or {}).get("relations", []),
        }

    result = service.run_diagnosis(**kwargs)
    result = _normalize_cdf_result(
        subject_id=subject_id,
        model_name=model_name,
        base_data=base_data,
        result=result,
        prereq_bundle=prereq_bundle,
        containment_bundle=containment_bundle,
    )
    return result


# 对外暴露的完整诊断流水线：训练后按需写回数据库。
def run_cdf_diagnosis_pipeline(
    subject_id: int,
    model_id: int,
    model_name: str,
    save_to_db: bool = True,
    force_graph_refresh: bool = False,
) -> Dict[str, Any]:
    result = train_cdf_model(
        subject_id=subject_id,
        model_name=model_name,
        force_graph_refresh=force_graph_refresh,
    )
    if "error" in result:
        return result

    if save_to_db:
        _save_cdf_results_to_database_async(subject_id, model_id, result)

    return result
