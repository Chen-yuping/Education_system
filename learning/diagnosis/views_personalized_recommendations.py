# views_personalized_recommendations.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q, Count
import random
from ..models import *


def is_student(user):
    return user.user_type == 'student'


@login_required
@user_passes_test(is_student)
def personalized_recommendations(request, subject_id=None):
    """
    个性化习题推荐页面 - 推荐10个题目
    """
    # 1. 获取学生已选科目
    enrolled_subjects = StudentSubject.objects.filter(
        student=request.user
    ).select_related('subject')

    # 如果没有科目，返回提示
    if not enrolled_subjects.exists():
        return render(request, 'student/no_subjects.html')

    # 2. 如果没有指定科目，使用第一个已选科目
    if not subject_id:
        # 重定向到有科目ID的URL
        first_subject = enrolled_subjects.first().subject
        return redirect('personalized_recommendations', subject_id=first_subject.id)

    # 3. 获取当前科目
    current_subject = get_object_or_404(Subject, id=subject_id)

    # 4. 检查学生是否选修该科目
    if not StudentSubject.objects.filter(student=request.user, subject=current_subject).exists():
        return render(request, 'student/access_denied.html')

    # 5. 获取推荐题目（10个）
    recommended_exercises = get_10_recommended_exercises(request.user, current_subject)

    # 6. 获取学生的薄弱知识点（用于显示）
    weak_points = StudentDiagnosis.objects.filter(
        student=request.user,
        knowledge_point__subject=current_subject,
        mastery_level__lt=0.6
    ).select_related('knowledge_point').order_by('mastery_level')[:5]

    # 7. 准备上下文
    context = {
        'subjects': enrolled_subjects,
        'current_subject': current_subject,
        'subject': current_subject,  # 添加这个以保持与其他页面一致
        'exercises': recommended_exercises,
        'weak_points': weak_points,
        'title': '个性化推荐习题',
    }

    return render(request, 'student/personalized_recommendations.html', context)


def get_10_recommended_exercises(student, subject):
    """
    获取10个推荐题目的核心函数
    """
    # 1. 获取学生已经做过的题目ID
    answered_exercise_ids = AnswerLog.objects.filter(
        student=student,
        exercise__subject=subject
    ).values_list('exercise_id', flat=True).distinct()

    exercises = []

    # 2. 获取薄弱知识点相关题目（最多5个）
    weak_exercises = get_weak_knowledge_exercises(
        student=student,
        subject=subject,
        answered_exercise_ids=answered_exercise_ids,
        limit=5
    )
    exercises.extend(weak_exercises)

    # 3. 获取未做过的题目补足到10个
    if len(exercises) < 10:
        new_limit = 10 - len(exercises)
        new_exercises = get_new_exercises(
            subject=subject,
            answered_exercise_ids=answered_exercise_ids,
            exclude_ids=[e.id for e in exercises],
            limit=new_limit
        )
        exercises.extend(new_exercises)

    # 4. 如果还不够，获取做错过的题目
    if len(exercises) < 10:
        remaining_limit = 10 - len(exercises)
        wrong_exercises = get_wrong_exercises(
            student=student,
            subject=subject,
            exclude_ids=[e.id for e in exercises],
            limit=remaining_limit
        )
        exercises.extend(wrong_exercises)

    return exercises[:10]


def get_weak_knowledge_exercises(student, subject, answered_exercise_ids, limit=5):
    """
    获取薄弱知识点相关题目
    """
    # 1. 获取学生的薄弱知识点ID（掌握程度<60%）
    weak_knowledge_ids = StudentDiagnosis.objects.filter(
        student=student,
        knowledge_point__subject=subject,
        mastery_level__lt=0.6
    ).values_list('knowledge_point_id', flat=True)

    if not weak_knowledge_ids:
        return []

    # 2. 获取这些薄弱知识点相关的习题
    exercises = Exercise.objects.filter(
        subject=subject,
        qmatrix__knowledge_point_id__in=weak_knowledge_ids
    ).exclude(
        id__in=answered_exercise_ids
    ).distinct()

    if not exercises.exists():
        return []

    # 3. 优先选择关联薄弱知识点多的题目
    # 计算每个题目关联的薄弱知识点数量
    exercise_weak_count = {}
    for exercise in exercises:
        weak_count = exercise.qmatrix_set.filter(
            knowledge_point_id__in=weak_knowledge_ids
        ).count()
        exercise_weak_count[exercise.id] = weak_count

    # 4. 按薄弱知识点数量排序，取前limit个
    sorted_exercise_ids = sorted(
        exercise_weak_count.keys(),
        key=lambda x: exercise_weak_count[x],
        reverse=True
    )[:limit]

    # 5. 保持排序查询
    id_order = {exercise_id: i for i, exercise_id in enumerate(sorted_exercise_ids)}
    exercises_list = list(Exercise.objects.filter(id__in=sorted_exercise_ids))
    exercises_list.sort(key=lambda x: id_order.get(x.id, 999))

    return exercises_list


def get_new_exercises(subject, answered_exercise_ids, exclude_ids=None, limit=5):
    """
    获取未做过的题目
    """
    exclude_ids = exclude_ids or []

    exercises = Exercise.objects.filter(
        subject=subject
    ).exclude(
        id__in=answered_exercise_ids
    ).exclude(
        id__in=exclude_ids
    ).order_by('?')[:limit]  # 随机取

    return exercises


def get_wrong_exercises(student, subject, exclude_ids=None, limit=5):
    """
    获取做错过的题目
    """
    exclude_ids = exclude_ids or []

    # 获取做错的题目ID
    wrong_exercise_ids = AnswerLog.objects.filter(
        student=student,
        exercise__subject=subject,
        is_correct=False
    ).values_list('exercise_id', flat=True).distinct()

    if not wrong_exercise_ids:
        return []

    exercises = Exercise.objects.filter(
        subject=subject,
        id__in=wrong_exercise_ids
    ).exclude(
        id__in=exclude_ids
    ).order_by('?')[:limit]

    return exercises


@login_required
@user_passes_test(is_student)
def start_recommended_exercise(request, exercise_id):
    """
    开始做推荐的题目
    """
    # 直接重定向到你现有的答题页面
    return redirect('take_exercise', exercise_id=exercise_id)


@login_required
@user_passes_test(is_student)
def recommendation_result(request, subject_id):
    """
    推荐流程完成页面
    """
    subject = get_object_or_404(Subject, id=subject_id)

    # 检查学生是否选修该科目
    if not StudentSubject.objects.filter(student=request.user, subject=subject).exists():
        return render(request, 'student/access_denied.html')

    # 获取学生最近完成的题目（最后10个）
    recent_logs = AnswerLog.objects.filter(
        student=request.user,
        exercise__subject=subject
    ).select_related('exercise').order_by('-submitted_at')[:10]

    # 统计正确率
    total_count = recent_logs.count()
    correct_count = recent_logs.filter(is_correct=True).count()

    # 计算正确率百分比
    correct_rate = (correct_count / total_count * 100) if total_count > 0 else 0

    context = {
        'subject': subject,
        'recent_logs': recent_logs,
        'total_count': total_count,
        'correct_count': correct_count,
        'correct_rate': correct_rate,
    }

    return render(request, 'student/recommendation_result.html', context)