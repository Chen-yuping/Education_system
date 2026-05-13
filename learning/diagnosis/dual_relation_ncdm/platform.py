import csv
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset as TorchDataset

from . import MODEL_NAMES, NO_GATE_MODEL_NAMES
from .NCDM.NCDM_dual_relation_sparse_q_fit import NCDM as SoftGateNCDM
from .NCDM.NCDM_dual_relation_sparse_q_fit_wumenkong import NCDM as NoGateNCDM


BASE_DIR = Path(__file__).resolve().parent
DIAGNOSIS_DATA_DIR = BASE_DIR.parent / "data"
CMD_SURVEY_DATA_DIR = BASE_DIR.parent / "CMD_survey" / "data"
RESEARCHER_DATASETS = {
    "math_pr": CMD_SURVEY_DATA_DIR / "Math-PR",
    "assist115_pr": CMD_SURVEY_DATA_DIR / "Assist115-PR",
    "assist175_pr": CMD_SURVEY_DATA_DIR / "Assist175-PR",
    "eedi_pr": CMD_SURVEY_DATA_DIR / "Eedi-PR",
    "ird_math": CMD_SURVEY_DATA_DIR / "Math-PR",
    "ird_assist_115": CMD_SURVEY_DATA_DIR / "Assist115-PR",
    "ird_assist_175": CMD_SURVEY_DATA_DIR / "Assist175-PR",
    "ird_eedi": CMD_SURVEY_DATA_DIR / "Eedi-PR",
}

SEED = 20260403
PREREQ_ALPHA = 0.25
PREREQ_MAX_ITER = 10
PREREQ_CANDIDATE_TOP_K = 100
SIMILARITY_CANDIDATE_TOP_K = 0
PREREQ_ACTIVE_TOP_K = 70
SIMILARITY_ACTIVE_TOP_K = 0
LEARNING_RATE = 0.002
EPOCHS = 10
BATCH_SIZE = 256
INITIAL_PREREQ_GATE = 0.7
INITIAL_SIMILARITY_GATE = 0.25
PREREQ_GATE_L1_WEIGHT = 1e-5
SIMILARITY_GATE_L1_WEIGHT = 1e-5
GATE_WARMUP_EPOCH = 0

TRAINED_SUBJECT_RUNS = {}


def is_dual_relation_model(model_name):
    return model_name in MODEL_NAMES


def get_model_variant(model_name):
    return "no_gate" if model_name in NO_GATE_MODEL_NAMES else "soft_gate"


def get_model_class(model_name):
    return NoGateNCDM if get_model_variant(model_name) == "no_gate" else SoftGateNCDM


class AssistDataset(TorchDataset):
    def __init__(self, records):
        self.records = records

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        user, item, q_original, q_prereq_residual, q_similarity_residual, correct = self.records[index]
        return (
            torch.tensor(user, dtype=torch.long),
            torch.tensor(item, dtype=torch.long),
            torch.tensor(q_original, dtype=torch.float32),
            torch.tensor(q_prereq_residual, dtype=torch.float32),
            torch.tensor(q_similarity_residual, dtype=torch.float32),
            torch.tensor(correct, dtype=torch.float32),
        )


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def build_relation_signal(base_q, related_q):
    delta = np.maximum(related_q - base_q, 0.0)
    row_max = delta.max(axis=1, keepdims=True)
    row_max[row_max == 0.0] = 1.0
    signal = delta / row_max
    return np.clip(signal, 0.0, None)


def keep_topk_per_row(matrix, top_k):
    if top_k <= 0:
        return np.zeros_like(matrix)
    if top_k >= matrix.shape[1]:
        return matrix.copy()

    output = np.zeros_like(matrix)
    for row_idx in range(matrix.shape[0]):
        row = matrix[row_idx]
        nonzero_indices = np.flatnonzero(row > 0)
        if len(nonzero_indices) <= top_k:
            output[row_idx, nonzero_indices] = row[nonzero_indices]
            continue
        top_indices = nonzero_indices[np.argsort(row[nonzero_indices])[-top_k:]]
        output[row_idx, top_indices] = row[top_indices]
    return output


def normalize_index(value, count):
    value = int(value)
    if 1 <= value <= count:
        return value - 1
    if 0 <= value < count:
        return value
    return None


def read_config(data_dir):
    config_path = Path(data_dir) / "config.txt"
    if not config_path.exists():
        return None
    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [int(part.strip()) for part in line.split(",")]
        if len(parts) >= 3:
            return {"student_n": parts[0], "exercise_n": parts[1], "knowledge_n": parts[2]}
    return None


def read_json_records(path):
    with Path(path).open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def infer_stats(records):
    max_user = max(int(row["user_id"]) for row in records) if records else 0
    max_exer = max(int(row["exer_id"]) for row in records) if records else 0
    max_kp = 0
    for row in records:
        for code in row.get("knowledge_code") or []:
            max_kp = max(max_kp, int(code))
    return {"student_n": max_user, "exercise_n": max_exer, "knowledge_n": max_kp}


def read_homologous_mapping(data_dir):
    mapping_path = Path(data_dir) / "homologous.csv"
    student_mapping = {}
    exercise_mapping = {}
    skill_mapping = {}
    if not mapping_path.exists():
        return student_mapping, exercise_mapping, skill_mapping

    with mapping_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get("new_user_id") and row.get("original_user_id"):
                student_mapping[int(row["new_user_id"]) - 1] = int(row["original_user_id"])
            if row.get("new_exer_id") and row.get("original_exer_id"):
                exercise_mapping[int(row["new_exer_id"]) - 1] = int(row["original_exer_id"])
            if row.get("new_knowledge_code") and row.get("original_knowledge_code"):
                skill_mapping[int(row["new_knowledge_code"]) - 1] = int(row["original_knowledge_code"])
    return student_mapping, exercise_mapping, skill_mapping


def build_q_original(records, stats):
    q_original = np.zeros((stats["exercise_n"], stats["knowledge_n"]), dtype=np.float32)
    for row in records:
        exer_idx = normalize_index(row["exer_id"], stats["exercise_n"])
        if exer_idx is None:
            continue
        knowledge_codes = row.get("knowledge_code") or []
        if not knowledge_codes:
            q_original[exer_idx, :] = 1.0
            continue
        for code in knowledge_codes:
            kp_idx = normalize_index(code, stats["knowledge_n"])
            if kp_idx is not None:
                q_original[exer_idx, kp_idx] = 1.0
    return q_original


def build_prereq_matrix(stats, edges):
    prereq = np.zeros((stats["knowledge_n"], stats["knowledge_n"]), dtype=np.float32)
    for source_idx, target_idx in edges:
        if source_idx is None or target_idx is None:
            continue
        if 0 <= source_idx < stats["knowledge_n"] and 0 <= target_idx < stats["knowledge_n"]:
            prereq[target_idx, source_idx] = 1.0
    return prereq


def propagate_q(q_original, prereq_matrix):
    if prereq_matrix.size == 0 or not np.any(prereq_matrix):
        return q_original.copy()

    propagated = q_original.astype(np.float32).copy()
    current = q_original.astype(np.float32).copy()
    weight = PREREQ_ALPHA
    for _ in range(PREREQ_MAX_ITER):
        current = current @ prereq_matrix
        if not np.any(current):
            break
        propagated = np.maximum(propagated, np.clip(current * weight, 0.0, 1.0))
        weight *= PREREQ_ALPHA
    return np.clip(propagated, 0.0, 1.0)


def build_q_result_from_records(records, stats, edges):
    q_original = build_q_original(records, stats)
    prereq_matrix = build_prereq_matrix(stats, edges)
    q_prereq_continuous = propagate_q(q_original, prereq_matrix)
    q_prereq_signal = build_relation_signal(q_original, q_prereq_continuous)
    q_similarity_signal = np.zeros_like(q_original, dtype=np.float32)
    return {
        "q_original": q_original,
        "q_prereq_continuous": q_prereq_continuous,
        "q_similarity": q_original.copy(),
        "q_prereq_residual": keep_topk_per_row(q_prereq_signal, top_k=PREREQ_CANDIDATE_TOP_K),
        "q_similarity_residual": keep_topk_per_row(q_similarity_signal, top_k=SIMILARITY_CANDIDATE_TOP_K),
    }


def convert_json_rows(rows, stats, q_result):
    records = []
    for row in rows:
        user_idx = normalize_index(row["user_id"], stats["student_n"])
        exer_idx = normalize_index(row["exer_id"], stats["exercise_n"])
        if user_idx is None or exer_idx is None:
            continue
        records.append(
            (
                user_idx,
                exer_idx,
                q_result["q_original"][exer_idx].astype(np.float32),
                q_result["q_prereq_residual"][exer_idx].astype(np.float32),
                q_result["q_similarity_residual"][exer_idx].astype(np.float32),
                float(row["score"]),
            )
        )
    return records


def read_adjacency_edges(data_dir, stats):
    edges_path = Path(data_dir) / "prerequisite_edges.csv"
    if not edges_path.exists():
        return []
    edges = []
    with edges_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            source = row.get("source_skill_id") or row.get("source") or row.get("source_id")
            target = row.get("target_skill_id") or row.get("target") or row.get("target_id")
            if source and target:
                edges.append((normalize_index(source, stats["knowledge_n"]), normalize_index(target, stats["knowledge_n"])))
    return edges


def read_subject_edges(subject_id, skill_mapping, stats):
    from learning.models import KnowledgeGraph

    original_to_idx = {original_id: idx for idx, original_id in skill_mapping.items()}
    edges = []
    for source_id, target_id in KnowledgeGraph.objects.filter(subject_id=subject_id).values_list("source_id", "target_id"):
        edges.append((original_to_idx.get(source_id), original_to_idx.get(target_id)))
    return edges


def build_context_from_json_dir(data_dir, subject_id=None):
    data_dir = Path(data_dir)
    log_path = data_dir / "log_data.json"
    train_rows = read_json_records(data_dir / "train.json")
    val_rows = read_json_records(data_dir / "val.json")
    log_rows = read_json_records(log_path) if log_path.exists() else train_rows + val_rows

    stats = read_config(data_dir) or infer_stats(train_rows + val_rows + log_rows)
    student_mapping, exercise_mapping, skill_mapping = read_homologous_mapping(data_dir)
    student_mapping = student_mapping or {idx: idx + 1 for idx in range(stats["student_n"])}
    exercise_mapping = exercise_mapping or {idx: idx + 1 for idx in range(stats["exercise_n"])}
    skill_mapping = skill_mapping or {idx: idx + 1 for idx in range(stats["knowledge_n"])}

    edges = read_subject_edges(subject_id, skill_mapping, stats) if subject_id is not None else read_adjacency_edges(data_dir, stats)
    q_result = build_q_result_from_records(train_rows + val_rows + log_rows, stats, edges)

    return {
        "stats": stats,
        "q_result": q_result,
        "train_records": convert_json_rows(train_rows, stats, q_result),
        "valid_records": convert_json_rows(val_rows, stats, q_result),
        "log_rows": log_rows,
        "student_mapping": student_mapping,
        "exercise_mapping": exercise_mapping,
        "skill_mapping": skill_mapping,
        "data_dir": data_dir,
    }


def has_system_dataset_files(data_dir):
    data_dir = Path(data_dir)
    return (data_dir / "train.json").exists() and (data_dir / "val.json").exists() and (data_dir / "config.txt").exists()


def resolve_system_dataset_dir(dataset_name):
    raw_name = str(dataset_name or "")
    compact_name = "".join(ch for ch in raw_name if ch.isalnum()).lower()
    candidates = [
        CMD_SURVEY_DATA_DIR / raw_name,
        DIAGNOSIS_DATA_DIR / raw_name,
    ]

    normalized = raw_name.lower().replace("-", "_").replace(" ", "_")
    mapped_dir = RESEARCHER_DATASETS.get(normalized)
    if mapped_dir:
        candidates.append(mapped_dir)

    alias_map = {
        "irdmath": "Math-PR",
        "irdassist115": "Assist115-PR",
        "irdassist175": "Assist175-PR",
        "irdeedi": "Eedi-PR",
        "mathpr": "Math-PR",
        "assist115pr": "Assist115-PR",
        "assist175pr": "Assist175-PR",
        "eedipr": "Eedi-PR",
    }
    alias_dir_name = alias_map.get(compact_name)
    if alias_dir_name:
        candidates.append(CMD_SURVEY_DATA_DIR / alias_dir_name)
        candidates.append(DIAGNOSIS_DATA_DIR / alias_dir_name)

    for base_dir in (CMD_SURVEY_DATA_DIR, DIAGNOSIS_DATA_DIR):
        if not base_dir.exists():
            continue
        for child in base_dir.iterdir():
            if not child.is_dir():
                continue
            child_compact = "".join(ch for ch in child.name if ch.isalnum()).lower()
            if child_compact == compact_name:
                candidates.append(child)

    for candidate in candidates:
        if has_system_dataset_files(candidate):
            return candidate
    return None


def build_loader(records, shuffle, seed):
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(AssistDataset(records), batch_size=BATCH_SIZE, shuffle=shuffle, generator=generator)


def make_model(stats, model_name="GDNCDM"):
    model_class = get_model_class(model_name)
    return model_class(
        knowledge_n=stats["knowledge_n"],
        exer_n=stats["exercise_n"],
        student_n=stats["student_n"],
        prereq_active_top_k=PREREQ_ACTIVE_TOP_K,
        similarity_active_top_k=SIMILARITY_ACTIVE_TOP_K,
        initial_prereq_gate=INITIAL_PREREQ_GATE,
        initial_similarity_gate=INITIAL_SIMILARITY_GATE,
        prereq_gate_l1_weight=PREREQ_GATE_L1_WEIGHT,
        similarity_gate_l1_weight=SIMILARITY_GATE_L1_WEIGHT,
    )


def train_from_context(context, model_name="GDNCDM"):
    set_seed(SEED)
    train_records = context["train_records"]
    valid_records = context["valid_records"] or train_records
    if not train_records:
        raise ValueError("DNCDM requires at least one training record.")

    train_loader = build_loader(train_records, shuffle=True, seed=SEED)
    valid_loader = build_loader(valid_records, shuffle=False, seed=SEED)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = make_model(context["stats"], model_name=model_name)
    start_time = time.time()
    train_result = model.train(
        train_data=train_loader,
        valid_data=valid_loader,
        epoch=EPOCHS,
        device=device,
        lr=LEARNING_RATE,
        history_csv_path=None,
        model_path=None,
        plot_path=None,
        use_fixed_threshold_eval=True,
        gate_warmup_epoch=GATE_WARMUP_EPOCH,
    )
    total_time = time.time() - start_time

    metrics = model.evaluate(valid_loader, device=device, threshold=0.5)
    history = train_result.get("history") or []
    training_curves = {
        "acc": [float(row.get("val_acc") or 0.0) for row in history],
        "auc": [float(row.get("val_auc") or 0.0) for row in history],
        "rmse": [float(row.get("val_rmse") or 0.0) for row in history],
    }
    best_metrics = train_result.get("best_metrics") or {}
    result = {
        "best_epoch": int(best_metrics.get("epoch") or EPOCHS),
        "auc": float(metrics["auc"]),
        "acc": float(metrics["accuracy"]),
        "rmse": float(metrics.get("rmse") or 0.0),
        "training_curves": training_curves,
        "history": history,
        "total_time": float(total_time),
        "best_round_time": 0.0,
        "model_path": "",
        "stats": context["stats"],
    }
    return result, model


def train_subject(subject_id, model_name="GDNCDM"):
    data_dir = DIAGNOSIS_DATA_DIR / str(subject_id)
    if not (data_dir / "train.json").exists() or not (data_dir / "val.json").exists():
        from learning.diagnosis.data_export import export_training_data

        export_training_data(subject_id)

    context = build_context_from_json_dir(data_dir, subject_id=subject_id)
    result, model = train_from_context(context, model_name=model_name)
    TRAINED_SUBJECT_RUNS[(int(subject_id), model_name)] = {"model": model, "context": context, "result": result}
    return result


def train_researcher_dataset(dataset_name, model_name="GDNCDM"):
    dataset_dir = resolve_system_dataset_dir(dataset_name)
    if dataset_dir:
        context = build_context_from_json_dir(dataset_dir)
        result, _ = train_from_context(context, model_name=model_name)
        return result
    if str(dataset_name).isdigit():
        return train_subject(int(dataset_name), model_name=model_name)
    raise ValueError("DNCDM now reads the original train.json/val.json dataset interface. Convert this dataset before training.")


def get_subject_model_and_context(subject_id, model_name):
    cache_key = (int(subject_id), model_name)
    cached = TRAINED_SUBJECT_RUNS.get(cache_key)
    if cached:
        return cached["model"], cached["context"]
    train_subject(subject_id, model_name=model_name)
    cached = TRAINED_SUBJECT_RUNS[cache_key]
    return cached["model"], cached["context"]


def extract_mastery(model):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.ncdm_net.to(device)
    model.ncdm_net.eval()
    with torch.no_grad():
        return torch.sigmoid(model.ncdm_net.student_emb.weight).detach().cpu().numpy()


def infer_and_get_diagnosis_data(subject_id, model_id, model_name):
    if not is_dual_relation_model(model_name):
        return None

    model, context = get_subject_model_and_context(subject_id, model_name)
    mastery = extract_mastery(model)
    student_mapping = context["student_mapping"]
    skill_mapping = context["skill_mapping"]

    student_known_skills = defaultdict(set)
    student_skill_stats = defaultdict(lambda: {"practice_count": 0, "correct_count": 0})
    stats = context["stats"]
    for row in context["log_rows"]:
        student_idx = normalize_index(row["user_id"], stats["student_n"])
        if student_idx is None:
            continue
        knowledge_codes = row.get("knowledge_code") or []
        score_value = float(row.get("score", 0) or 0)
        is_correct = score_value >= 0.5
        if not knowledge_codes:
            student_known_skills[student_idx].update(range(stats["knowledge_n"]))
            for skill_idx in range(stats["knowledge_n"]):
                student_skill_stats[(student_idx, skill_idx)]["practice_count"] += 1
                if is_correct:
                    student_skill_stats[(student_idx, skill_idx)]["correct_count"] += 1
            continue
        for code in knowledge_codes:
            skill_idx = normalize_index(code, stats["knowledge_n"])
            if skill_idx is not None:
                student_known_skills[student_idx].add(skill_idx)
                student_skill_stats[(student_idx, skill_idx)]["practice_count"] += 1
                if is_correct:
                    student_skill_stats[(student_idx, skill_idx)]["correct_count"] += 1

    from django.utils import timezone
    from learning.models import DiagnosisModel, KnowledgeGraph, KnowledgePoint, StudentDiagnosis, User

    diagnosis_model = DiagnosisModel.objects.get(id=model_id)
    kp_info = {kp.id: kp.name for kp in KnowledgePoint.objects.filter(subject_id=subject_id)}
    users = User.objects.in_bulk(student_mapping.values())
    diagnosis_results = {}
    kp_mastery_sum = defaultdict(float)
    kp_count = defaultdict(int)
    diagnosis_rows = []

    for student_idx, student_original_id in student_mapping.items():
        student_obj = users.get(student_original_id)
        student_mastery = {}
        weak_points = []
        for skill_idx in student_known_skills.get(student_idx, set()):
            kp_original_id = skill_mapping.get(skill_idx)
            if kp_original_id is None:
                continue
            value = float(mastery[student_idx][skill_idx])
            skill_stats = student_skill_stats[(student_idx, skill_idx)]
            student_mastery[str(kp_original_id)] = round(value, 3)
            kp_mastery_sum[kp_original_id] += value
            kp_count[kp_original_id] += 1
            if value < 0.6:
                weak_points.append({"id": int(kp_original_id), "name": kp_info.get(kp_original_id, "Unknown"), "mastery": round(value, 3)})
            if student_obj:
                diagnosis_rows.append(
                    (
                        student_original_id,
                        kp_original_id,
                        round(value, 3),
                        int(skill_stats["practice_count"]),
                        int(skill_stats["correct_count"]),
                    )
                )

        overall_score = round(sum(student_mastery.values()) / len(student_mastery), 3) if student_mastery else 0.0
        diagnosis_results[student_original_id] = {
            "student_id": student_original_id,
            "student_name": student_obj.username if student_obj else "Student%s" % student_original_id,
            "overall_score": overall_score,
            "knowledge_mastery": student_mastery,
            "weak_points": weak_points,
            "answer_count": len(student_mastery),
        }

    now = timezone.now()
    existing = {
        (row.student_id, row.knowledge_point_id): row
        for row in StudentDiagnosis.objects.filter(
            diagnosis_model=diagnosis_model,
            student_id__in=[row[0] for row in diagnosis_rows],
            knowledge_point_id__in=[row[1] for row in diagnosis_rows],
        )
    }
    to_create = []
    to_update = []
    for student_id, knowledge_point_id, mastery_value, practice_count, correct_count in diagnosis_rows:
        key = (student_id, knowledge_point_id)
        diagnosis = existing.get(key)
        if diagnosis:
            diagnosis.mastery_level = mastery_value
            diagnosis.practice_count = practice_count
            diagnosis.correct_count = correct_count
            diagnosis.last_practiced = now
            to_update.append(diagnosis)
        else:
            to_create.append(
                StudentDiagnosis(
                    student_id=student_id,
                    knowledge_point_id=knowledge_point_id,
                    diagnosis_model=diagnosis_model,
                    mastery_level=mastery_value,
                    practice_count=practice_count,
                    correct_count=correct_count,
                    last_practiced=now,
                )
            )

    if to_create:
        StudentDiagnosis.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
    if to_update:
        StudentDiagnosis.objects.bulk_update(
            to_update,
            ["mastery_level", "practice_count", "correct_count", "last_practiced"],
            batch_size=500,
        )

    knowledge_points_data = []
    for kp_id, name in kp_info.items():
        avg_mastery = round((kp_mastery_sum.get(kp_id, 0) / kp_count.get(kp_id, 1)) * 100, 3)
        knowledge_points_data.append({"id": int(kp_id), "name": name, "avg_mastery": avg_mastery, "exercise_count": 0})

    knowledge_relations = [
        {"source": int(source_id), "target": int(target_id)}
        for source_id, target_id in KnowledgeGraph.objects.filter(subject_id=subject_id).values_list("source_id", "target_id")
    ]

    return {
        "knowledge_points": knowledge_points_data,
        "diagnosis_results": diagnosis_results,
        "knowledge_relations": knowledge_relations,
        "total_students": len(diagnosis_results),
        "total_kp_count": len(knowledge_points_data),
    }
