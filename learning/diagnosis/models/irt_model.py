"""
IRT (Item Response Theory) 项目反应理论模型

IRT是一种经典的心理测量模型，用于评估学生能力和题目难度。
本实现采用三参数逻辑斯蒂模型 (3PL)：
P(θ) = c + (1-c) / (1 + exp(-a(θ-b)))

其中：
- θ: 学生能力参数
- a: 题目区分度
- b: 题目难度
- c: 猜测参数
"""

import numpy as np
from typing import Dict, List, Tuple, Any
from scipy.optimize import minimize
from scipy.special import expit  # sigmoid函数
import warnings

warnings.filterwarnings('ignore')


class IRTModel:
    """
    项目反应理论模型 (Item Response Theory)
    支持1PL, 2PL, 3PL模型
    """

    def __init__(self, model_type: str = '2PL', max_iter: int = 50, tol: float = 1e-3):
        """
        初始化IRT模型

        Args:
            model_type: 模型类型 ('1PL', '2PL', '3PL')
            max_iter: 最大迭代次数（减少以提高速度）
            tol: 收敛阈值（放宽以提高速度）
        """
        self.model_type = model_type
        self.max_iter = max_iter
        self.tol = tol

        # 模型参数
        self.theta = None  # 学生能力参数 [n_students]
        self.a = None  # 题目区分度 [n_items]
        self.b = None  # 题目难度 [n_items]
        self.c = None  # 猜测参数 [n_items]

        # 训练历史
        self.loss_history = []

    def _probability(self, theta: np.ndarray, a: np.ndarray, 
                     b: np.ndarray, c: np.ndarray) -> np.ndarray:
        """
        计算正确作答概率 (3PL模型)

        P(θ) = c + (1-c) * sigmoid(a * (θ - b))

        Args:
            theta: 学生能力 [n_students, 1] 或 [n_students]
            a: 区分度 [n_items]
            b: 难度 [n_items]
            c: 猜测参数 [n_items]

        Returns:
            概率矩阵 [n_students, n_items]
        """
        theta = np.atleast_2d(theta).T if theta.ndim == 1 else theta
        
        # 计算 a * (θ - b)
        z = a * (theta - b)
        
        # 3PL公式
        prob = c + (1 - c) * expit(z)
        
        return np.clip(prob, 1e-10, 1 - 1e-10)

    def _negative_log_likelihood(self, params: np.ndarray, 
                                  response_matrix: np.ndarray,
                                  n_students: int, n_items: int) -> float:
        """
        计算负对数似然

        Args:
            params: 所有参数的扁平化数组
            response_matrix: 作答矩阵 [n_students, n_items]
            n_students: 学生数量
            n_items: 题目数量

        Returns:
            负对数似然值
        """
        # 解析参数
        theta = params[:n_students]
        
        if self.model_type == '1PL':
            a = np.ones(n_items)
            b = params[n_students:n_students + n_items]
            c = np.zeros(n_items)
        elif self.model_type == '2PL':
            a = params[n_students:n_students + n_items]
            b = params[n_students + n_items:n_students + 2 * n_items]
            c = np.zeros(n_items)
        else:  # 3PL
            a = params[n_students:n_students + n_items]
            b = params[n_students + n_items:n_students + 2 * n_items]
            c = params[n_students + 2 * n_items:]

        # 计算概率
        prob = self._probability(theta, a, b, c)

        # 计算对数似然
        # 只计算有作答记录的位置
        mask = ~np.isnan(response_matrix)
        
        log_likelihood = 0
        for i in range(n_students):
            for j in range(n_items):
                if mask[i, j]:
                    p = prob[i, j]
                    y = response_matrix[i, j]
                    log_likelihood += y * np.log(p) + (1 - y) * np.log(1 - p)

        return -log_likelihood

    def fit(self, response_matrix: np.ndarray, 
            student_ids: List[int] = None,
            item_ids: List[int] = None) -> 'IRTModel':
        """
        训练IRT模型

        Args:
            response_matrix: 作答矩阵 [n_students, n_items]，NaN表示未作答
            student_ids: 学生ID列表
            item_ids: 题目ID列表

        Returns:
            self
        """
        n_students, n_items = response_matrix.shape
        
        self.student_ids = student_ids if student_ids else list(range(n_students))
        self.item_ids = item_ids if item_ids else list(range(n_items))

        # 初始化参数
        theta_init = np.zeros(n_students)
        
        if self.model_type == '1PL':
            b_init = np.zeros(n_items)
            params_init = np.concatenate([theta_init, b_init])
        elif self.model_type == '2PL':
            a_init = np.ones(n_items)
            b_init = np.zeros(n_items)
            params_init = np.concatenate([theta_init, a_init, b_init])
        else:  # 3PL
            a_init = np.ones(n_items)
            b_init = np.zeros(n_items)
            c_init = np.full(n_items, 0.2)
            params_init = np.concatenate([theta_init, a_init, b_init, c_init])

        # 设置参数边界
        bounds = []
        # theta 边界
        bounds.extend([(-4, 4)] * n_students)
        
        if self.model_type == '1PL':
            # b 边界
            bounds.extend([(-4, 4)] * n_items)
        elif self.model_type == '2PL':
            # a 边界
            bounds.extend([(0.1, 3)] * n_items)
            # b 边界
            bounds.extend([(-4, 4)] * n_items)
        else:  # 3PL
            # a 边界
            bounds.extend([(0.1, 3)] * n_items)
            # b 边界
            bounds.extend([(-4, 4)] * n_items)
            # c 边界
            bounds.extend([(0, 0.5)] * n_items)

        # 优化
        result = minimize(
            self._negative_log_likelihood,
            params_init,
            args=(response_matrix, n_students, n_items),
            method='L-BFGS-B',
            bounds=bounds,
            options={'maxiter': self.max_iter, 'disp': False}
        )

        # 解析结果
        params = result.x
        self.theta = params[:n_students]
        
        if self.model_type == '1PL':
            self.a = np.ones(n_items)
            self.b = params[n_students:n_students + n_items]
            self.c = np.zeros(n_items)
        elif self.model_type == '2PL':
            self.a = params[n_students:n_students + n_items]
            self.b = params[n_students + n_items:n_students + 2 * n_items]
            self.c = np.zeros(n_items)
        else:  # 3PL
            self.a = params[n_students:n_students + n_items]
            self.b = params[n_students + n_items:n_students + 2 * n_items]
            self.c = params[n_students + 2 * n_items:]

        self.loss_history.append(result.fun)
        
        return self

    def predict_proba(self, student_indices: np.ndarray = None, 
                      item_indices: np.ndarray = None) -> np.ndarray:
        """
        预测正确作答概率

        Args:
            student_indices: 学生索引
            item_indices: 题目索引

        Returns:
            概率矩阵
        """
        if self.theta is None:
            raise ValueError("模型尚未训练")

        theta = self.theta if student_indices is None else self.theta[student_indices]
        a = self.a if item_indices is None else self.a[item_indices]
        b = self.b if item_indices is None else self.b[item_indices]
        c = self.c if item_indices is None else self.c[item_indices]

        return self._probability(theta, a, b, c)

    def get_student_ability(self) -> Dict[int, float]:
        """
        获取学生能力值

        Returns:
            学生ID到能力值的映射
        """
        if self.theta is None:
            raise ValueError("模型尚未训练")

        # 将能力值转换为0-1范围
        normalized_theta = expit(self.theta)
        
        return {
            student_id: float(normalized_theta[i])
            for i, student_id in enumerate(self.student_ids)
        }

    def get_item_parameters(self) -> Dict[int, Dict[str, float]]:
        """
        获取题目参数

        Returns:
            题目ID到参数的映射
        """
        if self.a is None:
            raise ValueError("模型尚未训练")

        return {
            item_id: {
                'discrimination': float(self.a[i]),  # 区分度
                'difficulty': float(self.b[i]),  # 难度
                'guessing': float(self.c[i])  # 猜测参数
            }
            for i, item_id in enumerate(self.item_ids)
        }

    def diagnose_student(self, student_idx: int, 
                         q_matrix: np.ndarray,
                         knowledge_point_ids: List[int]) -> Dict[str, Any]:
        """
        诊断单个学生的知识点掌握情况

        Args:
            student_idx: 学生索引
            q_matrix: Q矩阵 [n_items, n_knowledge_points]
            knowledge_point_ids: 知识点ID列表

        Returns:
            诊断结果
        """
        if self.theta is None:
            raise ValueError("模型尚未训练")

        student_ability = self.theta[student_idx]
        normalized_ability = expit(student_ability)

        # 基于学生能力和Q矩阵计算各知识点掌握度
        knowledge_mastery = {}
        
        for kp_idx, kp_id in enumerate(knowledge_point_ids):
            # 找出考察该知识点的题目
            related_items = np.where(q_matrix[:, kp_idx] > 0)[0]
            
            if len(related_items) > 0:
                # 计算该知识点相关题目的平均预测正确率
                probs = self._probability(
                    np.array([student_ability]),
                    self.a[related_items],
                    self.b[related_items],
                    self.c[related_items]
                )
                mastery = float(np.mean(probs))
            else:
                # 没有相关题目，使用整体能力
                mastery = float(normalized_ability)
            
            knowledge_mastery[str(kp_id)] = round(mastery, 4)

        return {
            'student_ability': float(normalized_ability),
            'knowledge_mastery': knowledge_mastery
        }


class IRTDiagnosisService:
    """IRT诊断服务，封装IRT模型用于认知诊断"""

    def __init__(self, model_type: str = '2PL'):
        """
        初始化IRT诊断服务

        Args:
            model_type: IRT模型类型 ('1PL', '2PL', '3PL')
        """
        self.model_type = model_type
        self.model = None

    def run_diagnosis(self, students_data: Dict, 
                      exercises: List, 
                      knowledge_points: List,
                      q_matrix: np.ndarray) -> Dict[str, Any]:
        """
        运行IRT诊断

        Args:
            students_data: 学生数据字典
            exercises: 习题列表
            knowledge_points: 知识点列表
            q_matrix: Q矩阵

        Returns:
            诊断结果
        """
        # 构建作答矩阵
        student_ids = list(students_data.keys())
        n_students = len(student_ids)
        n_items = len(exercises)

        # 创建学生ID到索引的映射
        student_id_to_idx = {sid: idx for idx, sid in enumerate(student_ids)}

        # 初始化作答矩阵（NaN表示未作答）
        response_matrix = np.full((n_students, n_items), np.nan)

        # 填充作答矩阵
        for student_id, student_info in students_data.items():
            student_idx = student_id_to_idx[student_id]
            for log in student_info['answer_logs']:
                item_idx = log['exercise_idx']
                if item_idx < n_items:
                    response_matrix[student_idx, item_idx] = 1 if log['is_correct'] else 0

        # 检查是否有足够的数据
        valid_responses = ~np.isnan(response_matrix)
        if np.sum(valid_responses) < 10:
            return {'error': '答题数据不足，无法进行IRT诊断'}

        # 训练IRT模型
        self.model = IRTModel(model_type=self.model_type)
        
        try:
            self.model.fit(response_matrix, student_ids=student_ids)
        except Exception as e:
            return {'error': f'IRT模型训练失败: {str(e)}'}

        # 获取诊断结果
        diagnosis_results = {}
        knowledge_point_ids = [kp.id for kp in knowledge_points]

        for student_id in student_ids:
            student_idx = student_id_to_idx[student_id]
            student_info = students_data[student_id]

            # 使用IRT模型诊断
            diagnosis = self.model.diagnose_student(
                student_idx, q_matrix, knowledge_point_ids
            )

            # 计算练习次数和正确次数
            practice_counts = {}
            correct_counts = {}
            
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
            mastery_values = list(diagnosis['knowledge_mastery'].values())
            overall_score = round(sum(mastery_values) / len(mastery_values), 4) if mastery_values else 0

            # 找出薄弱知识点
            weak_points = []
            for kp in knowledge_points:
                kp_id_str = str(kp.id)
                mastery = diagnosis['knowledge_mastery'].get(kp_id_str, 0)
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
                'student_ability': diagnosis['student_ability'],
                'knowledge_mastery': diagnosis['knowledge_mastery'],
                'practice_counts': practice_counts,
                'correct_counts': correct_counts,
                'overall_score': overall_score,
                'weak_points': weak_points,
                'answer_count': len(student_info['answer_logs'])
            }

        return {
            'diagnosis_results': diagnosis_results,
            'model_info': {
                'type': 'IRT',
                'subtype': self.model_type,
                'item_parameters': self.model.get_item_parameters() if self.model else {}
            }
        }
