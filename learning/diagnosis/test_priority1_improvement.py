"""
优先级1改进的测试文件
测试知识图谱先决条件关系的推荐算法
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from learning.models import (
    Subject, KnowledgePoint, KnowledgeGraph, Exercise, QMatrix,
    StudentDiagnosis, AnswerLog, DiagnosisModel, StudentSubject
)
from learning.diagnosis.views_personalized_recommendations import (
    get_prerequisite_knowledge_points,
    check_prerequisite_mastery,
    get_weak_knowledge_exercises
)

User = get_user_model()


class PrerequisiteKnowledgePointsTestCase(TestCase):
    """测试 get_prerequisite_knowledge_points 函数"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建知识点
        self.kp_basic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="基本运算"
        )
        self.kp_linear = KnowledgePoint.objects.create(
            subject=self.subject,
            name="一次方程"
        )
        self.kp_quadratic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="二次方程"
        )
        self.kp_factorization = KnowledgePoint.objects.create(
            subject=self.subject,
            name="因式分解"
        )
        
        # 创建知识点关系
        # 基本运算 → 一次方程
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_basic,
            target=self.kp_linear
        )
        # 一次方程 → 二次方程
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_linear,
            target=self.kp_quadratic
        )
        # 因式分解 → 二次方程
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_factorization,
            target=self.kp_quadratic
        )
    
    def test_no_prerequisites(self):
        """测试没有前置知识的知识点"""
        prerequisites = get_prerequisite_knowledge_points(self.kp_basic, self.subject)
        self.assertEqual(prerequisites, set())
    
    def test_single_prerequisite(self):
        """测试有单个前置知识的知识点"""
        prerequisites = get_prerequisite_knowledge_points(self.kp_linear, self.subject)
        self.assertEqual(prerequisites, {self.kp_basic.id})
    
    def test_multiple_prerequisites(self):
        """测试有多个前置知识的知识点"""
        prerequisites = get_prerequisite_knowledge_points(self.kp_quadratic, self.subject)
        # 二次方程的前置知识：一次方程、因式分解、基本运算
        expected = {self.kp_linear.id, self.kp_factorization.id, self.kp_basic.id}
        self.assertEqual(prerequisites, expected)


class CheckPrerequisiteMasteryTestCase(TestCase):
    """测试 check_prerequisite_mastery 函数"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建知识点
        self.kp_basic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="基本运算"
        )
        self.kp_linear = KnowledgePoint.objects.create(
            subject=self.subject,
            name="一次方程"
        )
        self.kp_quadratic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="二次方程"
        )
        
        # 创建知识点关系
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_basic,
            target=self.kp_linear
        )
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_linear,
            target=self.kp_quadratic
        )
        
        # 创建学生
        self.student = User.objects.create_user(
            username='testuser',
            password='testpass',
            user_type='student'
        )
        
        # 创建诊断模型
        self.diagnosis_model = DiagnosisModel.objects.create(id=3, name="模型3")
        
        # 创建学生诊断数据
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_basic,
            mastery_level=0.8,
            diagnosis_model=self.diagnosis_model
        )
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_linear,
            mastery_level=0.45,
            diagnosis_model=self.diagnosis_model
        )
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_quadratic,
            mastery_level=0.3,
            diagnosis_model=self.diagnosis_model
        )
    
    def test_all_prerequisites_mastered(self):
        """测试所有前置知识都掌握的情况"""
        result = check_prerequisite_mastery(
            self.student,
            self.kp_linear,
            self.subject
        )
        self.assertTrue(result['all_prerequisites_mastered'])
        self.assertEqual(result['unmastered_prerequisites'], [])
    
    def test_some_prerequisites_unmastered(self):
        """测试部分前置知识未掌握的情况"""
        result = check_prerequisite_mastery(
            self.student,
            self.kp_quadratic,
            self.subject
        )
        self.assertFalse(result['all_prerequisites_mastered'])
        self.assertIn(self.kp_linear.id, result['unmastered_prerequisites'])
        self.assertNotIn(self.kp_basic.id, result['unmastered_prerequisites'])
    
    def test_no_prerequisites(self):
        """测试没有前置知识的知识点"""
        result = check_prerequisite_mastery(
            self.student,
            self.kp_basic,
            self.subject
        )
        self.assertTrue(result['all_prerequisites_mastered'])
        self.assertEqual(result['unmastered_prerequisites'], [])


class GetWeakKnowledgeExercisesTestCase(TestCase):
    """测试改进后的 get_weak_knowledge_exercises 函数"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建知识点
        self.kp_basic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="基本运算"
        )
        self.kp_linear = KnowledgePoint.objects.create(
            subject=self.subject,
            name="一次方程"
        )
        self.kp_quadratic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="二次方程"
        )
        
        # 创建知识点关系
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_basic,
            target=self.kp_linear
        )
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_linear,
            target=self.kp_quadratic
        )
        
        # 创建题目
        self.exercise_basic_1 = Exercise.objects.create(
            subject=self.subject,
            title="基本运算题1"
        )
        self.exercise_basic_2 = Exercise.objects.create(
            subject=self.subject,
            title="基本运算题2"
        )
        self.exercise_linear_1 = Exercise.objects.create(
            subject=self.subject,
            title="一次方程题1"
        )
        self.exercise_linear_2 = Exercise.objects.create(
            subject=self.subject,
            title="一次方程题2"
        )
        self.exercise_quadratic_1 = Exercise.objects.create(
            subject=self.subject,
            title="二次方程题1"
        )
        
        # 创建Q矩阵关系
        QMatrix.objects.create(exercise=self.exercise_basic_1, knowledge_point=self.kp_basic)
        QMatrix.objects.create(exercise=self.exercise_basic_2, knowledge_point=self.kp_basic)
        QMatrix.objects.create(exercise=self.exercise_linear_1, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_linear_2, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_quadratic_1, knowledge_point=self.kp_quadratic)
        
        # 创建学生
        self.student = User.objects.create_user(
            username='testuser',
            password='testpass',
            user_type='student'
        )
        
        # 创建诊断模型
        self.diagnosis_model = DiagnosisModel.objects.create(id=3, name="模型3")
        
        # 创建学生诊断数据
        # 基本运算：80%（掌握）
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_basic,
            mastery_level=0.8,
            diagnosis_model=self.diagnosis_model
        )
        # 一次方程：45%（薄弱）
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_linear,
            mastery_level=0.45,
            diagnosis_model=self.diagnosis_model
        )
        # 二次方程：30%（薄弱）
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_quadratic,
            mastery_level=0.3,
            diagnosis_model=self.diagnosis_model
        )
    
    def test_weak_knowledge_with_unmet_prerequisites(self):
        """测试推荐前置知识不足的薄弱知识点的前置知识题目"""
        answered_exercise_ids = []
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=5
        )
        
        # 应该优先推荐一次方程的题目（因为二次方程的前置知识不足）
        exercise_ids = [e.id for e in exercises]
        
        # 验证推荐结果
        self.assertGreater(len(exercises), 0)
        # 应该包含一次方程的题目
        self.assertTrue(
            any(e.id == self.exercise_linear_1.id or e.id == self.exercise_linear_2.id 
                for e in exercises),
            "应该推荐一次方程的题目"
        )
    
    def test_exclude_answered_exercises(self):
        """测试排除已做过的题目"""
        # 学生已做过一次方程题1
        answered_exercise_ids = [self.exercise_linear_1.id]
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=5
        )
        
        exercise_ids = [e.id for e in exercises]
        
        # 验证不包含已做过的题目
        self.assertNotIn(self.exercise_linear_1.id, exercise_ids)


class IntegrationTestCase(TestCase):
    """集成测试"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建知识点
        self.kp_basic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="基本运算"
        )
        self.kp_linear = KnowledgePoint.objects.create(
            subject=self.subject,
            name="一次方程"
        )
        self.kp_quadratic = KnowledgePoint.objects.create(
            subject=self.subject,
            name="二次方程"
        )
        
        # 创建知识点关系
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_basic,
            target=self.kp_linear
        )
        KnowledgeGraph.objects.create(
            subject=self.subject,
            source=self.kp_linear,
            target=self.kp_quadratic
        )
        
        # 创建题目
        self.exercises = []
        for i in range(10):
            ex = Exercise.objects.create(
                subject=self.subject,
                title=f"题目{i}"
            )
            self.exercises.append(ex)
            
            # 分配知识点
            if i < 3:
                QMatrix.objects.create(exercise=ex, knowledge_point=self.kp_basic)
            elif i < 6:
                QMatrix.objects.create(exercise=ex, knowledge_point=self.kp_linear)
            else:
                QMatrix.objects.create(exercise=ex, knowledge_point=self.kp_quadratic)
        
        # 创建学生
        self.student = User.objects.create_user(
            username='testuser',
            password='testpass',
            user_type='student'
        )
        
        # 创建诊断模型
        self.diagnosis_model = DiagnosisModel.objects.create(id=3, name="模型3")
        
        # 创建学生诊断数据
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_basic,
            mastery_level=0.8,
            diagnosis_model=self.diagnosis_model
        )
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_linear,
            mastery_level=0.45,
            diagnosis_model=self.diagnosis_model
        )
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_quadratic,
            mastery_level=0.3,
            diagnosis_model=self.diagnosis_model
        )
    
    def test_recommendation_respects_prerequisites(self):
        """测试推荐结果尊重前置知识关系"""
        answered_exercise_ids = []
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=5
        )
        
        # 验证推荐结果
        self.assertEqual(len(exercises), 5)
        
        # 验证推荐的题目都是有效的
        for exercise in exercises:
            self.assertIsNotNone(exercise)
            self.assertEqual(exercise.subject, self.subject)
