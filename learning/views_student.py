from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
import json
from itertools import groupby
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm


def is_teacher(user):
    return user.user_type == 'teacher'


def is_student(user):
    return user.user_type == 'student'


@login_required
def dashboard(request):
    if request.user.user_type == 'teacher':
        return redirect('teacher_dashboard')
    else:
        return redirect('student_dashboard')


@login_required
@user_passes_test(is_student)
def student_dashboard(request):
    subjects = Subject.objects.all()
    subjects = Subject.objects.all()
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:5]

    # 计算总体掌握情况
    total_diagnosis = StudentDiagnosis.objects.filter(student=request.user)
    if total_diagnosis.exists():
        avg_mastery = total_diagnosis.aggregate(avg=Avg('mastery_level'))['avg']
    else:
        avg_mastery = 0

    return render(request, 'learning/student_dashboard.html', {
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': subjects.first()
    })

#课程栏
@login_required
@user_passes_test(is_student)
def student_subject(request):
    subjects = Subject.objects.all()
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:5]

    # 计算总体掌握情况
    total_diagnosis = StudentDiagnosis.objects.filter(student=request.user)
    if total_diagnosis.exists():
        avg_mastery = total_diagnosis.aggregate(avg=Avg('mastery_level'))['avg']
    else:
        avg_mastery = 0

    return render(request, 'learning/subject.html', {
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': subjects.first()
    })

@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    subjects = Subject.objects.all()
    total_exercises = Exercise.objects.filter(created_by=request.user).count()
    total_knowledge_points = KnowledgePoint.objects.count()

    return render(request, 'learning/teacher_dashboard.html', {
        'subjects': subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
    })


@login_required
@user_passes_test(is_student)
def exercise_list(request, subject_id):
    """习题列表页面"""
    subject = get_object_or_404(Subject, id=subject_id)
    # exercises = Exercise.objects.filter(subject=subject, )
    exercises = Exercise.objects.filter(subject_id=subject_id).order_by('title', 'id')
    subjects = Subject.objects.all()  # 所有科目用于侧边栏

    # 获取学生的学习进度
    completed_exercises = AnswerLog.objects.filter(
        student=request.user,
        exercise__in=exercises
    ).values_list('exercise_id', flat=True)

    # 标记已完成的习题
    for exercise in exercises:
        exercise.completed = exercise.id in completed_exercises

    # 计算进度
    progress = {
        'total': exercises.count(),
        'completed': len(completed_exercises),
        'percentage': round((len(completed_exercises) / exercises.count() * 100) if exercises.count() > 0 else 0, 1)
    }

    # 获取知识点统计
    knowledge_points = KnowledgePoint.objects.filter(subject=subject)
    for kp in knowledge_points:
        kp.exercise_count = Exercise.objects.filter(
            subject=subject,
            qmatrix__knowledge_point=kp
        ).distinct().count()
        # 简化掌握度计算（实际应该基于答题记录）
        kp.mastery_percentage = min(100, kp.exercise_count * 20)

    # 按title分组
    grouped_exercises = []
    for title, group in groupby(exercises, key=lambda x: x.title):
        exercises_list = list(group)
        grouped_exercises.append({
            'title': title,
            'exercises': exercises_list,
            'exercise_count': len(exercises_list),
            'completed': all(ex.completed for ex in exercises_list)  # 假设有completed字段
        })

    return render(request, 'learning/exercise_list.html', {
        'subject': subject,
        'subjects': subjects,
        'exercises': exercises,
        'progress': progress,
        'knowledge_points': knowledge_points,
        'grouped_exercises':grouped_exercises

    })


@login_required
@user_passes_test(is_student)
def take_exercise(request, exercise_id):
    """答题页面"""
    exercise = get_object_or_404(Exercise, id=exercise_id)

    if request.method == 'POST':
        # 处理答题提交
        selected_choice_ids = request.POST.getlist('choices')
        text_answer = request.POST.get('text_answer', '')
        time_spent = request.POST.get('time_spent', 0)

        # 创建答题记录
        answer_log = AnswerLog.objects.create(
            student=request.user,
            exercise=exercise,
            text_answer=text_answer,
            time_spent=time_spent
        )

        # 处理选择题
        if exercise.question_type in ['single', 'multiple']:
            selected_choices = Choice.objects.filter(id__in=selected_choice_ids)
            answer_log.selected_choices.set(selected_choices)

            # 判断是否正确
            correct_choices = set(exercise.choices.filter(is_correct=True))
            selected_choices_set = set(selected_choices)
            answer_log.is_correct = correct_choices == selected_choices_set

        answer_log.save()

        # 更新知识点掌握情况
        update_knowledge_mastery(request.user, exercise, answer_log.is_correct)

        return redirect('exercise_result', log_id=answer_log.id)

    return render(request, 'learning/take_exercise.html', {
        'exercise': exercise
    })


@login_required
@user_passes_test(is_student)
def exercise_result(request, log_id):
    """答题结果页面"""
    answer_log = get_object_or_404(AnswerLog, id=log_id, student=request.user)
    current_exercise = answer_log.exercise
    current_subject = current_exercise.subject
    current_title = current_exercise.title
    # 获取用户选择的选项ID列表
    selected_choice_ids = list(answer_log.selected_choices.values_list('id', flat=True))

    # 查找同科目中下一题（按ID顺序，未完成的优先）
    # 1. 先找同科目中ID大于当前题且未完成的
    next_exercise = Exercise.objects.filter(
        subject=current_subject,
        title=current_title,
        id__gt=current_exercise.id  # ID比当前题大（保证顺序）
    ).first()

    return render(request, 'learning/exercise_result.html', {
        'answer_log': answer_log,
        'selected_choice_ids': selected_choice_ids,
        'next_exercise': next_exercise
    })



@login_required
@user_passes_test(is_student)
def student_diagnosis(request):
    # 获取学生的知识点掌握情况
    diagnoses = StudentDiagnosis.objects.filter(student=request.user).select_related('knowledge_point')

    # 按科目分组
    subjects = {}
    for diagnosis in diagnoses:
        subject_name = diagnosis.knowledge_point.subject.name
        if subject_name not in subjects:
            subjects[subject_name] = []
        subjects[subject_name].append(diagnosis)

    # 计算推荐学习路径
    weak_points = diagnoses.filter(mastery_level__lt=0.6).order_by('mastery_level')[:5]

    return render(request, 'learning/student_diagnosis.html', {
        'subjects': subjects,
        'weak_points': weak_points
    })


@login_required
@user_passes_test(is_student)
def knowledge_points(request, subject_id):
    subject = get_object_or_404(Subject, id=subject_id)
    knowledge_points = KnowledgePoint.objects.filter(subject=subject)

    # 获取学生掌握情况
    diagnoses = StudentDiagnosis.objects.filter(
        student=request.user,
        knowledge_point__in=knowledge_points
    )

    mastery_dict = {d.knowledge_point_id: d.mastery_level for d in diagnoses}

    for kp in knowledge_points:
        kp.mastery_level = mastery_dict.get(kp.id, 0)

    return render(request, 'learning/knowledge_points.html', {
        'subject': subject,
        'knowledge_points': knowledge_points
    })


@login_required
@user_passes_test(is_teacher)
def upload_exercise(request):
    if request.method == 'POST':
        form = ExerciseForm(request.POST)
        if form.is_valid():
            exercise = form.save(commit=False)
            exercise.created_by = request.user
            exercise.save()

            # 处理选项
            choices_data = json.loads(request.POST.get('choices_data', '[]'))
            for choice_data in choices_data:
                Choice.objects.create(
                    exercise=exercise,
                    content=choice_data['content'],
                    is_correct=choice_data['is_correct'],
                    order=choice_data['order']
                )

            messages.success(request, '习题上传成功！')
            return redirect('upload_exercise')
    else:
        form = ExerciseForm()

    return render(request, 'learning/upload_exercise.html', {
        'form': form
    })


@login_required
@user_passes_test(is_teacher)
def upload_knowledge(request):
    if request.method == 'POST':
        form = KnowledgePointForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '知识点上传成功！')
            return redirect('upload_knowledge')
    else:
        form = KnowledgePointForm()

    return render(request, 'learning/upload_knowledge.html', {
        'form': form
    })


@login_required
@user_passes_test(is_teacher)
def q_matrix_management(request):
    if request.method == 'POST':
        form = QMatrixForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Q矩阵关系添加成功！')
            return redirect('q_matrix_management')
    else:
        form = QMatrixForm()

    q_matrix = QMatrix.objects.all().select_related('exercise', 'knowledge_point')

    return render(request, 'learning/q_matrix.html', {
        'form': form,
        'q_matrix': q_matrix
    })


def update_knowledge_mastery(student, exercise, is_correct):
    """更新学生对知识点的掌握程度"""
    related_kps = QMatrix.objects.filter(exercise=exercise).select_related('knowledge_point')

    for q_item in related_kps:
        diagnosis, created = StudentDiagnosis.objects.get_or_create(
            student=student,
            knowledge_point=q_item.knowledge_point
        )

        diagnosis.practice_count += 1
        if is_correct:
            diagnosis.correct_count += 1

        diagnosis.calculate_mastery()