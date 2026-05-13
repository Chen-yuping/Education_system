# coding: utf-8
#杞棬鎺?
import csv
import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
try:
    from EduCDM import CDM
except ImportError:
    class CDM(object):
        pass
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable
try:
    from sklearn.metrics import (
        accuracy_score as sklearn_accuracy_score,
        f1_score as sklearn_f1_score,
        precision_score as sklearn_precision_score,
        recall_score as sklearn_recall_score,
        roc_auc_score as sklearn_roc_auc_score,
    )
except ImportError:
    sklearn_accuracy_score = None
    sklearn_f1_score = None
    sklearn_precision_score = None
    sklearn_recall_score = None
    sklearn_roc_auc_score = None


def _load_pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required only when plot_path is set.") from exc
    return plt


def _to_numpy_int_labels(values):
    return np.array(values, dtype=np.int64)


def _accuracy_score(y_true, y_pred_label):
    if sklearn_accuracy_score is not None:
        return float(sklearn_accuracy_score(y_true, y_pred_label))
    true_arr = _to_numpy_int_labels(y_true)
    pred_arr = _to_numpy_int_labels(y_pred_label)
    if true_arr.size == 0:
        return 0.0
    return float(np.mean(true_arr == pred_arr))


def _binary_confusion(y_true, y_pred_label):
    true_arr = _to_numpy_int_labels(y_true)
    pred_arr = _to_numpy_int_labels(y_pred_label)
    tp = int(np.sum((true_arr == 1) & (pred_arr == 1)))
    fp = int(np.sum((true_arr == 0) & (pred_arr == 1)))
    fn = int(np.sum((true_arr == 1) & (pred_arr == 0)))
    return tp, fp, fn


def _precision_score(y_true, y_pred_label):
    if sklearn_precision_score is not None:
        return float(sklearn_precision_score(y_true, y_pred_label, zero_division=0))
    tp, fp, _ = _binary_confusion(y_true, y_pred_label)
    denom = tp + fp
    return float(tp / denom) if denom else 0.0


def _recall_score(y_true, y_pred_label):
    if sklearn_recall_score is not None:
        return float(sklearn_recall_score(y_true, y_pred_label, zero_division=0))
    tp, _, fn = _binary_confusion(y_true, y_pred_label)
    denom = tp + fn
    return float(tp / denom) if denom else 0.0


def _f1_score(y_true, y_pred_label):
    if sklearn_f1_score is not None:
        return float(sklearn_f1_score(y_true, y_pred_label, zero_division=0))
    precision = _precision_score(y_true, y_pred_label)
    recall = _recall_score(y_true, y_pred_label)
    denom = precision + recall
    return float((2.0 * precision * recall) / denom) if denom else 0.0


def _roc_auc_score(y_true, y_pred):
    if sklearn_roc_auc_score is not None:
        try:
            return float(sklearn_roc_auc_score(y_true, y_pred))
        except ValueError:
            return 0.5
    true_arr = _to_numpy_int_labels(y_true)
    pred_arr = np.array(y_pred, dtype=np.float64)
    pos_mask = true_arr == 1
    neg_mask = true_arr == 0
    pos_count = int(np.sum(pos_mask))
    neg_count = int(np.sum(neg_mask))
    if pos_count == 0 or neg_count == 0:
        return 0.5

    order = np.argsort(pred_arr)
    sorted_scores = pred_arr[order]
    ranks = np.empty(len(pred_arr), dtype=np.float64)
    start = 0
    while start < len(sorted_scores):
        end = start + 1
        while end < len(sorted_scores) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        avg_rank = (start + end - 1) / 2.0 + 1.0
        ranks[order[start:end]] = avg_rank
        start = end

    pos_rank_sum = float(np.sum(ranks[pos_mask]))
    auc = (pos_rank_sum - (pos_count * (pos_count + 1) / 2.0)) / (pos_count * neg_count)
    return float(auc)


class PosLinear(nn.Linear):
    def forward(self, input_tensor: torch.Tensor) -> torch.Tensor:
        weight = 2 * F.relu(torch.neg(self.weight)) + self.weight
        return F.linear(input_tensor, weight, self.bias)


class DualRelationSparseQNet(nn.Module):
    def __init__(
        self,
        knowledge_n: int,
        exer_n: int,
        student_n: int,
        prereq_active_top_k: int = 1,
        similarity_active_top_k: int = 1,
        initial_prereq_gate: float = 0.1,
        initial_similarity_gate: float = 0.1,
    ):
        super().__init__()
        self.knowledge_dim = knowledge_n
        self.exer_n = exer_n
        self.emb_num = student_n
        self.stu_dim = self.knowledge_dim
        self.prednet_input_len = self.knowledge_dim
        self.prednet_len1, self.prednet_len2 = 512, 256
        self.prereq_active_top_k = prereq_active_top_k
        self.similarity_active_top_k = similarity_active_top_k

        prereq_gate = min(max(initial_prereq_gate, 1e-4), 1.0 - 1e-4)
        sim_gate = min(max(initial_similarity_gate, 1e-4), 1.0 - 1e-4)
        prereq_logit = float(np.log(prereq_gate / (1.0 - prereq_gate)))
        sim_logit = float(np.log(sim_gate / (1.0 - sim_gate)))

        self.prereq_gate_logits = nn.Parameter(
            torch.full((self.exer_n, self.knowledge_dim), prereq_logit, dtype=torch.float32)
        )
        self.similarity_gate_logits = nn.Parameter(
            torch.full((self.exer_n, self.knowledge_dim), sim_logit, dtype=torch.float32)
        )

        self.student_emb = nn.Embedding(self.emb_num, self.stu_dim)
        self.k_difficulty = nn.Embedding(self.exer_n, self.knowledge_dim)
        self.e_difficulty = nn.Embedding(self.exer_n, 1)
        self.prednet_full1 = PosLinear(self.prednet_input_len, self.prednet_len1)
        self.drop_1 = nn.Dropout(p=0.5)
        self.prednet_full2 = PosLinear(self.prednet_len1, self.prednet_len2)
        self.drop_2 = nn.Dropout(p=0.5)
        self.prednet_full3 = PosLinear(self.prednet_len2, 1)

        for name, param in self.named_parameters():
            if "weight" in name:
                nn.init.xavier_normal_(param)

    def current_prereq_gate(self) -> torch.Tensor:
        return torch.sigmoid(self.prereq_gate_logits)

    def current_similarity_gate(self) -> torch.Tensor:
        return torch.sigmoid(self.similarity_gate_logits)

    @staticmethod
    def _select_sparse_gate(
        gate_values: torch.Tensor,
        residual: torch.Tensor,
        active_top_k: int,
    ) -> torch.Tensor:
        candidate_mask = residual > 0
        if active_top_k <= 0 or not torch.any(candidate_mask):
            return torch.zeros_like(gate_values)

        if active_top_k >= gate_values.shape[1]:
            return gate_values * candidate_mask.to(gate_values.dtype)

        masked_scores = gate_values.masked_fill(~candidate_mask, -1.0)
        top_values, top_indices = torch.topk(masked_scores, k=active_top_k, dim=1)
        selected_mask = (top_values > 0).to(gate_values.dtype)
        sparse_mask = torch.zeros_like(gate_values)
        sparse_mask.scatter_(1, top_indices, selected_mask)
        return gate_values * sparse_mask

    def compose_q(
        self,
        input_exercise: torch.Tensor,
        q_original: torch.Tensor,
        q_prereq_residual: torch.Tensor,
        q_similarity_residual: torch.Tensor,
        force_zero_gate: bool = False,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if force_zero_gate:
            prereq_gate = torch.zeros_like(q_original)
            similarity_gate = torch.zeros_like(q_original)
        else:
            prereq_gate_full = self.current_prereq_gate()[input_exercise]
            similarity_gate_full = self.current_similarity_gate()[input_exercise]
            prereq_gate = self._select_sparse_gate(
                prereq_gate_full,
                q_prereq_residual,
                active_top_k=self.prereq_active_top_k,
            )
            similarity_gate = self._select_sparse_gate(
                similarity_gate_full,
                q_similarity_residual,
                active_top_k=self.similarity_active_top_k,
            )

        q_adjusted = q_original + prereq_gate * q_prereq_residual + similarity_gate * q_similarity_residual
        return q_adjusted, prereq_gate, similarity_gate

    def forward(
        self,
        stu_id: torch.Tensor,
        input_exercise: torch.Tensor,
        q_original: torch.Tensor,
        q_prereq_residual: torch.Tensor,
        q_similarity_residual: torch.Tensor,
        force_zero_gate: bool = False,
        return_gate_values: bool = False,
    ):
        input_knowledge_point, prereq_gate, similarity_gate = self.compose_q(
            input_exercise,
            q_original,
            q_prereq_residual,
            q_similarity_residual,
            force_zero_gate=force_zero_gate,
        )

        stu_emb = self.student_emb(stu_id)
        stat_emb = torch.sigmoid(stu_emb)
        k_difficulty = torch.sigmoid(self.k_difficulty(input_exercise))
        e_difficulty = torch.sigmoid(self.e_difficulty(input_exercise))
        input_x = e_difficulty * (stat_emb - k_difficulty) * input_knowledge_point

        input_x = self.drop_1(torch.sigmoid(self.prednet_full1(input_x)))
        input_x = self.drop_2(torch.sigmoid(self.prednet_full2(input_x)))
        output = torch.sigmoid(self.prednet_full3(input_x)).view(-1)

        if return_gate_values:
            return output, prereq_gate, similarity_gate
        return output


class NCDM(CDM):
    def __init__(
        self,
        knowledge_n: int,
        exer_n: int,
        student_n: int,
        prereq_active_top_k: int = 1,
        similarity_active_top_k: int = 1,
        initial_prereq_gate: float = 0.1,
        initial_similarity_gate: float = 0.1,
        prereq_gate_l1_weight: float = 1e-5,
        similarity_gate_l1_weight: float = 1e-5,
    ):
        super().__init__()
        self.ncdm_net = DualRelationSparseQNet(
            knowledge_n,
            exer_n,
            student_n,
            prereq_active_top_k=prereq_active_top_k,
            similarity_active_top_k=similarity_active_top_k,
            initial_prereq_gate=initial_prereq_gate,
            initial_similarity_gate=initial_similarity_gate,
        )
        self.prereq_gate_l1_weight = prereq_gate_l1_weight
        self.similarity_gate_l1_weight = similarity_gate_l1_weight

    @staticmethod
    def search_best_threshold(y_true: List[float], y_pred: List[float]) -> Dict[str, float]:
        y_true_np = np.array(y_true)
        y_pred_np = np.array(y_pred)
        best_threshold = 0.5
        best_accuracy = -1.0

        for threshold in np.linspace(0.1, 0.9, 81):
            accuracy = _accuracy_score(y_true_np, y_pred_np >= threshold)
            if accuracy > best_accuracy:
                best_accuracy = float(accuracy)
                best_threshold = float(threshold)
        return {"threshold": best_threshold, "accuracy": best_accuracy}

    def predict_scores(
        self,
        data_loader,
        device: str = "cpu",
        force_zero_gate: bool = False,
    ) -> Tuple[List[float], List[float], Dict[str, float]]:
        self.ncdm_net = self.ncdm_net.to(device)
        self.ncdm_net.eval()
        y_true, y_pred = [], []
        prereq_sum = 0.0
        prereq_count = 0
        prereq_max = 0.0
        similarity_sum = 0.0
        similarity_count = 0
        similarity_max = 0.0

        with torch.no_grad():
            for user_id, item_id, q_original, q_prereq_residual, q_similarity_residual, y in tqdm(data_loader, "Evaluating"):
                user_id = user_id.to(device)
                item_id = item_id.to(device)
                q_original = q_original.to(device)
                q_prereq_residual = q_prereq_residual.to(device)
                q_similarity_residual = q_similarity_residual.to(device)
                pred, prereq_gate, similarity_gate = self.ncdm_net(
                    user_id,
                    item_id,
                    q_original,
                    q_prereq_residual,
                    q_similarity_residual,
                    force_zero_gate=force_zero_gate,
                    return_gate_values=True,
                )
                y_pred.extend(pred.detach().cpu().tolist())
                y_true.extend(y.tolist())

                prereq_positive = prereq_gate[prereq_gate > 0]
                if prereq_positive.numel() > 0:
                    prereq_sum += float(prereq_positive.sum().item())
                    prereq_count += int(prereq_positive.numel())
                    prereq_max = max(prereq_max, float(prereq_positive.max().item()))

                similarity_positive = similarity_gate[similarity_gate > 0]
                if similarity_positive.numel() > 0:
                    similarity_sum += float(similarity_positive.sum().item())
                    similarity_count += int(similarity_positive.numel())
                    similarity_max = max(similarity_max, float(similarity_positive.max().item()))

        gate_stats = {
            "prereq_gate_mean": prereq_sum / prereq_count if prereq_count else 0.0,
            "prereq_gate_max": prereq_max,
            "similarity_gate_mean": similarity_sum / similarity_count if similarity_count else 0.0,
            "similarity_gate_max": similarity_max,
        }
        return y_true, y_pred, gate_stats

    def evaluate(
        self,
        data_loader,
        device: str = "cpu",
        threshold: Optional[float] = None,
        force_zero_gate: bool = False,
    ) -> Dict[str, float]:
        y_true, y_pred, gate_stats = self.predict_scores(data_loader, device=device, force_zero_gate=force_zero_gate)
        y_true_arr = np.array(y_true, dtype=np.float64)
        y_pred_arr = np.array(y_pred, dtype=np.float64)
        auc = float(_roc_auc_score(y_true, y_pred))
        rmse = float(np.sqrt(np.mean((y_true_arr - y_pred_arr) ** 2)))
        if threshold is None:
            threshold_info = self.search_best_threshold(y_true, y_pred)
            threshold = threshold_info["threshold"]
            accuracy = threshold_info["accuracy"]
        else:
            accuracy = float(_accuracy_score(y_true, np.array(y_pred) >= threshold))

        y_label = (np.array(y_pred) >= threshold).astype(int)

        return {
            "auc": auc,
            "accuracy": float(accuracy),
            "rmse": rmse,
            "threshold": float(threshold),
            "precision": float(_precision_score(y_true, y_label)),
            "recall": float(_recall_score(y_true, y_label)),
            "f1": float(_f1_score(y_true, y_label)),
            **gate_stats,
        }

    def _collect_full_q_matrices(self, data_loader, device: str = "cpu") -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Collect full original, prerequisite-residual, and similarity-residual Q matrices.
        Returns tensors with shape (exer_n, knowledge_dim).
        """
        exer_n = self.ncdm_net.exer_n
        knowledge_dim = self.ncdm_net.knowledge_dim

        q_original_full = torch.zeros(exer_n, knowledge_dim, device=device)
        q_prereq_full = torch.zeros(exer_n, knowledge_dim, device=device)
        q_similarity_full = torch.zeros(exer_n, knowledge_dim, device=device)

        with torch.no_grad():
            for _, item_id, q_orig, q_prereq, q_sim, _ in tqdm(data_loader, desc="Collecting full Q matrices"):
                item_id = item_id.to(device)
                q_orig = q_orig.to(device)
                q_prereq = q_prereq.to(device)
                q_sim = q_sim.to(device)

                for idx, exer in enumerate(item_id):
                    q_original_full[exer] = q_orig[idx]
                    q_prereq_full[exer] = q_prereq[idx]
                    q_similarity_full[exer] = q_sim[idx]

        return q_original_full, q_prereq_full, q_similarity_full

    def export_q_matrix(
        self,
        q_original: torch.Tensor,
        q_prereq_residual: torch.Tensor,
        q_similarity_residual: torch.Tensor,
        device: str = "cpu",
        output_path: str = "final_q_matrix.csv",
    ) -> None:
        """
        Calculate adjusted Q vectors for all exercises and save them as CSV.
        """
        self.ncdm_net.eval()
        self.ncdm_net.to(device)

        exer_ids = torch.arange(q_original.shape[0], device=device)
        q_original = q_original.to(device)
        q_prereq_residual = q_prereq_residual.to(device)
        q_similarity_residual = q_similarity_residual.to(device)

        with torch.no_grad():
            q_adjusted, _, _ = self.ncdm_net.compose_q(
                exer_ids,
                q_original,
                q_prereq_residual,
                q_similarity_residual,
                force_zero_gate=False,
            )
        # q_adjusted shape: (exer_n, knowledge_dim)
        df = pd.DataFrame(q_adjusted.cpu().numpy())
        df.to_csv(output_path, index=False, header=False)
        print(f"Q matrix saved to {output_path}")

    def train(
        self,
        train_data,
        valid_data=None,
        epoch: int = 10,
        device: str = "cpu",
        lr: float = 0.002,
        history_csv_path: Optional[Union[str, Path]] = None,
        model_path: Optional[Union[str, Path]] = None,
        plot_path: Optional[Union[str, Path]] = None,
        use_fixed_threshold_eval: bool = False,
        gate_warmup_epoch: int = 0,
        q_save_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        if q_save_path is not None:
            print("Collecting full Q matrices from train_data...")
            q_orig_full, q_prereq_full, q_sim_full = self._collect_full_q_matrices(train_data, device=device)
        else:
            q_orig_full = q_prereq_full = q_sim_full = None

        self.ncdm_net = self.ncdm_net.to(device)
        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.ncdm_net.parameters(), lr=lr)
        history: List[Dict[str, float]] = []
        best_metrics: Optional[Dict[str, float]] = None
        best_state_dict = None

        history_csv = Path(history_csv_path) if history_csv_path else None
        if history_csv:
            history_csv.parent.mkdir(parents=True, exist_ok=True)

        for epoch_index in range(epoch):
            self.ncdm_net.train()
            epoch_losses = []
            warmup_mode = epoch_index < gate_warmup_epoch

            for user_id, item_id, q_original, q_prereq_residual, q_similarity_residual, y in tqdm(train_data, f"Epoch {epoch_index + 1}/{epoch}"):
                user_id = user_id.to(device)
                item_id = item_id.to(device)
                q_original = q_original.to(device)
                q_prereq_residual = q_prereq_residual.to(device)
                q_similarity_residual = q_similarity_residual.to(device)
                y = y.to(device)

                pred = self.ncdm_net(
                    user_id,
                    item_id,
                    q_original,
                    q_prereq_residual,
                    q_similarity_residual,
                    force_zero_gate=warmup_mode,
                )
                if warmup_mode:
                    gate_penalty = 0.0
                else:
                    gate_penalty = (
                        self.prereq_gate_l1_weight * self.ncdm_net.current_prereq_gate().mean()
                        + self.similarity_gate_l1_weight * self.ncdm_net.current_similarity_gate().mean()
                    )
                loss = loss_function(pred, y) + gate_penalty

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                epoch_losses.append(loss.mean().item())

            row: Dict[str, float] = {"epoch": float(epoch_index + 1), "train_loss": float(np.mean(epoch_losses))}

            if valid_data is not None:
                metrics = self.evaluate(
                    valid_data,
                    device=device,
                    threshold=0.5 if use_fixed_threshold_eval else None,
                    force_zero_gate=warmup_mode,
                )
                row.update(
                    {
                        "val_auc": metrics["auc"],
                        "val_acc": metrics["accuracy"],
                        "val_rmse": metrics["rmse"],
                        "val_threshold": metrics["threshold"],
                        "precision": metrics["precision"],
                        "recall": metrics["recall"],
                        "f1": metrics["f1"],
                        "prereq_gate_mean": metrics["prereq_gate_mean"],
                        "prereq_gate_max": metrics["prereq_gate_max"],
                        "similarity_gate_mean": metrics["similarity_gate_mean"],
                        "similarity_gate_max": metrics["similarity_gate_max"],
                        "warmup_mode": float(1 if warmup_mode else 0),
                    }
                )
                print(
                    "[Epoch %d] loss=%.6f auc=%.6f acc=%.6f pg=%.4f sg=%.4f warmup=%d"
                    % (
                        epoch_index + 1,
                        row["train_loss"],
                        row["val_auc"],
                        row["val_acc"],
                        row["prereq_gate_mean"],
                        row["similarity_gate_mean"],
                        1 if warmup_mode else 0,
                    )
                )

                if best_metrics is None or row["val_auc"] > best_metrics["val_auc"]:
                    best_metrics = row.copy()
                    best_state_dict = copy.deepcopy(self.ncdm_net.state_dict())
                    if model_path:
                        model_path = Path(model_path)
                        model_path.parent.mkdir(parents=True, exist_ok=True)
                        torch.save(self.ncdm_net.state_dict(), model_path)
            history.append(row)

        if best_state_dict is not None:
            self.ncdm_net.load_state_dict(best_state_dict)

        if q_save_path is not None and q_orig_full is not None:
            print("Saving final Q matrix after training...")
            self.export_q_matrix(
                q_orig_full,
                q_prereq_full,
                q_sim_full,
                device=device,
                output_path=str(q_save_path),
            )

        if history_csv and history:
            with history_csv.open("w", newline="", encoding="utf-8") as csv_file:
                fieldnames = list(history[0].keys())
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(history)

        if plot_path and valid_data is not None and history:
            plt = _load_pyplot()
            plot_path = Path(plot_path)
            plot_path.parent.mkdir(parents=True, exist_ok=True)
            epochs = [int(row["epoch"]) for row in history]
            aucs = [row["val_auc"] for row in history]
            accs = [row["val_acc"] for row in history]
            plt.figure(figsize=(12, 5))
            plt.subplot(1, 2, 1)
            plt.plot(epochs, aucs, marker="o")
            plt.xlabel("Epoch")
            plt.ylabel("AUC")
            plt.title("Validation AUC")
            plt.grid(True)

            plt.subplot(1, 2, 2)
            plt.plot(epochs, accs, marker="s")
            plt.xlabel("Epoch")
            plt.ylabel("Accuracy")
            plt.title("Validation Accuracy")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(plot_path, dpi=300)
            plt.close()

        return {"history": history, "best_metrics": best_metrics}

    def eval(self, test_data, device: str = "cpu"):
        metrics = self.evaluate(test_data, device=device, threshold=0.5)
        return metrics["auc"], metrics["accuracy"]

    def save(self, filepath: Union[str, Path]) -> None:
        torch.save(self.ncdm_net.state_dict(), filepath)
        logging.info("save parameters to %s", filepath)

    def load(self, filepath: Union[str, Path]) -> None:
        self.ncdm_net.load_state_dict(torch.load(filepath, map_location="cpu"))
        logging.info("load parameters from %s", filepath)

