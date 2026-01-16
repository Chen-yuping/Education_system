# D:\Project\Learning platform\Github\Education_system\learning\diagnosis\services.py
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from django.db.models import Q
from django.utils import timezone
import json
from collections import defaultdict
from django.db import transaction

from ..models import (
    User, Subject, StudentSubject, AnswerLog,
    Exercise, QMatrix, KnowledgePoint, StudentDiagnosis, DiagnosisModel
)

# 导入诊断模型
from .models import IRTDiagnosisService, NCDDiagnosisService


class DiagnosisService:
    """诊断服务类"""

    def __init__(self, teacher_id: int):
        self.teacher_id = teacher_id

    def get_teacher_subjects(self):
        """获取教师所授科目"""
        from ..models import TeacherSubject
        return TeacherSubject.objects.filter(
            teacher_id=self.teacher_id
        ).select_related('subject').distinct()

    def get_subject_students(self, subject_id: int):
        """获取科目下的学生"""
        return StudentSubject.objects.filter(
            subject_id=subject_id
        ).select_related('student').distinct()

    def build_diagnosis_data(self, subject_id: int) -> Dict[str, Any]:
        """
        构建诊断所需数据 - 从做题记录中获取所有学生

        Returns:
            包含学生答题数据、Q矩阵、知识点的字典
        """
        # 获取该科目的所有习题
        exercises = Exercise.objects.filter(
            subject_id=subject_id
        ).order_by('id')
        exercise_list = list(exercises)
        exercise_id_map = {ex.id: idx for idx, ex in enumerate(exercise_list)}

        # 获取该科目的所有知识点
        knowledge_points = KnowledgePoint.objects.filter(
            subject_id=subject_id
        ).order_by('id')
        kp_list = list(knowledge_points)
        kp_id_map = {kp.id: idx for idx, kp in enumerate(kp_list)}

        # 构建Q矩阵
        n_exercises = len(exercise_list)
        n_kps = len(kp_list)
        Q = np.zeros((n_exercises, n_kps), dtype=np.float32)

        qmatrices = QMatrix.objects.filter(
            exercise__subject_id=subject_id
        ).select_related('exercise', 'knowledge_point')

        for qm in qmatrices:
            ex_idx = exercise_id_map.get(qm.exercise_id)
            kp_idx = kp_id_map.get(qm.knowledge_point_id)
            if ex_idx is not None and kp_idx is not None:
                Q[ex_idx, kp_idx] = qm.weight or 1.0

        # 从做题记录中获取该科目所有有答题记录的学生
        answer_logs = AnswerLog.objects.filter(
            exercise__subject_id=subject_id,
            is_correct__isnull=False
        ).select_related('student', 'exercise')

        # 先收集所有有答题记录的学生ID
        student_ids_with_logs = answer_logs.values_list('student_id', flat=True).distinct()
        
        # 获取这些学生的详细信息
        students_with_logs = User.objects.filter(
            id__in=student_ids_with_logs,
            user_type='student'
        )

        # 构建学生数据字典
        student_data = {}
        for student in students_with_logs:
            student_data[student.id] = {
                'id': student.id,
                'username': student.username,
                'first_name': f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username,
                'answer_logs': [],
                'exercise_scores': {}
            }

        # 填充答题记录
        for log in answer_logs:
            student_id = log.student_id
            if student_id in student_data:
                exercise_idx = exercise_id_map.get(log.exercise_id)
                if exercise_idx is not None:
                    student_data[student_id]['answer_logs'].append({
                        'exercise_id': log.exercise_id,
                        'exercise_idx': exercise_idx,
                        'is_correct': log.is_correct,
                        'time_spent': log.time_spent
                    })
                    student_data[student_id]['exercise_scores'][log.exercise_id] = log.is_correct

        return {
            'students': student_data,
            'exercises': exercise_list,
            'knowledge_points': kp_list,
            'Q_matrix': Q,
            'exercise_id_map': exercise_id_map,
            'kp_id_map': kp_id_map
        }

    def run_diagnosis(self, subject_id: int, model_name: str = 'simple') -> Dict[str, Any]:
        """
        运行诊断模型

        Args:
            subject_id: 科目ID
            model_name: 模型名称 ('simple', 'IRT', 'NCD' 等)

        Returns:
            诊断结果
        """
        # 构建数据
        data = self.build_diagnosis_data(subject_id)

        if not data['students']:
            return {'error': '该科目下没有学生答题数据'}

        # 根据模型类型选择诊断方法
        model_name_lower = model_name.lower()
        
        if 'irt' in model_name_lower:
            # 使用IRT模型
            return self._run_irt_diagnosis(data, model_name)
        elif 'ncd' in model_name_lower:
            # 使用NCD模型（目前使用简单方法，后续可扩展）
            return self._run_simple_diagnosis(data, model_name)
        else:
            # 默认使用简单诊断
            return self._run_simple_diagnosis(data, model_name)

    def _run_irt_diagnosis(self, data: Dict, model_name: str) -> Dict[str, Any]:
        """
        使用IRT模型进行诊断

        Args:
            data: 诊断数据
            model_name: 模型名称

        Returns:
            诊断结果
        """
        # 确定IRT模型类型
        if '3pl' in model_name.lower():
            irt_type = '3PL'
        elif '1pl' in model_name.lower():
            irt_type = '1PL'
        else:
            irt_type = '2PL'  # 默认使用2PL

        # 创建IRT诊断服务
        irt_service = IRTDiagnosisService(model_type=irt_type)

        # 运行诊断
        result = irt_service.run_diagnosis(
            students_data=data['students'],
            exercises=data['exercises'],
            knowledge_points=data['knowledge_points'],
            q_matrix=data['Q_matrix']
        )

        if 'error' in result:
            return result

        # 添加额外信息
        result['subject_id'] = data.get('subject_id')
        result['model_type'] = f'IRT-{irt_type}'
        result['knowledge_points'] = [
            {
                'id': kp.id,
                'name': kp.name,
                'subject_id': kp.subject_id
            }
            for kp in data['knowledge_points']
        ]
        result['total_students'] = len(data['students'])
        result['diagnosed_students'] = len(result.get('diagnosis_results', {}))
        result['diagnosis_time'] = timezone.now().isoformat()

        return result

    def _run_simple_diagnosis(self, data: Dict, model_name: str) -> Dict[str, Any]:
        """
        使用简单正确率方法进行诊断

        Args:
            data: 诊断数据
            model_name: 模型名称

        Returns:
            诊断结果
        """
        Q = data['Q_matrix']
        knowledge_points = data['knowledge_points']
        students = data['students']

        # 为每个学生计算知识点掌握度
        diagnosis_results = {}

        for student_id, student_info in students.items():
            if not student_info['answer_logs']:
                continue

            # 计算每个知识点的掌握度
            kp_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'weight': 0})

            for log in student_info['answer_logs']:
                ex_idx = log['exercise_idx']
                is_correct = log['is_correct']

                # 获取该习题关联的知识点
                related_kps = np.where(Q[ex_idx] > 0)[0]

                for kp_idx in related_kps:
                    weight = Q[ex_idx, kp_idx]
                    kp_id = knowledge_points[kp_idx].id

                    kp_stats[kp_id]['total'] += 1
                    kp_stats[kp_id]['weight'] += weight
                    if is_correct:
                        kp_stats[kp_id]['correct'] += 1

            # 计算掌握度
            knowledge_mastery = {}
            practice_counts = {}
            correct_counts = {}

            for kp in knowledge_points:
                stats = kp_stats.get(kp.id, {'total': 0, 'correct': 0, 'weight': 0})
                practice_count = stats['total']
                correct_count = stats['correct']

                if practice_count > 0:
                    # 基于正确率的掌握度计算
                    mastery = correct_count / practice_count
                else:
                    mastery = 0.0

                knowledge_mastery[str(kp.id)] = round(mastery, 4)
                practice_counts[str(kp.id)] = practice_count
                correct_counts[str(kp.id)] = correct_count

            # 计算总体掌握度
            if knowledge_mastery:
                overall_score = round(sum(knowledge_mastery.values()) / len(knowledge_mastery), 4)
            else:
                overall_score = 0.0

            # 筛选薄弱知识点（掌握度<0.6）
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
            'subject_id': data.get('subject_id'),
            'model_type': model_name,
            'diagnosis_results': diagnosis_results,
            'knowledge_points': [
                {
                    'id': kp.id,
                    'name': kp.name,
                    'subject_id': kp.subject_id
                }
                for kp in knowledge_points
            ],
            'total_students': len(students),
            'diagnosed_students': len(diagnosis_results),
            'diagnosis_time': timezone.now().isoformat()
        }

    # 保留旧方法名以兼容
    def run_simple_diagnosis(self, subject_id: int, model_type: str = 'simple') -> Dict[str, Any]:
        """兼容旧接口"""
        return self.run_diagnosis(subject_id, model_type)

    def save_student_diagnoses(self, subject_id: int, diagnosis_data: Dict, model_id: int) -> int:
        """
        保存诊断结果到StudentDiagnosis表（优化版本，减少数据库锁定时间）

        Args:
            subject_id: 科目ID
            diagnosis_data: 诊断数据
            model_id: 模型ID

        Returns:
            保存的学生数量（不是记录数量）
        """
        saved_students = set()
        current_time = timezone.now()
        
        # 预先获取所需数据，减少循环中的查询
        subject = Subject.objects.get(id=subject_id)
        diagnosis_model = DiagnosisModel.objects.get(id=model_id)
        
        # 获取所有知识点，建立ID映射
        knowledge_points = {
            kp.id: kp for kp in KnowledgePoint.objects.filter(subject=subject)
        }
        
        # 获取所有相关学生
        student_ids = [int(sid) for sid in diagnosis_data.get('diagnosis_results', {}).keys()]
        students = {
            s.id: s for s in User.objects.filter(id__in=student_ids, user_type='student')
        }
        
        # 批量准备数据
        records_to_update = []
        
        for student_id_str, result_data in diagnosis_data.get('diagnosis_results', {}).items():
            student_id = int(student_id_str)
            student = students.get(student_id)
            if not student:
                continue
                
            for kp_str, mastery in result_data['knowledge_mastery'].items():
                kp_id = int(kp_str)
                knowledge_point = knowledge_points.get(kp_id)
                if not knowledge_point:
                    continue
                    
                practice_count = result_data['practice_counts'].get(kp_str, 0)
                correct_count = result_data['correct_counts'].get(kp_str, 0)
                
                records_to_update.append({
                    'student': student,
                    'knowledge_point': knowledge_point,
                    'mastery': mastery,
                    'practice_count': practice_count,
                    'correct_count': correct_count
                })
                saved_students.add(student_id)
        
        # 分批保存，每批50条，减少单次事务时间
        batch_size = 50
        for i in range(0, len(records_to_update), batch_size):
            batch = records_to_update[i:i + batch_size]
            with transaction.atomic():
                for record in batch:
                    StudentDiagnosis.objects.update_or_create(
                        student=record['student'],
                        knowledge_point=record['knowledge_point'],
                        diagnosis_model=diagnosis_model,
                        defaults={
                            'mastery_level': record['mastery'],
                            'practice_count': record['practice_count'],
                            'correct_count': record['correct_count'],
                            'last_practiced': current_time
                        }
                    )
        
        return len(saved_students)

    def get_student_diagnosis_history(self, student_id: int, subject_id: int) -> List[Dict]:
        """获取学生诊断历史"""
        return StudentDiagnosis.objects.filter(
            student_id=student_id,
            knowledge_point__subject_id=subject_id
        ).select_related('knowledge_point', 'diagnosis_model').order_by('-last_practiced')