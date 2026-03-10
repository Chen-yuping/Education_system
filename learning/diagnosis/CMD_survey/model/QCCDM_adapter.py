import logging
import numpy as np
import torch
from torch import nn
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import sys
from model.QCCDM import QCCDM


class QCCDM_Adapter:
    def __init__(self, knowledge_n, exer_n, student_n, mode='12', lambda_reg=0.01, 
                 dtype=torch.float32, num_layers=2, nonlinear='sigmoid', q_aug='single'):
        """
        QCCDM模型适配器，将QCCDM模型适配到当前系统
        
        :param knowledge_n: 知识点数量
        :param exer_n: 习题数量
        :param student_n: 学生数量
        :param mode: 模型模式 '1'-SCM, '2'-Q增强, '12'-两者都使用
        :param lambda_reg: 正则化参数
        :param dtype: 数据类型
        :param num_layers: 网络层数
        :param nonlinear: 非线性函数
        :param q_aug: Q矩阵增强方式
        """
        super(QCCDM_Adapter, self).__init__()
        self.knowledge_n = knowledge_n
        self.exer_n = exer_n
        self.student_n = student_n
        self.mode = mode
        self.lambda_reg = lambda_reg
        self.dtype = dtype
        self.num_layers = num_layers
        self.nonlinear = nonlinear
        self.q_aug = q_aug
        
        # 初始化Q矩阵(在CPU上)
        self.q_matrix = torch.zeros((self.exer_n, self.knowledge_n))
        
        # 初始化图结构 (对于模式1)，保持在CPU上
        self.graph = torch.eye(self.knowledge_n) if '1' in self.mode else None

    def prepare_data(self, train_data, test_data, device):
        """
        将DataLoader数据转换为QCCDM所需的numpy格式
        
        :param train_data: 训练数据的DataLoader
        :param test_data: 测试数据的DataLoader
        :param device: 设备
        :return: 转换后的训练数据和测试数据，以及完整的Q矩阵
        """
        train_data_np = []
        test_data_np = []
        
        # 处理训练数据并构建Q矩阵
        print("正在构建Q矩阵并处理训练数据...")
        for batch_data in tqdm(train_data):
            user_id, item_id, knowledge_emb, score = batch_data
            # 确保所有数据都在CPU上进行处理
            user_id = user_id.cpu().numpy()
            item_id = item_id.cpu().numpy()
            knowledge_emb = knowledge_emb.cpu().numpy()
            score = score.cpu().numpy()
            
            # 更新Q矩阵
            for i in range(len(item_id)):
                self.q_matrix[item_id[i]] = torch.Tensor(knowledge_emb[i])
            
            # 转换为QCCDM输入格式 [user_id, item_id, score]
            for i in range(len(user_id)):
                # 确保用户ID和题目ID为整数
                u_id = int(user_id[i])
                i_id = int(item_id[i])
                s = float(score[i])
                
                # 确保索引在有效范围内
                if 0 <= u_id < self.student_n and 0 <= i_id < self.exer_n:
                    train_data_np.append([u_id, i_id, s])
                
        # 处理测试数据
        print("正在处理测试数据...")
        for batch_data in tqdm(test_data):
            user_id, item_id, knowledge_emb, score = batch_data
            # 确保所有数据都在CPU上进行处理
            user_id = user_id.cpu().numpy()
            item_id = item_id.cpu().numpy()
            knowledge_emb = knowledge_emb.cpu().numpy()
            score = score.cpu().numpy()
            
            # 更新Q矩阵 (确保覆盖测试数据中的题目)
            for i in range(len(item_id)):
                self.q_matrix[item_id[i]] = torch.Tensor(knowledge_emb[i])
            
            # 转换为QCCDM输入格式
            for i in range(len(user_id)):
                # 确保用户ID和题目ID为整数
                u_id = int(user_id[i])
                i_id = int(item_id[i])
                s = float(score[i])
                
                # 确保索引在有效范围内
                if 0 <= u_id < self.student_n and 0 <= i_id < self.exer_n:
                    test_data_np.append([u_id, i_id, s])
        
        # 转换为numpy数组
        train_data_np = np.array(train_data_np)
        test_data_np = np.array(test_data_np)
        
        # 将Q矩阵移至指定设备
        q_matrix = self.q_matrix.to(device)
        
        # 如果有图结构，也将其移至指定设备
        if self.graph is not None:
            self.graph = self.graph.to(device)
        
        return train_data_np, test_data_np, q_matrix

    def train(self, train_data, test_data=None, *, epoch: int, device="cpu", lr=0.001) -> ...:
        """
        训练QCCDM模型
        
        :param train_data: 训练数据的DataLoader
        :param test_data: 测试数据的DataLoader
        :param epoch: 训练轮数
        :param device: 设备
        :param lr: 学习率
        :return: 最佳轮次、AUC、准确率、RMSE
        """
        print("初始化QCCDM模型...")
        print(f"模式: {self.mode}, 正则化参数: {self.lambda_reg}, 非线性函数: {self.nonlinear}, Q矩阵增强: {self.q_aug}")
        print(f"设备: {device}, 数据类型: {self.dtype}")
        
        # 设置默认数据类型，确保所有新创建的张量使用相同类型
        torch.set_default_dtype(self.dtype)
        
        # 准备数据
        train_data_np, test_data_np, q_matrix = self.prepare_data(train_data, test_data, device)
        
        # 初始化QCCDM模型
        self.qccdm = QCCDM(
            stu_num=self.student_n,
            prob_num=self.exer_n, 
            know_num=self.knowledge_n,
            q_matrix=q_matrix,
            device=device,
            graph=self.graph,
            lambda_reg=self.lambda_reg,
            mode=self.mode,
            dtype=self.dtype,  # 确保传递正确的数据类型
            num_layers=self.num_layers,
            nonlinear=self.nonlinear,
            q_aug=self.q_aug
        )
        
        # 训练模型
        try:
            print(f"开始训练QCCDM模型，共{epoch}轮...")
            self.qccdm.train(
                np_train=train_data_np,
                np_test=test_data_np,
                batch_size=128,
                epoch=epoch,
                lr=lr,
                q=q_matrix
            )
            
            # 评估模型
            print("评估模型性能...")
            auc, accuracy, rmse, f1, doa = self.qccdm.eval(test_data_np, q=q_matrix)
            print(f"评估结果 - AUC: {auc:.4f}, ACC: {accuracy:.4f}, RMSE: {rmse:.4f}, F1: {f1:.4f}, DOA: {doa:.4f}")
            
            return epoch, auc, accuracy, rmse
        except Exception as e:
            print(f"训练过程中出错: {e}")
            import traceback
            traceback.print_exc()
            return 0, 0.5, 0.5, 1.0

    def eval(self, test_data, device="cpu") -> tuple:
        """
        评估QCCDM模型性能
        
        :param test_data: 测试数据的DataLoader
        :param device: 设备
        :return: AUC、准确率、RMSE、F1分数
        """
        # 转换数据
        _, test_data_np, q_matrix = self.prepare_data(test_data, test_data, device)
        
        # 评估模型
        auc, accuracy, rmse, f1, doa = self.qccdm.eval(test_data_np, q=q_matrix)
        
        return auc, accuracy, rmse, f1

    def save(self, filepath):
        """
        保存模型参数
        
        :param filepath: 文件路径
        """
        torch.save(self.qccdm.net.state_dict(), filepath)
        logging.info("保存参数到 %s" % filepath)

    def load(self, filepath):
        """
        加载模型参数
        
        :param filepath: 文件路径
        """
        self.qccdm.net.load_state_dict(torch.load(filepath))
        logging.info("从 %s 加载参数" % filepath) 