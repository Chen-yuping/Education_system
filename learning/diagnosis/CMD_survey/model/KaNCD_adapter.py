import logging
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import sys
from .KaNCD import KaNCD

class KaNCD_Adapter:
    '''KaNCD适配器 - 使KaNCD模型能够接受与其他模型相同格式的json数据'''

    def __init__(self, knowledge_n, exer_n, student_n, dim=20, mf_type='gmf'):
        self.knowledge_n = knowledge_n
        self.exer_n = exer_n
        self.student_n = student_n
        self.dim = dim
        self.mf_type = mf_type
        # 初始化原始KaNCD模型
        self.kancd = KaNCD(exer_n=exer_n, student_n=student_n, knowledge_n=knowledge_n, 
                           dim=dim, mf_type=mf_type)

    def train(self, train_data, test_data=None, epoch=100, device="cpu", lr=0.002, silence=False):
        """与其他CDM模型兼容的训练接口"""
        logging.info(f"Training KaNCD model with {self.mf_type} type...")
        self.kancd.net = self.kancd.net.to(device)
        self.kancd.net.train()
        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.kancd.net.parameters(), lr=lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        best_f1 = 0.
        rmse1 = 1.

        for epoch_i in range(epoch):
            epoch_losses = []
            batch_count = 0
            for batch_data in tqdm(train_data, f"Epoch {epoch_i}", file=sys.stdout):
                batch_count += 1
                user_id, item_id, knowledge_emb, y = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                knowledge_emb: torch.Tensor = knowledge_emb.to(device)
                y: torch.Tensor = y.to(device)
                
                pred = self.kancd.net(user_id, item_id, knowledge_emb)
                loss = loss_function(pred, y)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_losses.append(loss.mean().item())

            print(f"[Epoch {epoch_i}] average loss: {float(np.mean(epoch_losses)):.6f}")

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print(f"[Epoch {epoch_i}] auc: {auc:.6f}, accuracy: {accuracy:.6f}, rmse: {rmse:.6f}, f1: {f1:.6f}")
                if auc > best_auc:
                    best_epoch = epoch_i
                    best_auc = auc
                    acc1 = accuracy
                    best_f1 = f1
                    rmse1 = rmse
            print(f'BEST epoch<{best_epoch}>, auc: {best_auc}, acc: {acc1}, rmse: {rmse1:.6f}, f1: {best_f1:.6f}')
        return best_epoch, best_auc, acc1

    def eval(self, test_data, device="cpu"):
        """与其他CDM模型兼容的评估接口"""
        self.kancd.net = self.kancd.net.to(device)
        self.kancd.net.eval()
        y_true, y_pred = [], []
        for batch_data in tqdm(test_data, "Evaluating", file=sys.stdout):
            user_id, item_id, knowledge_emb, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            knowledge_emb: torch.Tensor = knowledge_emb.to(device)
            pred: torch.Tensor = self.kancd.net(user_id, item_id, knowledge_emb)

            y_pred.extend(pred.detach().cpu().tolist())
            y_true.extend(y.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))

        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        """保存模型参数"""
        self.kancd.save(filepath)

    def load(self, filepath):
        """加载模型参数"""
        self.kancd.load(filepath) 