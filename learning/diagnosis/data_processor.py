from django.db import connection
from django.db.models import Count, Avg
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from ..models import AnswerLog, QMatrix, KnowledgePoint, Subject


class DiagnosisDataProcessor:
    """诊断数据处理模块"""

    @staticmethod
    def prepare_data_for_subject(subject_id: int) -> Dict:
        """
        为指定科目准备NCD模型所需数据

        Returns:
            {
                'student_ids': List[int],
                'exercise_ids': List[int],
                'knowledge_ids': List[int],
                'q_matrix': np.ndarray,
                'interaction_data': List[Tuple[student_id, exercise_id, correctness]]
            }
        """
        # 1. 获取科目下的知识点
        knowledge_points = KnowledgePoint.objects.filter(
            subject_id=subject_id
        ).order_by('id')
        knowledge_ids = list(knowledge_points.values_list('id', flat=True))

        # 2. 获取Q矩阵
        q_matrix_records = QMatrix.objects.filter(
            exercise__subject_id=subject_id
        ).select_related('exercise', 'knowledge_point')

        # 构建Q矩阵 DataFrame
        q_matrix_df = pd.DataFrame(list(q_matrix_records.values(
            'exercise_id', 'knowledge_point_id', 'weight'
        )))

        # 转换为稀疏矩阵格式
        if not q_matrix_df.empty:
            q_matrix = q_matrix_df.pivot_table(
                index='exercise_id',
                columns='knowledge_point_id',
                values='weight',
                fill_value=0
            )
            # 确保所有知识点都有列
            for kid in knowledge_ids:
                if kid not in q_matrix.columns:
                    q_matrix[kid] = 0

            q_matrix = q_matrix[knowledge_ids]  # 按知识ID排序
            exercise_ids = q_matrix.index.tolist()
            q_matrix_array = q_matrix.values.astype(np.float32)
        else:
            exercise_ids = []
            q_matrix_array = np.zeros((0, len(knowledge_ids)), dtype=np.float32)

        # 3. 获取学生答题数据
        answer_logs = AnswerLog.objects.filter(
            exercise__subject_id=subject_id
        ).select_related('student', 'exercise')

        # 构建交互数据
        interaction_data = []
        student_set = set()

        for log in answer_logs:
            if log.exercise_id in exercise_ids and log.is_correct is not None:
                interaction_data.append({
                    'student_id': log.student_id,
                    'exercise_id': log.exercise_id,
                    'correctness': 1 if log.is_correct else 0
                })
                student_set.add(log.student_id)

        student_ids = list(student_set)

        return {
            'student_ids': student_ids,
            'exercise_ids': exercise_ids,
            'knowledge_ids': knowledge_ids,
            'q_matrix': q_matrix_array,
            'interaction_data': interaction_data,
            'knowledge_names': {k.id: k.name for k in knowledge_points}
        }

    @staticmethod
    def create_training_data(interaction_data: List[Dict],
                             student_ids: List[int],
                             exercise_ids: List[int]) -> Tuple[np.ndarray, np.ndarray]:
        """创建训练数据"""
        if not interaction_data:
            return np.array([]), np.array([])

        # 创建学生和习题的映射
        student_to_idx = {sid: i for i, sid in enumerate(student_ids)}
        exercise_to_idx = {eid: i for i, eid in enumerate(exercise_ids)}

        X = []
        y = []

        for item in interaction_data:
            student_idx = student_to_idx.get(item['student_id'])
            exercise_idx = exercise_to_idx.get(item['exercise_id'])

            if student_idx is not None and exercise_idx is not None:
                X.append([student_idx, exercise_idx])
                y.append(item['correctness'])

        return np.array(X), np.array(y)

    @staticmethod
    def calculate_weak_points(mastery_vector: List[float],
                              threshold: float = 0.5) -> List[int]:
        """计算薄弱知识点（掌握度低于阈值）"""
        weak_points = []
        for i, mastery in enumerate(mastery_vector):
            if mastery < threshold:
                weak_points.append(i)
        return weak_points

    @staticmethod
    def calculate_overall_score(mastery_vector: List[float]) -> float:
        """计算总体掌握度分数"""
        if not mastery_vector:
            return 0.0
        return float(np.mean(mastery_vector))