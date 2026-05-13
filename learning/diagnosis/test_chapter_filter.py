"""
章节过滤功能的测试文件
测试学生已学过章节的知识点优先推荐
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from learning.models import (
    Subject, KnowledgePoint, KnowledgeGraph, Exercise, QMatrix,
    StudentDiagnosis, AnswerLog, DiagnosisModel, StudentSubject
)
from learning.diagnosis.views_personalized_recommendations import (
    get_student_learned_chapters,
    get_knowledge_point_chapter,
    get_weak_knowledge_exercises
)

User = get_user_model()


class GetStudentLearnedChaptersTestCase(TestCase):
    """测试 get_student_learned_chapters 函数"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建学生
        self.student = User.objects.create_user(
            username='testuser',
            password='testpass',
            user_type='student'
        )
        
        # 创建题目（不同章节）
        self.exercise_ch1 = Exercise.objects.create(
            subject=self.subject,
            title="第1章题目",
            content="内容",
            problemsets="chapter_1"
        )
        self.exercise_ch2 = Exercise.objects.create(
            subject=self.subject,
            title="第2章题目",
            content="内容",
            problemsets="chapter_2"
        )
        self.exercise_ch3 = Exercise.objects.create(
            subject=self.subject,
            title="第3章题目",
            content="内容",
            problemsets="chapter_3"
        )
        self.exercise_ch5 = Exercise.objects.create(
            subject=self.subject,
            title="第5章题目",
            content="内容",
            problemsets="chapter_5"
        )
    
    def test_no_answer_logs(self):
        """测试没有答题记录的情况"""
        max_chapter = get_student_learned_chapters(self.student, self.subject)
        self.assertEqual(max_chapter, 0)
    
    def test_single_chapter(self):
        """测试只做过一个章节的题目"""
        # 学生做过第1章的题目
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch1,
            subject=self.subject,
            is_correct=True
        )
        
        max_chapter = get_student_learned_chapters(self.student, self.subject)
        self.assertEqual(max_chapter, 1)
    
    def test_multiple_chapters(self):
        """测试做过多个章节的题目"""
        # 学生做过第1、2、3章的题目
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch1,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch2,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch3,
            subject=self.subject,
            is_correct=True
        )
        
        max_chapter = get_student_learned_chapters(self.student, self.subject)
        self.assertEqual(max_chapter, 3)
    
    def test_non_sequential_chapters(self):
        """测试做过非连续章节的题目"""
        # 学生做过第1、3、5章的题目
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch1,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch3,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_ch5,
            subject=self.subject,
            is_correct=True
        )
        
        max_chapter = get_student_learned_chapters(self.student, self.subject)
        self.assertEqual(max_chapter, 5)


class GetKnowledgePointChapterTestCase(TestCase):
    """测试 get_knowledge_point_chapter 函数"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建科目
        self.subject = Subject.objects.create(name="数学")
        
        # 创建知识点
        self.kp_linear = KnowledgePoint.objects.create(
            subject=self.subject,
            name="一次方程"
        )
        
        # 创建题目（不同章节）
        self.exercise_ch1 = Exercise.objects.create(
            subject=self.subject,
            title="第1章题目",
            content="内容",
            problemsets="chapter_1"
        )
        self.exercise_ch2 = Exercise.objects.create(
            subject=self.subject,
            title="第2章题目",
            content="内容",
            problemsets="chapter_2"
        )
        self.exercise_ch2_2 = Exercise.objects.create(
            subject=self.subject,
            title="第2章题目2",
            content="内容",
            problemsets="chapter_2"
        )
        
        # 创建Q矩阵关系
        QMatrix.objects.create(exercise=self.exercise_ch1, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_ch2, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_ch2_2, knowledge_point=self.kp_linear)
    
    def test_single_chapter(self):
        """测试知识点只在一个章节的情况"""
        chapter = get_knowledge_point_chapter(self.kp_linear, self.subject)
        # 应该返回出现最频繁的章节（第2章出现2次）
        self.assertEqual(chapter, 2)
    
    def test_no_exercises(self):
        """测试知识点没有相关题目的情况"""
        # 创建一个没有题目的知识点
        kp_empty = KnowledgePoint.objects.create(
            subject=self.subject,
            name="空知识点"
        )
        
        chapter = get_knowledge_point_chapter(kp_empty, self.subject)
        self.assertEqual(chapter, 0)


class GetWeakKnowledgeExercisesWithChapterFilterTestCase(TestCase):
    """测试带章节过滤的推荐算法"""
    
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
        
        # 创建题目（不同章节）
        # 第1章：基本运算
        self.exercise_basic_1 = Exercise.objects.create(
            subject=self.subject,
            title="基本运算题1",
            content="内容",
            problemsets="chapter_1"
        )
        self.exercise_basic_2 = Exercise.objects.create(
            subject=self.subject,
            title="基本运算题2",
            content="内容",
            problemsets="chapter_1"
        )
        
        # 第2章：一次方程
        self.exercise_linear_1 = Exercise.objects.create(
            subject=self.subject,
            title="一次方程题1",
            content="内容",
            problemsets="chapter_2"
        )
        self.exercise_linear_2 = Exercise.objects.create(
            subject=self.subject,
            title="一次方程题2",
            content="内容",
            problemsets="chapter_2"
        )
        
        # 第3章：二次方程
        self.exercise_quadratic_1 = Exercise.objects.create(
            subject=self.subject,
            title="二次方程题1",
            content="内容",
            problemsets="chapter_3"
        )
        self.exercise_quadratic_2 = Exercise.objects.create(
            subject=self.subject,
            title="二次方程题2",
            content="内容",
            problemsets="chapter_3"
        )
        
        # 第4章：因式分解
        self.exercise_factorization_1 = Exercise.objects.create(
            subject=self.subject,
            title="因式分解题1",
            content="内容",
            problemsets="chapter_4"
        )
        self.exercise_factorization_2 = Exercise.objects.create(
            subject=self.subject,
            title="因式分解题2",
            content="内容",
            problemsets="chapter_4"
        )
        
        # 创建Q矩阵关系
        QMatrix.objects.create(exercise=self.exercise_basic_1, knowledge_point=self.kp_basic)
        QMatrix.objects.create(exercise=self.exercise_basic_2, knowledge_point=self.kp_basic)
        QMatrix.objects.create(exercise=self.exercise_linear_1, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_linear_2, knowledge_point=self.kp_linear)
        QMatrix.objects.create(exercise=self.exercise_quadratic_1, knowledge_point=self.kp_quadratic)
        QMatrix.objects.create(exercise=self.exercise_quadratic_2, knowledge_point=self.kp_quadratic)
        QMatrix.objects.create(exercise=self.exercise_factorization_1, knowledge_point=self.kp_factorization)
        QMatrix.objects.create(exercise=self.exercise_factorization_2, knowledge_point=self.kp_factorization)
        
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
        StudentDiagnosis.objects.create(
            student=self.student,
            knowledge_point=self.kp_factorization,
            mastery_level=0.55,
            diagnosis_model=self.diagnosis_model
        )
    
    def test_prioritize_learned_chapters(self):
        """测试优先推荐已学过章节的知识点"""
        # 学生做过第1、2、3章的题目
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_basic_1,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_linear_1,
            subject=self.subject,
            is_correct=True
        )
        AnswerLog.objects.create(
            student=self.student,
            exercise=self.exercise_quadratic_1,
            subject=self.subject,
            is_correct=True
        )
        
        answered_exercise_ids = [
            self.exercise_basic_1.id,
            self.exercise_linear_1.id,
            self.exercise_quadratic_1.id
        ]
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=5
        )
        
        # 验证推荐结果
        self.assertGreater(len(exercises), 0)
        
        # 应该优先推荐已学过章节的题目
        # 已学过章节：1、2、3
        # 薄弱知识点：一次方程(2)、二次方程(3)、因式分解(4)
        # 应该优先推荐一次方程和二次方程的题目
        exercise_ids = [e.id for e in exercises]
        
        # 验证推荐的题目中包含已学过章节的知识点
        learned_chapter_exercises = [
            self.exercise_linear_2.id,
            self.exercise_quadratic_2.id
        ]
        
        # 至少应该推荐一个已学过章节的题目
        self.assertTrue(
            any(ex_id in exercise_ids for ex_id in learned_chapter_exercises),
            "应该推荐已学过章节的题目"
        )
    
    def test_no_answer_logs(self):
        """测试没有答题记录的情况"""
        answered_exercise_ids = []
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=5
        )
        
        # 验证推荐结果
        self.assertGreater(len(exercises), 0)
        # 没有答题记录时，应该推荐所有薄弱知识点的题目


class IntegrationTestWithChapterFilterTestCase(TestCase):
    """集成测试：验证章节过滤功能的完整流程"""
    
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
        for chapter in range(1, 6):
            for i in range(3):
                ex = Exercise.objects.create(
                    subject=self.subject,
                    title=f"第{chapter}章题目{i}",
                    content="内容",
                    problemsets=f"chapter_{chapter}"
                )
                self.exercises.append(ex)
                
                # 分配知识点
                if chapter == 1:
                    QMatrix.objects.create(exercise=ex, knowledge_point=self.kp_basic)
                elif chapter == 2:
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
    
    def test_chapter_filter_integration(self):
        """测试章节过滤功能的完整流程"""
        # 学生做过第1、2章的题目
        for i in range(2):
            AnswerLog.objects.create(
                student=self.student,
                exercise=self.exercises[i],
                subject=self.subject,
                is_correct=True
            )
            AnswerLog.objects.create(
                student=self.student,
                exercise=self.exercises[3 + i],
                subject=self.subject,
                is_correct=True
            )
        
        answered_exercise_ids = [self.exercises[i].id for i in range(2)] + \
                                [self.exercises[3 + i].id for i in range(2)]
        
        exercises = get_weak_knowledge_exercises(
            self.student,
            self.subject,
            answered_exercise_ids,
            limit=10
        )
        
        # 验证推荐结果
        self.assertEqual(len(exercises), 10)
        
        # 验证推荐的题目都是有效的
        for exercise in exercises:
            self.assertIsNotNone(exercise)
            self.assertEqual(exercise.subject, self.subject)
