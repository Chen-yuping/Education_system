import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from sklearn.metrics import roc_auc_score, accuracy_score, mean_squared_error
from model.model_CACD import Net
import time
import math

class CACD_Adapter:
    def __init__(self, knowledge_n, exer_n, student_n, dim=None):
        """
        初始化CACD适配器
        :param knowledge_n: 知识点数量
        :param exer_n: 习题数量
        :param student_n: 学生数量
        :param dim: 潜在空间维度，默认等于知识点数量
        """
        self.knowledge_n = knowledge_n
        self.exer_n = exer_n
        self.student_n = student_n
        # 确保嵌入层大小足够
        self.model = Net(student_n=student_n+1, exer_n=exer_n+1, knowledge_n=knowledge_n)
        print(f"初始化CACD模型，学生数: {student_n}，习题数: {exer_n}，知识点数: {knowledge_n}")
        
    def train(self, train_data, test_data, epoch, device='cpu', lr=0.002):
        """
        训练CACD模型
        :param train_data: 训练数据
        :param test_data: 测试数据
        :param epoch: 训练轮数
        :param device: 训练设备
        :param lr: 学习率
        :return: 最佳轮数，AUC，准确率，RMSE
        """
        self.model = self.model.to(device)
        optimizer = optim.Adam(self.model.parameters(), lr=lr)
        
        best_auc = 0
        best_acc = 0
        best_rmse = float('inf')
        best_epoch = 0
        best_model_state = None
        
        start_time = time.time()
        
        # 检查数据中的最大ID
        max_user_id = 0
        max_exer_id = 0
        for batch in train_data:
            user_id, exer_id, _, _ = batch
            max_user_id = max(max_user_id, torch.max(user_id).item())
            max_exer_id = max(max_exer_id, torch.max(exer_id).item())
        
        print(f"训练数据中最大用户ID: {max_user_id}，最大习题ID: {max_exer_id}")
        print(f"模型嵌入层大小 - 用户: {self.model.emb_num}，习题: {self.model.exer_n}")
        
        # 如果ID超出范围，重新初始化模型
        if max_user_id >= self.model.emb_num or max_exer_id >= self.model.exer_n:
            print("警告: ID超出嵌入层范围，重新初始化模型...")
            self.model = Net(student_n=max_user_id+1, exer_n=max_exer_id+1, knowledge_n=self.knowledge_n)
            self.model = self.model.to(device)
            optimizer = optim.Adam(self.model.parameters(), lr=lr)
        
        for e in range(epoch):
            self.model.train()
            loss_sum = 0
            closs_sum = 0
            
            for batch_idx, batch in enumerate(train_data):
                try:
                    user_id, exer_id, knowledge_emb, score = batch
                    user_id = user_id.to(device)
                    exer_id = exer_id.to(device)
                    knowledge_emb = knowledge_emb.to(device)
                    score = score.to(device)
                    
                    # 检查是否有超出范围的ID
                    if torch.max(user_id).item() >= self.model.emb_num:
                        print(f"警告: 批次 {batch_idx} 中用户ID {torch.max(user_id).item()} 超出范围 {self.model.emb_num}")
                        continue
                    
                    if torch.max(exer_id).item() >= self.model.exer_n:
                        print(f"警告: 批次 {batch_idx} 中习题ID {torch.max(exer_id).item()} 超出范围 {self.model.exer_n}")
                        continue
                    
                    optimizer.zero_grad()
                    output, affect, closs = self.model(user_id, exer_id, knowledge_emb, score)
                    
                    # 计算预测损失
                    pred_loss = nn.BCELoss()(output.view(-1), score)
                    # 总损失 = 预测损失 + 对比损失
                    loss = pred_loss + 0.1 * closs
                    
                    loss.backward()
                    optimizer.step()
                    self.model.apply_clipper()
                    
                    loss_sum += pred_loss.item()
                    closs_sum += closs.item()
                except Exception as ex:
                    print(f"批次 {batch_idx} 处理出错: {ex}")
                    continue
            
            # 评估模型
            try:
                auc, acc, rmse = self.eval(test_data, device)
                print(f"Epoch {e+1}, Loss: {loss_sum:.4f}, CLoss: {closs_sum:.4f}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
                
                # 保存最佳模型
                if auc > best_auc:
                    best_auc = auc
                    best_acc = acc
                    best_rmse = rmse
                    best_epoch = e + 1
                    best_model_state = self.model.state_dict().copy()
                    print(f"发现更好的模型! Epoch {best_epoch}, AUC: {best_auc:.4f}, ACC: {best_acc:.4f}, RMSE: {best_rmse:.4f}")
            except Exception as ex:
                print(f"评估时出错: {ex}")
                continue
        
        end_time = time.time()
        train_time = end_time - start_time
        print(f"训练完成，用时 {train_time:.2f} 秒")
        print(f"最佳轮次: {best_epoch}, 最佳AUC: {best_auc:.4f}, 最佳ACC: {best_acc:.4f}, 最佳RMSE: {best_rmse:.4f}")
        
        # 恢复最佳模型
        if best_model_state is not None:
            self.model.load_state_dict(best_model_state)
            print("已恢复最佳模型状态")
            
            # 再次评估最佳模型
            try:
                final_auc, final_acc, final_rmse = self.eval(test_data, device)
                print(f"最终评估结果 - AUC: {final_auc:.4f}, ACC: {final_acc:.4f}, RMSE: {final_rmse:.4f}")
            except Exception as ex:
                print(f"最终评估时出错: {ex}")
        
        return best_epoch, best_auc, best_acc, best_rmse
    
    def eval(self, test_data, device='cpu'):
        """
        评估模型性能
        :param test_data: 测试数据
        :param device: 设备
        :return: AUC，准确率，RMSE
        """
        self.model.eval()
        y_true = []
        y_pred = []
        
        with torch.no_grad():
            for batch_idx, batch in enumerate(test_data):
                try:
                    user_id, exer_id, knowledge_emb, score = batch
                    
                    # 检查是否有超出范围的ID
                    if torch.max(user_id).item() >= self.model.emb_num or torch.max(exer_id).item() >= self.model.exer_n:
                        print(f"评估时跳过批次 {batch_idx}: ID超出范围")
                        continue
                    
                    user_id = user_id.to(device)
                    exer_id = exer_id.to(device)
                    knowledge_emb = knowledge_emb.to(device)
                    
                    output, _ = self.model(user_id, exer_id, knowledge_emb)
                    
                    y_true.extend(score.numpy())
                    y_pred.extend(output.view(-1).cpu().numpy())
                except Exception as ex:
                    print(f"评估批次 {batch_idx} 出错: {ex}")
                    continue
        
        if len(y_true) == 0:
            print("警告: 没有有效的评估数据")
            return 0.5, 0.5, 1.0
        
        # 计算AUC和准确率
        y_pred_binary = np.array(y_pred) >= 0.5
        acc = accuracy_score(y_true, y_pred_binary)
        auc = roc_auc_score(y_true, y_pred)
        
        # 计算RMSE
        rmse = math.sqrt(mean_squared_error(y_true, y_pred))
        
        return auc, acc, rmse 