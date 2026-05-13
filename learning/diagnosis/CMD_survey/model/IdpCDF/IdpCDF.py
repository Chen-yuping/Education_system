import os
import os.path as osp
import warnings

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error, roc_auc_score

from dataloader import TrainDataLoader
from itf import itf_dict
from tools import Logger, format_hparams, labelize, to_numpy

warnings.filterwarnings("ignore")
torch.set_default_tensor_type(torch.DoubleTensor)


class IRTCDM(nn.Module):
    """
    去掉利用知识图谱，构建关系传递后的对比模型
    """

    def __init__(
        self,
        n_user: int,
        n_item: int,
        n_know: int,
        hidden_dim: int,
        itf_type: str = "irt",
        log_path: str = "./log/",
    ):
        super().__init__()
        self.logger = Logger(path=log_path)
        self.max_exercise_id = None

        self.n_user = n_user
        self.n_item = n_item
        self.n_know = n_know
        self.hidden_dim = hidden_dim
        self.interaction_dim = 1 if itf_type == "irt" else hidden_dim

        # User mastery is learned directly, without graph-based propagation.
        self.user_mastery = nn.Embedding(n_user, n_know)

        # Question feature module stays aligned with the other models.
        self.item_diff = nn.Embedding(n_item, n_know)
        self.item_disc = nn.Embedding(n_item, 1)
        self.user_contract = nn.Linear(n_know, self.interaction_dim)
        self.item_contract = nn.Linear(n_know, self.interaction_dim)

        # Fallback neural interaction module, consistent with the repo design.
        cross_hidden = max(int(self.interaction_dim / 2), 1)
        self.cross_layer1 = nn.Linear(self.interaction_dim, cross_hidden)
        self.cross_layer2 = nn.Linear(cross_hidden, 1)

        self.set_itf(itf_type)
        self._init_parameters()

    def _init_parameters(self):
        nn.init.xavier_normal_(self.user_mastery.weight)
        nn.init.xavier_normal_(self.item_diff.weight)
        nn.init.xavier_normal_(self.item_disc.weight)
        nn.init.xavier_normal_(self.user_contract.weight)
        nn.init.xavier_normal_(self.item_contract.weight)
        nn.init.xavier_normal_(self.cross_layer1.weight)
        nn.init.xavier_normal_(self.cross_layer2.weight)

        if self.user_contract.bias is not None:
            nn.init.zeros_(self.user_contract.bias)
        if self.item_contract.bias is not None:
            nn.init.zeros_(self.item_contract.bias)
        if self.cross_layer1.bias is not None:
            nn.init.zeros_(self.cross_layer1.bias)
        if self.cross_layer2.bias is not None:
            nn.init.zeros_(self.cross_layer2.bias)

    def ncd(self, user_emb: torch.Tensor, item_emb: torch.Tensor, item_offset: torch.Tensor):
        input_vec = (user_emb - item_emb) * item_offset
        x_vec = torch.sigmoid(self.cross_layer1(input_vec))
        x_vec = torch.sigmoid(self.cross_layer2(x_vec))
        return x_vec

    def set_itf(self, itf_type: str):
        self.itf_type = itf_type
        self.itf = itf_dict.get(itf_type, self.ncd)

    def get_posterior(self, user_ids: torch.LongTensor, device="cpu") -> torch.Tensor:
        # No relation graph: posterior mastery is directly learned per user.
        return torch.sigmoid(self.user_mastery(user_ids.to(device)))

    def _infer_item_column(self, data: pd.DataFrame):
        if data is None:
            return None
        for candidate in ("exercise_id", "exer_id", "item_id"):
            if candidate in data.columns:
                return candidate
        return None

    def _filter_samples_by_item_id(
        self,
        data: pd.DataFrame,
        max_item_id: int,
        logger_mode: str = "console",
        stage: str = "",
    ):
        if data is None or max_item_id is None:
            return data
        item_col = self._infer_item_column(data)
        if item_col is None:
            self.logger.write(
                "Skip {} filtering: no exercise id column detected.".format(stage or "data"),
                logger_mode,
            )
            return data

        mask = data[item_col] < max_item_id
        filtered = data.loc[mask].reset_index(drop=True)
        removed = data.shape[0] - filtered.shape[0]
        if removed > 0:
            self.logger.write(
                "Filtered {} / {} {} records with {} >= {}".format(
                    removed, data.shape[0], stage or "data", item_col, max_item_id
                ),
                logger_mode,
            )
        if filtered.shape[0] == 0:
            self.logger.write(
                "Warning: {} is empty after filtering by {}".format(stage or "data", item_col),
                logger_mode,
            )
        return filtered

    def forward(
        self,
        user_ids: torch.LongTensor,
        item_ids: torch.LongTensor,
        item_know: torch.Tensor,
        device="cpu",
    ) -> torch.Tensor:
        item_know = item_know.float().to(device)
        user_ids = user_ids.to(device)
        item_ids = item_ids.to(device)

        user_mastery = self.get_posterior(user_ids, device)
        item_diff = torch.sigmoid(self.item_diff(item_ids))
        item_disc = torch.sigmoid(self.item_disc(item_ids))

        user_factor = torch.tanh(self.user_contract(user_mastery * item_know))
        item_factor = torch.sigmoid(self.item_contract(item_diff * item_know))
        output = self.itf(user_factor, item_factor, item_disc)

        return output.clamp(min=1e-6, max=1 - 1e-6)

    def pos_clipper(self, module_list: list):
        for module in module_list:
            module.weight.data = module.weight.clamp_min(0)

    def neg_clipper(self, module_list: list):
        for module in module_list:
            module.weight.data = module.weight.clamp_max(0)

    def _to_device(self, device):
        self.to(device)

    @staticmethod
    def _safe_auc(y_true, y_score):
        if len(np.unique(y_true)) < 2:
            return float("nan")
        return roc_auc_score(y_true, y_score)

    def train(
        self,
        hparams: dict,
        train_data: pd.DataFrame,
        Q_matrix: np.array,
        valid_data: pd.DataFrame = None,
    ):
        lr = hparams.get("lr", 0.01)
        epoch = hparams.get("epoch", 5)
        batch_size = hparams.get("batch_size", 64)
        logger_mode = hparams.get("logger_mode", "both")
        loss_factor = hparams.get("loss_factor", 0.0)
        device = hparams.get("device", "cpu")
        batch_show = hparams.get("batch_show", 200)
        self.max_exercise_id = hparams.get("max_exercise_id", None)

        self.logger.write("Before IdpCDF train.\n{}".format(format_hparams(hparams)), logger_mode)
        self._to_device(device)

        train_data = self._filter_samples_by_item_id(train_data, self.max_exercise_id, logger_mode, "train")
        if train_data.shape[0] == 0:
            raise ValueError("No training samples left after applying max_exercise_id={}".format(self.max_exercise_id))
        if valid_data is not None:
            valid_data = self._filter_samples_by_item_id(valid_data, self.max_exercise_id, logger_mode, "valid")
            if valid_data.shape[0] == 0:
                self.logger.write("Valid data empty after filtering. Skip validation stage.", logger_mode)
                valid_data = None

        loss_fn = MyLoss(self, nn.NLLLoss, loss_factor)
        dataloader = TrainDataLoader(train_data, Q_matrix, batch_size)
        optimizer = torch.optim.Adam(self.parameters(), lr=lr)

        # 记录最佳指标
        best_epoch = -1
        best_auc = 0.0
        best_acc = 0.0
        best_rmse = float('inf')

        for step in range(1, epoch + 1):
            dataloader.reset(shuffle=False)
            y_score_all = np.array([])
            y_label_all = np.array([], dtype=np.int_)
            y_target_all = np.array([], dtype=np.int_)
            loss_all = 0.0
            batch_count = 0

            while not dataloader.is_end():
                optimizer.zero_grad()
                user_ids, item_ids, item_know, y_target = dataloader.next_batch()
                user_ids = user_ids.to(device)
                item_ids = item_ids.to(device)
                item_know = item_know.to(device)
                y_target = y_target.to(device)

                y_pred = self.forward(user_ids, item_ids, item_know, device)
                output_1 = y_pred
                output_0 = torch.ones_like(output_1) - output_1
                output = torch.cat((output_0, output_1), dim=1).clamp(min=1e-6, max=1 - 1e-6)

                loss = loss_fn(torch.log(output), y_target, user_ids, item_ids)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.parameters(), 5.0)
                optimizer.step()

                self.pos_clipper([self.user_contract, self.item_contract, self.cross_layer1, self.cross_layer2])

                y_score_all = np.concatenate([y_score_all, to_numpy(y_pred)], axis=0)
                y_label_all = np.concatenate([y_label_all, labelize(y_pred)], axis=0)
                y_target_all = np.concatenate([y_target_all, y_target.detach().cpu().numpy()], axis=0)
                loss_all += loss.item()

                if batch_count % batch_show == batch_show - 1:
                    self.logger.write(
                        "IdpCDF:"
                        "epoch = {}, batch = {}, loss = {}".format(step, batch_count, loss_all / batch_show),
                        logger_mode,
                    )
                    loss_all = 0.0
                batch_count += 1

            train_acc = accuracy_score(y_target_all, y_label_all)
            train_f1 = f1_score(y_target_all, y_label_all)
            train_auc = self._safe_auc(y_target_all, y_score_all)
            train_mse = mean_squared_error(y_target_all, y_score_all)
            self.logger.write(
                "IdpCDF:"
                "epoch = {}, train_acc = {}, train_f1 = {}, train_auc = {}, train_mse = {}".format(
                    step, train_acc, train_f1, train_auc, train_mse
                ),
                logger_mode,
            )

            # 如果有验证集，计算验证指标并更新最佳值
            if valid_data is not None:
                metrics = self.validate(valid_data, Q_matrix, device, logger_mode)
                auc = metrics['auc']
                acc = metrics['acc']
                rmse = metrics['mse']  # 原 validate 返回的 mse 是均方误差，不是 rmse，这里转换一下
                if 'rmse' not in metrics:
                    rmse = np.sqrt(rmse) if rmse > 0 else 0.0

                if auc > best_auc:
                    best_auc = auc
                    best_acc = acc
                    best_rmse = rmse
                    best_epoch = step

            # 返回最佳指标
        if valid_data is None:
            return None, None, None, None
        else:
            return best_epoch, best_auc, best_acc, best_rmse

    def predict(self, data: pd.DataFrame, Q_matrix: np.array, device="cpu") -> pd.DataFrame:
        data = self._filter_samples_by_item_id(data, self.max_exercise_id, "console", "predict")
        if data is None or data.shape[0] == 0:
            if data is None:
                return pd.DataFrame(columns=["predict_score", "predict_label"])
            empty_df = data.copy()
            empty_df["predict_score"] = pd.Series(dtype=float)
            empty_df["predict_label"] = pd.Series(dtype=float)
            return empty_df

        dataloader = TrainDataLoader(data, Q_matrix, 8192)
        dataloader.reset(shuffle=False)
        df_pred = pd.DataFrame(columns=["predict_score", "predict_label"])
        self._to_device(device)

        with torch.no_grad():
            while not dataloader.is_end():
                user_ids, item_ids, item_know, _ = dataloader.next_batch()
                user_ids = user_ids.to(device)
                item_ids = item_ids.to(device)
                item_know = item_know.to(device)

                z_output = self.forward(user_ids, item_ids, item_know, device=device)
                df_batch = pd.DataFrame(
                    {
                        "predict_score": to_numpy(z_output).reshape(-1),
                        "predict_label": labelize(z_output).reshape(-1),
                    }
                )
                df_pred = pd.concat([df_pred, df_batch], ignore_index=True)

        return data.reset_index(drop=True).join(df_pred.reset_index(drop=True))

    def validate(self, valid_data: pd.DataFrame, Q_matrix: np.array, device, logger_mode):
        valid_pred = self.predict(valid_data, Q_matrix, device)
        z_true = valid_pred["score"].astype(int).tolist()
        z_score = valid_pred["predict_score"].tolist()
        z_label = valid_pred["predict_label"].tolist()

        valid_acc = accuracy_score(z_true, z_label)
        valid_auc = self._safe_auc(z_true, z_score)
        valid_f1 = f1_score(z_true, z_label)
        valid_mse = mean_squared_error(z_true, z_score)

        self.logger.write("IdpCDF:"
                          "valid acc = {}".format(valid_acc), logger_mode)
        self.logger.write("IdpCDF:"
                          "valid f1  = {}".format(valid_f1), logger_mode)
        self.logger.write("IdpCDF:"
                          "valid auc = {}".format(valid_auc), logger_mode)
        self.logger.write("IdpCDF:"
                          "valid mse = {}\n".format(valid_mse), logger_mode)

        metrics_dict = {}
        metrics_dict['acc'] = (valid_acc)
        metrics_dict['f1'] = (valid_f1)
        metrics_dict['auc'] = (valid_auc)
        metrics_dict['mse'] = (valid_mse)

        return metrics_dict

    def save(self, model_name="./model.pkl"):
        path = "/".join(model_name.split("/")[:-1]) + "/"
        if path and not os.path.exists(path):
            os.makedirs(path)
        torch.save(self.state_dict(), model_name)

    def load(self, model_name="./model.pkl", map_location=None):
        self.load_state_dict(torch.load(model_name, map_location=map_location))


class MyLoss(nn.Module):
    def __init__(self, net: IRTCDM, loss_fn: nn.Module, factor=0.0):
        super().__init__()
        self.net = net
        self.factor = factor
        self.loss_fn = loss_fn()

    def forward(self, y_pred, y_target, user_ids=None, item_ids=None):
        loss = self.loss_fn(y_pred, y_target)
        if self.factor <= 0 or user_ids is None or item_ids is None:
            return loss

        reg = (
            self.net.user_mastery(user_ids).pow(2).mean()
            + self.net.item_diff(item_ids).pow(2).mean()
            + self.net.item_disc(item_ids).pow(2).mean()
        )
        return loss + self.factor * reg


def _find_existing_file(data_path: str, candidates):
    for filename in candidates:
        file_path = osp.join(data_path, filename)
        if osp.exists(file_path):
            return file_path
    raise FileNotFoundError("Cannot find any file in {} from candidates {}".format(data_path, candidates))
