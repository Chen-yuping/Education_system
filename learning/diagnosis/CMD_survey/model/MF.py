import logging
import numpy as np
import torch
from torch import nn
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import torch.autograd as autograd
import torch.nn.functional as F
import sys


class MFNet(nn.Module):
    def __init__(self, user_num, item_num, hidden_dim, strategy_num=2, max_slip=0.4, max_guess=0.4, *args, **kwargs):
        super(MFNet, self).__init__()
        self._user_num = user_num
        self._item_num = item_num
        self._strategy_num = strategy_num
        self.step = 0
        self.max_step = 1000
        self.max_slip = max_slip
        self.max_guess = max_guess

        # 每个题目的猜测和滑动参数
        self.guess = nn.Embedding(self._item_num, 1)
        self.slip = nn.Embedding(self._item_num, 1)
        
        # 学生能力参数
        self.theta = nn.Embedding(self._user_num, hidden_dim)
        
        # 策略选择概率
        self.strategy_weights = nn.Embedding(self._item_num, strategy_num)
        
        # 每种策略的知识点要求矩阵 (item_num, strategy_num, hidden_dim)
        self.strategy_q_matrix = nn.Parameter(torch.randn(self._item_num, strategy_num, hidden_dim) * 0.01)

    def forward(self, user, item, knowledge, *args):
        batch_size = user.size(0)
        theta = self.theta(user)  # (batch_size, hidden_dim)
        slip = torch.squeeze(torch.sigmoid(self.slip(item)) * self.max_slip)  # (batch_size,)
        guess = torch.squeeze(torch.sigmoid(self.guess(item)) * self.max_guess)  # (batch_size,)
        
        # 获取策略选择概率
        strategy_probs = F.softmax(self.strategy_weights(item), dim=1)  # (batch_size, strategy_num)
        
        # 获取每个题目的策略-知识点矩阵，并应用sigmoid
        item_indices = item.unsqueeze(-1).unsqueeze(-1).expand(-1, self._strategy_num, theta.size(-1))
        q_matrices_raw = torch.gather(self.strategy_q_matrix, 0, item_indices)  # (batch_size, strategy_num, hidden_dim)
        q_matrices = torch.sigmoid(q_matrices_raw)  # 使用torch.sigmoid而不是nn.Sigmoid
        
        if self.training:
            # 训练阶段使用软掩码和退火
            mastery_per_strategy = []
            for s in range(self._strategy_num):
                # 对每个策略，计算学生在该策略所需知识点上的掌握程度
                strategy_q = q_matrices[:, s, :]  # (batch_size, hidden_dim)
                n = torch.sum(knowledge * strategy_q * (torch.sigmoid(theta) - 0.5), dim=1)  # (batch_size,)
                mastery_per_strategy.append(n)
            
            mastery_tensor = torch.stack(mastery_per_strategy, dim=1)  # (batch_size, strategy_num)
            
            # 使用退火机制
            t, self.step = max((np.sin(2 * np.pi * self.step / self.max_step) + 1) / 2 * 100, 
                              1e-6), self.step + 1 if self.step < self.max_step else 0
            
            # 对每个策略计算正确率
            correct_probs = torch.zeros_like(mastery_tensor)
            for s in range(self._strategy_num):
                n = mastery_tensor[:, s]
                correct_probs[:, s] = torch.sum(
                    torch.stack([1 - slip, guess]).T * torch.softmax(torch.stack([n, torch.zeros_like(n)]).T / t, dim=-1),
                    dim=1
                )
            
            # 根据策略选择概率加权平均
            return torch.sum(strategy_probs * correct_probs, dim=1)
        else:
            # 测试阶段使用硬掩码
            correct_probs = torch.zeros(batch_size, self._strategy_num, device=user.device)
            
            for s in range(self._strategy_num):
                strategy_q = q_matrices[:, s, :]  # (batch_size, hidden_dim)
                # 对每个策略，计算学生是否掌握所有必要知识点
                n = torch.prod(knowledge * (strategy_q >= 0.5) * (theta >= 0) + (1 - knowledge * (strategy_q >= 0.5)), dim=1)
                correct_probs[:, s] = (1 - slip) ** n * guess ** (1 - n)
            
            # 选择最大概率的策略（学生会选择最有可能成功的策略）
            return torch.max(correct_probs, dim=1)[0]


class STEMF(MFNet):
    """使用Straight-Through Estimator的MF模型"""
    def __init__(self, user_num, item_num, hidden_dim, strategy_num=2, max_slip=0.4, max_guess=0.4, *args, **kwargs):
        super(STEMF, self).__init__(user_num, item_num, hidden_dim, strategy_num, max_slip, max_guess, *args, **kwargs)
        self.sign = StraightThroughEstimator()

    def forward(self, user, item, knowledge, *args):
        batch_size = user.size(0)
        theta = self.sign(self.theta(user))  # 使用STE进行二值化
        slip = torch.squeeze(torch.sigmoid(self.slip(item)) * self.max_slip)
        guess = torch.squeeze(torch.sigmoid(self.guess(item)) * self.max_guess)
        
        # 获取策略选择概率
        strategy_probs = F.softmax(self.strategy_weights(item), dim=1)
        
        # 获取每个题目的策略-知识点矩阵，并应用sigmoid
        item_indices = item.unsqueeze(-1).unsqueeze(-1).expand(-1, self._strategy_num, theta.size(-1))
        q_matrices_raw = torch.gather(self.strategy_q_matrix, 0, item_indices)
        q_matrices = torch.sigmoid(q_matrices_raw)  # 使用torch.sigmoid
        
        # 对每个策略计算正确率
        correct_probs = torch.zeros(batch_size, self._strategy_num, device=user.device)
        
        for s in range(self._strategy_num):
            strategy_q = q_matrices[:, s, :]
            # 对每个策略，计算学生是否掌握所有必要知识点
            mask_theta = (knowledge == 0) + (knowledge == 1) * (strategy_q >= 0.5) * theta
            n = torch.prod((mask_theta + 1) / 2, dim=-1)
            correct_probs[:, s] = torch.pow(1 - slip, n) * torch.pow(guess, 1 - n)
        
        # 根据策略选择概率加权平均或选择最大概率
        if self.training:
            return torch.sum(strategy_probs * correct_probs, dim=1)
        else:
            return torch.max(correct_probs, dim=1)[0]


class StraightThroughEstimator(nn.Module):
    def __init__(self):
        super(StraightThroughEstimator, self).__init__()

    def forward(self, x):
        return STEFunction.apply(x)


class STEFunction(autograd.Function):
    @staticmethod
    def forward(ctx, input):
        return (input > 0).float()

    @staticmethod
    def backward(ctx, grad_output):
        return F.hardtanh(grad_output)


class MF:
    def __init__(self, user_num, item_num, hidden_dim, strategy_num=2, ste=False):
        super(MF, self).__init__()
        if ste:
            self.mf_net = STEMF(user_num, item_num, hidden_dim, strategy_num)
        else:
            self.mf_net = MFNet(user_num, item_num, hidden_dim, strategy_num)

    def train(self, train_data, test_data=None, *, epoch: int, device="cpu", lr=0.001) -> ...:
        self.mf_net = self.mf_net.to(device)
        loss_function = nn.BCELoss()

        trainer = torch.optim.Adam(self.mf_net.parameters(), lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        best_f1 = 0.
        rmse1 = 1.

        for e in range(epoch):
            losses = []
            for batch_data in tqdm(train_data, "Epoch %s" % e, file=sys.stdout):
                user_id, item_id, knowledge, response = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                knowledge: torch.Tensor = knowledge.to(device)
                predicted_response: torch.Tensor = self.mf_net(user_id, item_id, knowledge)
                response: torch.Tensor = response.to(device)
                loss = loss_function(predicted_response, response)

                # back propagation
                trainer.zero_grad()
                loss.backward()
                trainer.step()

                losses.append(loss.mean().item())
            print("[Epoch %d] LogisticLoss: %.6f" % (e, float(np.mean(losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (e, auc, accuracy, rmse, f1))
                if auc > best_auc:
                    best_epoch = e
                    best_auc = auc
                    acc1 = accuracy
                    best_f1 = f1
                    rmse1=rmse

                    # self.save("params/mf.params")
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))
        return best_epoch, best_auc, acc1

    def eval(self, test_data, device="cpu") -> tuple:
        self.mf_net = self.mf_net.to(device)
        self.mf_net.eval()
        y_pred = []
        y_true = []
        for batch_data in tqdm(test_data, "evaluating", file=sys.stdout):
            user_id, item_id, knowledge, response = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            knowledge: torch.Tensor = knowledge.to(device)
            pred: torch.Tensor = self.mf_net(user_id, item_id, knowledge)
            y_pred.extend(pred.tolist())
            y_true.extend(response.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))

        self.mf_net.train()
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        torch.save(self.mf_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.mf_net.load_state_dict(torch.load(filepath))
        logging.info("load parameters from %s" % filepath) 