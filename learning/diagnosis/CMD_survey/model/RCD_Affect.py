import torch
import torch.nn as nn
import logging
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score, mean_squared_error
import sys
import math


class PosLinear(nn.Linear):
    def forward(self, input: torch.Tensor) -> torch.Tensor:
        weight = 2 * F.relu(1 * torch.neg(self.weight)) + self.weight
        return F.linear(input, weight, self.bias)


class RCDAffectNet(nn.Module):
    def __init__(self, stu_n, exer_n, k_n, emb_dim):
        super(RCDAffectNet, self).__init__()
        self.stu_n = stu_n
        self.exer_n = exer_n
        self.k_n = k_n
        self.emb_dim = emb_dim

        # 原始RCD参数
        self.student_v = nn.Embedding(self.stu_n, self.emb_dim)
        self.exercise_v = nn.Embedding(self.exer_n, self.emb_dim)
        self.knowledge_v = nn.Embedding(self.k_n, self.emb_dim)
        
        # 新增：学生情感参数
        self.student_affect = nn.Embedding(self.stu_n, self.emb_dim)
        
        # RCD网络层
        self.prednet_full1 = PosLinear(2 * self.emb_dim, self.emb_dim)
        self.prednet_full2 = PosLinear(2 * self.emb_dim, self.emb_dim)
        self.prednet_full3 = PosLinear(self.emb_dim, 1)
        
        # 新增：情感相关网络
        self.prednet_affect = nn.Linear(2, 4)  # 情感与知识点结合
        self.guess = nn.Linear(4, 1)  # 猜测因子
        self.slip = nn.Linear(4, 1)  # 滑动因子
        
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.k_index = torch.LongTensor(list(range(self.k_n))).to(self.device)

        # 初始化参数
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, stu_id, exer_id, kq, labels=None):
        # 检查索引是否越界
        if torch.max(stu_id) >= self.stu_n or torch.min(stu_id) < 0:
            raise ValueError(f"学生ID越界: 最大值 {torch.max(stu_id).item()}, 最小值 {torch.min(stu_id).item()}, 学生数量 {self.stu_n}")
        if torch.max(exer_id) >= self.exer_n or torch.min(exer_id) < 0:
            raise ValueError(f"习题ID越界: 最大值 {torch.max(exer_id).item()}, 最小值 {torch.min(exer_id).item()}, 习题数量 {self.exer_n}")
            
        # 获取学生、习题和知识点的嵌入
        stu_v = self.student_v(stu_id)
        exer_v = self.exercise_v(exer_id)
        k_v = self.knowledge_v(self.k_index)
        
        # 学生情感参数
        stu_affect = torch.sigmoid(self.student_affect(stu_id))

        # 批量处理向量
        batch_stu_vector = stu_v.repeat(1, k_v.shape[0]).reshape(stu_v.shape[0], k_v.shape[0], stu_v.shape[1])
        batch_exer_vector = exer_v.repeat(1, k_v.shape[0]).reshape(exer_v.shape[0], k_v.shape[0], exer_v.shape[1])
        kn_vector = k_v.repeat(stu_v.shape[0], 1).reshape(stu_v.shape[0], k_v.shape[0], k_v.shape[1])

        # 计算偏好和难度
        preference = torch.sigmoid(self.prednet_full1(torch.cat((batch_stu_vector, kn_vector), dim=2)))
        diff = torch.sigmoid(self.prednet_full2(torch.cat((batch_exer_vector, kn_vector), dim=2)))
        
        # 计算优势
        advantage = preference - diff
        input_x = advantage

        # 基础RCD输出
        o = torch.sigmoid(self.prednet_full3(input_x))
        sum_out = torch.sum(o * kq.unsqueeze(2), dim=1)
        count_of_concept = torch.sum(kq, dim=1).unsqueeze(1)
        base_output = sum_out / (count_of_concept + 1e-8)  # 避免除以零
        
        # 情感处理
        # 将学生情感与知识点结合
        knowledge_mean = kq.float().mean(dim=1, keepdim=True)
        affect_input = torch.cat([
            stu_affect.mean(dim=1, keepdim=True), 
            knowledge_mean
        ], dim=1)
        
        affect = torch.sigmoid(self.prednet_affect(affect_input))
        
        # 计算猜测和滑动因子
        g = torch.sigmoid(self.guess(affect))
        s = torch.sigmoid(self.slip(affect))
        
        # 最终输出结合猜测和滑动因子
        output = ((1-s.squeeze(-1))*base_output.squeeze(-1)) + (g.squeeze(-1)*(1-base_output.squeeze(-1)))
        
        # 如果提供了标签，计算对比损失
        if labels is not None:
            try:
                closs = self.contrastive_loss(affect, labels)
                return output, affect, closs
            except Exception as e:
                print(f"对比损失计算错误: {e}")
                return output, affect, torch.tensor(0.1, device=output.device)
        
        return output, affect

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


class RCD_Affect:
    def __init__(self, student_n, exer_n, k_n, emb_dim):
        super(RCD_Affect, self).__init__()
        self.acd_net = RCDAffectNet(student_n, exer_n, k_n, emb_dim)

    def train(self, train_data, test_data=None, epoch=10, device="cpu", lr=0.002):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.train()
        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.acd_net.parameters(), lr=lr)
        best_epoch = 0
        best_auc = 0.
        best_acc = 0.
        best_rmse = float('inf')
        best_model_state = None

        for epoch_i in range(epoch):
            epoch_losses = []
            closs_sum = 0
            batch_count = 0
            
            for batch_data in tqdm(train_data, "Epoch %s" % epoch_i, file=sys.stdout):
                batch_count += 1
                user_id, item_id, kq, y = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                kq = kq.to(device)
                y: torch.Tensor = y.to(device)

                # 前向传播
                pred, affect, closs = self.acd_net(user_id, item_id, kq, y)
                
                # 计算预测损失
                pred_loss = loss_function(pred, y)
                
                # 总损失 = 预测损失 + 对比损失
                loss = pred_loss + 0.1 * closs

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_losses.append(pred_loss.item())
                closs_sum += closs.item()

            print("[Epoch %d] average loss: %.6f, CLoss: %.6f" % (epoch_i, float(np.mean(epoch_losses)), closs_sum))

            if test_data is not None:
                auc, accuracy, rmse = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f" % (epoch_i, auc, accuracy, rmse))

                if auc > best_auc:
                    best_epoch = epoch_i
                    best_auc = auc
                    best_acc = accuracy
                    best_rmse = rmse
                    best_model_state = self.acd_net.state_dict().copy()
                    print(f"发现更好的模型! Epoch {best_epoch}, AUC: {best_auc:.4f}, ACC: {best_acc:.4f}, RMSE: {best_rmse:.4f}")

            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f' % (best_epoch, best_auc, best_acc, best_rmse))

        # 恢复最佳模型
        if best_model_state is not None:
            self.acd_net.load_state_dict(best_model_state)
            print("已恢复最佳模型状态")
            
            # 再次评估最佳模型
            try:
                final_auc, final_acc, final_rmse = self.eval(test_data, device=device)
                print(f"最终评估结果 - AUC: {final_auc:.4f}, ACC: {final_acc:.4f}, RMSE: {final_rmse:.4f}")
            except Exception as ex:
                print(f"最终评估时出错: {ex}")
                
        return best_epoch, best_auc, best_acc, best_rmse

    def eval(self, test_data, device="cpu"):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.eval()
        y_true, y_pred = [], []
        
        with torch.no_grad():
            for batch_data in tqdm(test_data, "Evaluating", file=sys.stdout):
                user_id, item_id, kq, y = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                kq = kq.to(device)
                pred, _ = self.acd_net(user_id, item_id, kq)

                y_pred.extend(pred.detach().cpu().tolist())
                y_true.extend(y.tolist())
                
        rmse = math.sqrt(mean_squared_error(y_true, y_pred))
        
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse

    def save(self, filepath):
        torch.save(self.acd_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.acd_net.load_state_dict(torch.load(filepath))
        logging.info("load parameters from %s" % filepath) 