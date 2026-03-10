import logging
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import time
import sys


def irf(theta, a, b, c, D=1.702, *, F=np):
    """
    IRT 项目反应函数 - 支持 1-PL, 2-PL, 3-PL
    通过注释选择使用哪个模型，只保留一个 return 语句生效
    
    Args:
        theta: 学生能力参数
        a: 题目区分度参数（1-PL 不使用）
        b: 题目难度参数
        c: 猜测参数（1-PL 和 2-PL 不使用）
        D: 缩放常数，默认 1.702
        F: 数值计算库 (np 或 torch)
    """
    
    # ============ 选择模型类型（注释掉不需要的，保留需要的）============
    
    # 3-PL: 三参数 Logistic 模型（包含猜测参数 c）
    # p(y=1|θ,a,b,c) = c + (1-c) / (1 + exp(-D*a*(θ-b)))
    # return c + (1 - c) / (1 + F.exp(-D * a * (theta - b)))
    
    # 2-PL: 二参数 Logistic 模型（包含区分度 a）
    # p(y=1|θ,a,b) = 1 / (1 + exp(-D*a*(θ-b)))
    # return 1 / (1 + F.exp(-D * a * (theta - b)))
    
    # 1-PL (Rasch Model): 一参数 Logistic 模型（区分度固定为 1）
    # p(y=1|θ,b) = 1 / (1 + exp(-D*(θ-b)))
    return 1 / (1 + F.exp(-D * (theta - b)))

irt3pl = irf
irt2pl = irf
irt1pl = irf

class IRTNet(nn.Module):
    def __init__(self, user_num, item_num, value_range, a_range, irf_kwargs=None):
        """
        IRT 网络 - 支持 1-PL, 2-PL, 3-PL
        具体模型类型通过 irf 函数中的注释选择
        
        Args:
            user_num: 用户数量
            item_num: 题目数量
            value_range: theta 和 b 的值范围
            a_range: a 的值范围
            irf_kwargs: IRF 函数的额外参数
        """
        super(IRTNet, self).__init__()
        self.user_num = user_num
        self.item_num = item_num
        self.irf_kwargs = irf_kwargs if irf_kwargs is not None else {}
        self.value_range = value_range
        self.a_range = a_range
        
        # 所有参数（即使是 1-PL 也定义，只是不会使用）
        self.theta = nn.Embedding(self.user_num, 1)  # 能力参数
        self.a = nn.Embedding(self.item_num, 1)      # 区分度参数
        self.b = nn.Embedding(self.item_num, 1)      # 难度参数
        self.c = nn.Embedding(self.item_num, 1)      # 猜测参数

    def forward(self, user, item):
        theta = torch.squeeze(self.theta(user), dim=-1)
        a = torch.squeeze(self.a(item), dim=-1)
        b = torch.squeeze(self.b(item), dim=-1)
        c = torch.squeeze(self.c(item), dim=-1)
        c = torch.sigmoid(c)
        
        # 应用值范围约束
        if self.value_range is not None:
            theta = self.value_range * (torch.sigmoid(theta) - 0.5)
            b = self.value_range * (torch.sigmoid(b) - 0.5)
        if self.a_range is not None:
            a = self.a_range * torch.sigmoid(a)
        else:
            a = F.softplus(a)
        
        if torch.max(theta != theta) or torch.max(a != a) or torch.max(b != b):
            raise ValueError('ValueError:theta,a,b may contains nan!  The value_range or a_range is too large.')
        
        # 调用 irf 函数（模型选择在 irf 函数内部通过注释完成）
        return self.irf(theta, a, b, c, **self.irf_kwargs)

    @classmethod
    def irf(cls, theta, a, b, c, **kwargs):
        """调用全局的 irf 函数"""
        return irf(theta, a, b, c, F=torch, **kwargs)


class IRT:
    """
    IRT 模型类 - 支持 1-PL, 2-PL, 3-PL
    
    模型选择：在 model/IRT.py 的 irf 函数中注释/取消注释对应的 return 语句
    
    使用方法：
        model = IRT(user_num, item_num, value_range=4.0, a_range=2.0)
    """
    def __init__(self, user_num, item_num, value_range=None, a_range=None):
        super(IRT, self).__init__()
        self.irt_net = IRTNet(user_num, item_num, value_range, a_range)

    def train(self, train_data, test_data=None, *, epoch: int, device="cpu", lr=0.001) -> ...:
        self.irt_net = self.irt_net.to(device)
        loss_function = nn.BCELoss()

        trainer = torch.optim.Adam(self.irt_net.parameters(), lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        best_f1 = 0.
        rmse1 = 1.

        for e in range(epoch):
            losses = []
            for batch_data in tqdm(train_data, "Epoch %s" % e, file=sys.stdout):
                user_id, item_id, _, response = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                predicted_response: torch.Tensor = self.irt_net(user_id, item_id)
                response: torch.Tensor = response.to(device)
                loss = loss_function(predicted_response, response)

                # back propagation
                trainer.zero_grad()
                loss.backward()
                trainer.step()

                losses.append(loss.mean().item())
            print("LogisticLoss: %.6f" % float(np.mean(losses)))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (e, auc, accuracy, rmse, f1))
                if auc > best_auc:
                    best_epoch = e
                    best_auc = auc
                    acc1 = accuracy
                    best_f1 = f1
                    rmse1=rmse
                    # self.save("params/irt.params")
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))
        return best_epoch, best_auc, acc1

    def eval(self, test_data, device="cpu") -> tuple:
        self.irt_net = self.irt_net.to(device)
        self.irt_net.eval()
        y_pred = []
        y_true = []
        for batch_data in tqdm(test_data, "evaluating", file=sys.stdout):
            user_id, item_id, _, response = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            pred: torch.Tensor = self.irt_net(user_id, item_id)
            y_pred.extend(pred.tolist())
            y_true.extend(response.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))

        self.irt_net.train()
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        torch.save(self.irt_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.irt_net.load_state_dict(torch.load(filepath))
        logging.info("load parameters from %s" % filepath)
