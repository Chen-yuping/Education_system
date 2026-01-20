import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from scipy.special import expit
import torch.optim as optim
from sklearn.model_selection import train_test_split
import json


class NCDModel:
    """
    Neural Cognitive Diagnosis Model (NCD)
    参考论文: "Neural Cognitive Diagnosis for Intelligent Education Systems"
    """

    def __init__(self, n_knowledge_points: int, hidden_dim: int = 64,
                 learning_rate: float = 0.001, epochs: int = 100):
        """
        初始化NCD模型

        Args:
            n_knowledge_points: 知识点数量
            hidden_dim: 隐藏层维度
            learning_rate: 学习率
            epochs: 训练轮数
        """
        self.n_knowledge_points = n_knowledge_points
        self.hidden_dim = hidden_dim
        self.learning_rate = learning_rate
        self.epochs = epochs

        # 模型参数
        self.student_embedding = None  # 学生掌握度向量
        self.exercise_embedding = None  # 习题难度向量
        self.knowledge_embedding = None  # 知识点嵌入
        self.predict_layer = None  # 预测层

        # 训练历史
        self.loss_history = []

    def build_model(self):
        """构建神经网络模型"""
        # 学生掌握度参数 (可学习的)
        self.student_embedding = nn.Parameter(
            torch.randn(self.n_knowledge_points) * 0.1
        )

        # 习题难度参数
        self.exercise_embedding = nn.Parameter(
            torch.randn(self.n_knowledge_points) * 0.1
        )

        # 知识点交互矩阵
        self.knowledge_embedding = nn.Parameter(
            torch.randn(self.n_knowledge_points, self.hidden_dim) * 0.1
        )

        # 预测层
        self.predict_layer = nn.Sequential(
            nn.Linear(self.hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )

    def forward(self, q_matrix: torch.Tensor) -> torch.Tensor:
        """
        前向传播

        Args:
            q_matrix: 习题-知识点关联矩阵 [batch_size, n_knowledge_points]

        Returns:
            预测的正确率 [batch_size, 1]
        """
        # 计算学生的认知状态
        cognitive_state = self.student_embedding * q_matrix

        # 计算习题认知需求
        exercise_demand = self.exercise_embedding * q_matrix

        # 交互项
        interaction = cognitive_state * exercise_demand

        # 通过知识点嵌入层
        embedded = torch.matmul(interaction.unsqueeze(1),
                                self.knowledge_embedding)
        embedded = embedded.squeeze(1)

        # 预测层
        prediction = self.predict_layer(embedded)

        return prediction

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            q_matrix: np.ndarray, X_val=None, y_val=None):
        """
        训练模型

        Args:
            X_train: 训练数据 [学生ID, 习题ID]
            y_train: 训练标签 [正确/错误]
            q_matrix: Q矩阵 [习题数, 知识点数]
            X_val: 验证数据
            y_val: 验证标签
        """
        # 转换为Tensor
        X_train_tensor = torch.LongTensor(X_train)
        y_train_tensor = torch.FloatTensor(y_train).unsqueeze(1)
        q_matrix_tensor = torch.FloatTensor(q_matrix)

        # 构建模型
        self.build_model()

        # 优化器
        optimizer = optim.Adam([
                                   self.student_embedding,
                                   self.exercise_embedding,
                                   self.knowledge_embedding
                               ] + list(self.predict_layer.parameters()),
                               lr=self.learning_rate)

        criterion = nn.BCELoss()

        # 训练循环
        for epoch in range(self.epochs):
            optimizer.zero_grad()

            # 获取当前批次的Q矩阵
            exercise_indices = X_train_tensor[:, 1]
            batch_q_matrix = q_matrix_tensor[exercise_indices]

            # 前向传播
            outputs = self.forward(batch_q_matrix)

            # 计算损失
            loss = criterion(outputs, y_train_tensor)

            # 反向传播
            loss.backward()
            optimizer.step()

            self.loss_history.append(loss.item())

            if (epoch + 1) % 10 == 0:
                print(f"Epoch [{epoch + 1}/{self.epochs}], Loss: {loss.item():.4f}")

    def predict(self, X: np.ndarray, q_matrix: np.ndarray) -> np.ndarray:
        """预测正确率"""
        with torch.no_grad():
            X_tensor = torch.LongTensor(X)
            q_matrix_tensor = torch.FloatTensor(q_matrix)

            exercise_indices = X_tensor[:, 1]
            batch_q_matrix = q_matrix_tensor[exercise_indices]

            predictions = self.forward(batch_q_matrix)
            return predictions.numpy().flatten()

    def get_student_mastery(self, student_ids: List[int]) -> Dict[int, List[float]]:
        """获取学生掌握度向量"""
        with torch.no_grad():
            mastery = {}
            # 使用sigmoid将掌握度转换为[0,1]范围
            student_mastery = torch.sigmoid(self.student_embedding).numpy()

            for i, student_id in enumerate(student_ids):
                # 这里简化处理，实际应该根据学生数量调整
                mastery[student_id] = student_mastery.tolist()

            return mastery

    def save_model(self, filepath: str):
        """保存模型"""
        torch.save({
            'student_embedding': self.student_embedding,
            'exercise_embedding': self.exercise_embedding,
            'knowledge_embedding': self.knowledge_embedding,
            'predict_layer': self.predict_layer.state_dict(),
            'n_knowledge_points': self.n_knowledge_points,
            'hidden_dim': self.hidden_dim
        }, filepath)

    def load_model(self, filepath: str):
        """加载模型"""
        checkpoint = torch.load(filepath, map_location='cpu')
        self.n_knowledge_points = checkpoint['n_knowledge_points']
        self.hidden_dim = checkpoint['hidden_dim']

        self.student_embedding = checkpoint['student_embedding']
        self.exercise_embedding = checkpoint['exercise_embedding']
        self.knowledge_embedding = checkpoint['knowledge_embedding']

        self.predict_layer = nn.Sequential(
            nn.Linear(self.hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )
        self.predict_layer.load_state_dict(checkpoint['predict_layer'])



class NCDDiagnosisService:
    """NCD诊断服务，封装NCD模型用于认知诊断"""

    def __init__(self, hidden_dim: int = 64, learning_rate: float = 0.002, epochs: int = 30):
        """
        初始化NCD诊断服务

        Args:
            hidden_dim: 隐藏层维度
            learning_rate: 学习率
            epochs: 训练轮数（减少以提高速度）
        """
        self.hidden_dim = hidden_dim
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.model = None

    def run_diagnosis(self, students_data: Dict, 
                      exercises: List, 
                      knowledge_points: List,
                      q_matrix: np.ndarray) -> Dict:
        """
        运行NCD诊断（优化版本：使用简化的批量方法）

        Args:
            students_data: 学生数据字典
            exercises: 习题列表
            knowledge_points: 知识点列表
            q_matrix: Q矩阵 [n_exercises, n_knowledge_points]

        Returns:
            诊断结果
        """
        student_ids = list(students_data.keys())
        n_students = len(student_ids)
        n_items = len(exercises)
        n_kps = len(knowledge_points)

        if n_kps == 0:
            return {'error': '该科目没有知识点数据'}

        # 创建学生ID到索引的映射
        student_id_to_idx = {sid: idx for idx, sid in enumerate(student_ids)}
        knowledge_point_ids = [kp.id for kp in knowledge_points]

        # 使用简化方法：基于正确率和知识点权重的加权计算
        diagnosis_results = {}

        for student_id in student_ids:
            student_info = students_data[student_id]

            if not student_info['answer_logs']:
                continue

            # 计算每个知识点的掌握度（使用加权正确率）
            kp_stats = {}
            for kp_idx in range(n_kps):
                kp_stats[kp_idx] = {'total_weight': 0, 'correct_weight': 0}

            for log in student_info['answer_logs']:
                ex_idx = log['exercise_idx']
                if ex_idx < len(q_matrix):
                    related_kps = np.where(q_matrix[ex_idx] > 0)[0]
                    for kp_idx in related_kps:
                        if kp_idx < n_kps:
                            weight = q_matrix[ex_idx, kp_idx]
                            kp_stats[kp_idx]['total_weight'] += weight
                            if log['is_correct']:
                                kp_stats[kp_idx]['correct_weight'] += weight

            # 计算掌握度（使用sigmoid平滑）
            knowledge_mastery = {}
            practice_counts = {}
            correct_counts = {}

            for kp_idx, kp_id in enumerate(knowledge_point_ids):
                stats = kp_stats.get(kp_idx, {'total_weight': 0, 'correct_weight': 0})
                
                if stats['total_weight'] > 0:
                    # 基础正确率
                    base_mastery = stats['correct_weight'] / stats['total_weight']
                    # 使用sigmoid平滑，考虑练习次数
                    practice_factor = min(stats['total_weight'] / 5.0, 1.0)  # 5次练习达到稳定
                    mastery = base_mastery * practice_factor + 0.5 * (1 - practice_factor)
                else:
                    mastery = 0.5  # 未练习的知识点给予中等掌握度

                knowledge_mastery[str(kp_id)] = round(float(mastery), 4)

            # 计算练习次数和正确次数
            for kp in knowledge_points:
                kp_id_str = str(kp.id)
                practice_counts[kp_id_str] = 0
                correct_counts[kp_id_str] = 0

            for log in student_info['answer_logs']:
                ex_idx = log['exercise_idx']
                if ex_idx < len(q_matrix):
                    related_kps = np.where(q_matrix[ex_idx] > 0)[0]
                    for kp_idx in related_kps:
                        if kp_idx < len(knowledge_points):
                            kp_id_str = str(knowledge_points[kp_idx].id)
                            practice_counts[kp_id_str] += 1
                            if log['is_correct']:
                                correct_counts[kp_id_str] += 1

            # 计算总体掌握度
            mastery_values = list(knowledge_mastery.values())
            overall_score = round(sum(mastery_values) / len(mastery_values), 4) if mastery_values else 0

            # 找出薄弱知识点
            weak_points = []
            for kp in knowledge_points:
                kp_id_str = str(kp.id)
                mastery = knowledge_mastery.get(kp_id_str, 0)
                if mastery < 0.6:
                    weak_points.append({
                        'id': kp_id_str,
                        'name': kp.name,
                        'mastery': mastery,
                        'practice_count': practice_counts.get(kp_id_str, 0),
                        'correct_count': correct_counts.get(kp_id_str, 0)
                    })

            diagnosis_results[student_id] = {
                'student_id': student_id,
                'student_name': student_info['first_name'],
                'username': student_info['username'],
                'knowledge_mastery': knowledge_mastery,
                'practice_counts': practice_counts,
                'correct_counts': correct_counts,
                'overall_score': overall_score,
                'weak_points': weak_points,
                'answer_count': len(student_info['answer_logs'])
            }

        return {
            'diagnosis_results': diagnosis_results,
            'model_info': {
                'type': 'NCD',
                'method': 'weighted_accuracy',
                'hidden_dim': self.hidden_dim
            }
        }

    def _simple_mastery(self, student_info: Dict, q_matrix: np.ndarray, 
                        knowledge_points: List) -> Dict[str, float]:
        """当数据不足时使用简单正确率计算掌握度"""
        from collections import defaultdict

        kp_stats = defaultdict(lambda: {'total': 0, 'correct': 0})

        for log in student_info['answer_logs']:
            ex_idx = log['exercise_idx']
            if ex_idx < len(q_matrix):
                related_kps = np.where(q_matrix[ex_idx] > 0)[0]
                for kp_idx in related_kps:
                    if kp_idx < len(knowledge_points):
                        kp_id = knowledge_points[kp_idx].id
                        kp_stats[kp_id]['total'] += 1
                        if log['is_correct']:
                            kp_stats[kp_id]['correct'] += 1

        knowledge_mastery = {}
        for kp in knowledge_points:
            stats = kp_stats.get(kp.id, {'total': 0, 'correct': 0})
            if stats['total'] > 0:
                mastery = stats['correct'] / stats['total']
            else:
                mastery = 0.0
            knowledge_mastery[str(kp.id)] = round(mastery, 4)

        return knowledge_mastery
