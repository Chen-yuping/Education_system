import logging
import numpy as np
import torch
from torch import nn
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score, mean_squared_error
import torch.autograd as autograd
import torch.nn.functional as F
import sys
import math


class DINAAffectNet(nn.Module):
    def __init__(self, user_num, item_num, hidden_dim, max_slip=0.4, max_guess=0.4, *args, **kwargs):
        super(DINAAffectNet, self).__init__()
        self._user_num = user_num
        self._item_num = item_num
        self.step = 0
        self.max_step = 1000
        self.max_slip = max_slip
        self.max_guess = max_guess
        self.hidden_dim = hidden_dim

        # 原始DINA参数
        self.theta = nn.Embedding(self._user_num, hidden_dim)
        
        # 新增：学生情感参数
        self.student_affect = nn.Embedding(self._user_num, hidden_dim)
        
        # 新增：情感相关网络
        self.prednet_affect = nn.Linear(2, 4)  # 情感与难度结合
        self.guess_net = nn.Linear(4, 1)  # 猜测因子网络
        self.slip_net = nn.Linear(4, 1)  # 滑动因子网络
        
        # 初始化参数
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, user, item, knowledge, labels=None):
        # 检查索引是否越界
        if torch.max(user) >= self._user_num or torch.min(user) < 0:
            print(f"警告: 用户ID越界: 最大值 {torch.max(user).item()}, 最小值 {torch.min(user).item()}, 用户数量 {self._user_num}")
            # 将超出范围的ID限制在有效范围内
            user = torch.clamp(user, 0, self._user_num - 1)
        if torch.max(item) >= self._item_num or torch.min(item) < 0:
            print(f"警告: 题目ID越界: 最大值 {torch.max(item).item()}, 最小值 {torch.min(item).item()}, 题目数量 {self._item_num}")
            # 将超出范围的ID限制在有效范围内
            item = torch.clamp(item, 0, self._item_num - 1)
            
        theta = self.theta(user)  # 每个user均hidden_dim长，并非一定k长
        
        # 学生情感参数
        stu_affect = torch.sigmoid(self.student_affect(user))
        
        # 将知识点与情感结合
        knowledge_mean = knowledge.float().mean(dim=1, keepdim=True)
        affect_input = torch.cat([
            stu_affect.mean(dim=1, keepdim=True),
            knowledge_mean
        ], dim=1)
        
        affect = torch.sigmoid(self.prednet_affect(affect_input))
        
        # 通过情感网络计算猜测和滑动因子
        g_affect = torch.sigmoid(self.guess_net(affect))
        s_affect = torch.sigmoid(self.slip_net(affect))
        
        # 限制猜测和滑动因子的范围
        guess = g_affect * self.max_guess
        slip = s_affect * self.max_slip
        
        if self.training:
            # 训练模式
            n = torch.sum(knowledge * (torch.sigmoid(theta) - 0.5), dim=1)  # 考虑Q后的平均能力
            t, self.step = max((np.sin(2 * np.pi * self.step / self.max_step) + 1) / 2 * 100,  # 像是退火
                               1e-6), self.step + 1 if self.step < self.max_step else 0
            
            # 使用softmax计算概率
            probs = torch.softmax(torch.stack([n, torch.zeros_like(n)]).T / t, dim=-1)
            
            # 基础DINA输出
            o = torch.sum(torch.stack([1 - slip.squeeze(-1), guess.squeeze(-1)]).T * probs, dim=1)
            
            # 如果提供了标签，计算对比损失
            if labels is not None:
                try:
                    closs = self.contrastive_loss(affect, labels)
                    return o, affect, closs
                except Exception as e:
                    print(f"对比损失计算错误: {e}")
                    return o, affect, torch.tensor(0.1, device=o.device)
            
            return o, affect
        else:
            # 评估模式
            n = torch.prod(knowledge * (theta >= 0) + (1 - knowledge), dim=1)
            
            # 基础DINA输出
            o = (1 - slip.squeeze(-1)) ** n * guess.squeeze(-1) ** (1 - n)
            
            return o, affect

    def contrastive_loss(self, affect, label):
        t = 0.1
        batch_size = affect.shape[0]
        
        # 如果批次大小为1，无法计算对比损失
        if batch_size <= 1:
            return torch.tensor(0.1, device=affect.device)
            
        try:
            # 计算特征之间的余弦相似度
            similarity_matrix = F.cosine_similarity(affect.unsqueeze(1), affect.unsqueeze(0), dim=2)
            
            # 创建正样本掩码（相同标签）
            mask_positive = torch.ones_like(similarity_matrix) * (label.expand(batch_size, batch_size).eq(label.expand(batch_size, batch_size).t()))
            mask_negative = torch.ones_like(mask_positive) - mask_positive
            
            # 创建对角线掩码（排除自身）
            mask_0 = torch.ones(batch_size, batch_size, device=affect.device) - torch.eye(batch_size, batch_size, device=affect.device)
            
            # 应用温度系数
            similarity_matrix = torch.exp(similarity_matrix/t)
            similarity_matrix = similarity_matrix * mask_0
            
            # 计算正样本相似度
            positives = mask_positive*similarity_matrix
            
            # 检查正例是否存在
            if torch.sum(positives) == 0:
                return torch.tensor(0.1, device=affect.device)
                
            # 计算负样本相似度
            negatives = similarity_matrix - positives
            negatives_sum = torch.sum(negatives, dim=1)
            negatives_sum_expend = negatives_sum.repeat(batch_size, 1).T
            positives_sum = positives + negatives_sum_expend
            
            # 避免除以零
            epsilon = 1e-8
            loss = torch.div(positives, positives_sum + epsilon)
            loss = loss + mask_negative + torch.eye(batch_size, batch_size, device=loss.device)
            loss = -torch.log(loss + epsilon)
            
            # 计算非零元素的平均损失
            non_zero_count = torch.nonzero(loss).size(0)
            if non_zero_count > 0:
                loss = torch.sum(torch.sum(loss, dim=1)) / non_zero_count
            else:
                loss = torch.tensor(0.1, device=affect.device)
                
            return loss
        except Exception as e:
            print(f"对比损失计算中出现异常: {e}")
            return torch.tensor(0.1, device=affect.device)


class DINA_Affect:
    def __init__(self, user_num, item_num, hidden_dim):
        super(DINA_Affect, self).__init__()
        self.dina_net = DINAAffectNet(user_num, item_num, hidden_dim)

    def train(self, train_data, test_data=None, *, epoch: int, device="cpu", lr=0.001) -> ...:
        self.dina_net = self.dina_net.to(device)
        loss_function = nn.BCELoss()

        trainer = torch.optim.Adam(self.dina_net.parameters(), lr)
        best_epoch = 0
        best_auc = 0.
        best_acc = 0.
        best_rmse = float('inf')
        best_model_state = None

        for e in range(epoch):
            losses = []
            closs_sum = 0
            self.dina_net.train()
            
            for batch_data in tqdm(train_data, "Epoch %s" % e, file=sys.stdout):
                user_id, item_id, knowledge, response = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                knowledge: torch.Tensor = knowledge.to(device)
                response: torch.Tensor = response.to(device)
                
                # 前向传播
                predicted_response, affect, closs = self.dina_net(user_id, item_id, knowledge, response)
                
                # 计算预测损失
                pred_loss = loss_function(predicted_response, response)
                
                # 总损失 = 预测损失 + 对比损失
                loss = pred_loss + 0.1 * closs

                # 反向传播
                trainer.zero_grad()
                loss.backward()
                trainer.step()

                losses.append(pred_loss.mean().item())
                closs_sum += closs.item()
                
            print("[Epoch %d] LogisticLoss: %.6f, CLoss: %.6f" % (e, float(np.mean(losses)), closs_sum))

            if test_data is not None:
                auc, accuracy, rmse = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f" % (e, auc, accuracy, rmse))
                
                if auc > best_auc:
                    best_epoch = e
                    best_auc = auc
                    best_acc = accuracy
                    best_rmse = rmse
                    best_model_state = self.dina_net.state_dict().copy()
                    print(f"发现更好的模型! Epoch {best_epoch}, AUC: {best_auc:.4f}, ACC: {best_acc:.4f}, RMSE: {best_rmse:.4f}")
                    
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f' % (best_epoch, best_auc, best_acc, best_rmse))
        
        # 恢复最佳模型
        if best_model_state is not None:
            self.dina_net.load_state_dict(best_model_state)
            print("已恢复最佳模型状态")
            
            # 再次评估最佳模型
            try:
                final_auc, final_acc, final_rmse = self.eval(test_data, device=device)
                print(f"最终评估结果 - AUC: {final_auc:.4f}, ACC: {final_acc:.4f}, RMSE: {final_rmse:.4f}")
            except Exception as ex:
                print(f"最终评估时出错: {ex}")
                
        return best_epoch, best_auc, best_acc, best_rmse

    def eval(self, test_data, device="cpu") -> tuple:
        self.dina_net = self.dina_net.to(device)
        self.dina_net.eval()
        y_pred = []
        y_true = []
        
        with torch.no_grad():
            for batch_data in tqdm(test_data, "evaluating", file=sys.stdout):
                user_id, item_id, knowledge, response = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                knowledge: torch.Tensor = knowledge.to(device)
                pred, _ = self.dina_net(user_id, item_id, knowledge)
                y_pred.extend(pred.tolist())
                y_true.extend(response.tolist())
                
        rmse = math.sqrt(mean_squared_error(y_true, y_pred))
        
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse

    def save(self, filepath):
        torch.save(self.dina_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.dina_net.load_state_dict(torch.load(filepath))
        logging.info("load parameters from %s" % filepath) 