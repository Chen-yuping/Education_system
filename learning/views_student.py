from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
import json
from itertools import groupby
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from .diagnosis.views_diagnosis import knowledge_mastery_diagnoses
from django.utils import timezone
from datetime import timedelta
#登录用户判断
def is_teacher(user):
    return user.user_type == 'teacher'

def is_student(user):
    return user.user_type == 'student'

def is_researcher(user):
    return user.user_type == 'researcher'

@login_required
def dashboard(request):
    if request.user.user_type == 'teacher':
        return redirect('teacher_dashboard')
    if request.user.user_type == 'student':
        return redirect('student_dashboard')
    else:
        return redirect('researcher_dashboard')

#学生学习面板
@login_required
@user_passes_test(is_student)
def student_dashboard(request):
    subjects = Subject.objects.all()
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:5]
    total_answers = AnswerLog.objects.filter(student=request.user).count()
    # 计算总体掌握情况
    total_diagnosis = StudentDiagnosis.objects.filter(student=request.user)
    if total_diagnosis.exists():
        avg_mastery = total_diagnosis.aggregate(avg=Avg('mastery_level'))['avg']
    else:
        avg_mastery = 0

    return render(request, 'student/student_dashboard.html', {
        'total_answers': total_answers,
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': subjects.first()
    })

#所有课程页面显示
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

    return render(request, 'student/subject.html', {
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': subjects.first()
    })

#"""单个课程列表页面"""
@login_required
@user_passes_test(is_student)
def exercise_list(request, subject_id):
    subject = get_object_or_404(Subject, id=subject_id)
    exercises = Exercise.objects.filter(subject_id=subject_id).order_by('problemsets', 'id')
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

    return render(request, 'student/exercise_list.html', {
        'subject': subject,
        'subjects': subjects,
        'exercises': exercises,
        'progress': progress,
        'knowledge_points': knowledge_points,
        'grouped_exercises':grouped_exercises

    })

#"""答题页面，做题页面"""
@login_required
@user_passes_test(is_student)
def take_exercise(request, exercise_id):
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

        # 处理选择题（单选题和多选题）
        if exercise.question_type in ['1', '2']:
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

    return render(request, 'student/take_exercise.html', {
        'exercise': exercise
    })

#"""单个题目答题结果页面"""
@login_required
@user_passes_test(is_student)
def exercise_result(request, log_id):
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

    return render(request, 'student/exercise_result.html', {
        'answer_log': answer_log,
        'selected_choice_ids': selected_choice_ids,
        'next_exercise': next_exercise
    })

# 获取学生的知识点掌握情况，学习诊断页面
@login_required
@user_passes_test(is_student)
def student_diagnosis(request):

    diagnoses = StudentDiagnosis.objects.filter(student=request.user).select_related('knowledge_point')
    answerlog = AnswerLog.objects.filter(student=request.user)

    knowledge_mastery_diagnoses(request.user, answerlog)

    # 按科目分组
    subjects = {}
    for diagnosis in diagnoses:
        subject_name = diagnosis.knowledge_point.subject.name
        if subject_name not in subjects:
            subjects[subject_name] = []
        subjects[subject_name].append(diagnosis)

    # 计算推荐学习路径
    weak_points = diagnoses.filter(mastery_level__lt=0.6).order_by('mastery_level')[:5]
    # 更新知识点掌握情况


    return render(request, 'student/student_diagnosis.html', {
        'subjects': subjects,
        'weak_points': weak_points
    })

#单科目下的做题记录
@login_required
def subject_exercise_logs(request, subject_id):
    """显示科目下所有习题的答题记录"""
    subject = get_object_or_404(Subject, id=subject_id)

    # 计算3个月前的时间点
    three_months_ago = timezone.now() - timedelta(days=90)

    # 获取用户在该科目下的所有答题记录（预加载相关数据）
    answer_logs = AnswerLog.objects.filter(
        student=request.user,
        exercise__subject=subject
    ).select_related('exercise').prefetch_related('selected_choices').order_by('-submitted_at')

    # 统计信息
    total_logs = answer_logs.count()
    correct_logs = answer_logs.filter(is_correct=True).count()
    incorrect_logs = answer_logs.filter(is_correct=False).count()
    unmarked_logs = answer_logs.filter(is_correct__isnull=True).count()

    # 计算正确率
    if total_logs > 0:
        correct_rate = round((correct_logs / total_logs) * 100, 1)
    else:
        correct_rate = 0

    # 获取所有不重复的习题（优化性能）
    exercise_ids = answer_logs.values_list('exercise_id', flat=True).distinct()

    # 预加载习题的选择项
    exercises = Exercise.objects.filter(id__in=exercise_ids).prefetch_related('choices')

    # 为每个习题准备统计数据
    exercises_with_stats = []
    for exercise in exercises:
        # 获取该习题的所有答题记录
        exercise_logs = [log for log in answer_logs if log.exercise.id == exercise.id]

        # 获取最近3个月的答题记录
        recent_logs = [log for log in exercise_logs if log.submitted_at >= three_months_ago][:31]  # 最多显示31个

        # 统计该习题的答题情况
        total_attempts = len(exercise_logs)
        correct_attempts = len([log for log in exercise_logs if log.is_correct is True])

        # 计算正确率
        if total_attempts > 0:
            exercise_correct_rate = round((correct_attempts / total_attempts) * 100, 1)
        else:
            exercise_correct_rate = 0

        # 获取该习题的所有选项
        choices = list(exercise.choices.all().order_by('order'))

        # 准备最近答题记录的数据
        processed_recent_logs = []
        for i, log in enumerate(recent_logs, 1):
            # 获取用户选择的选项
            selected_choices = list(log.selected_choices.all())

            # 获取用户选择的文本
            selected_options_text = []
            for choice in selected_choices:
                selected_options_text.append(choice.content)

            # 获取正确答案
            correct_choices = [c for c in choices if c.is_correct]
            correct_options_text = [c.content for c in correct_choices]

            # 获取所有选项文本
            options_text = [c.content for c in choices]

            # 准备日志数据
            log_data = {
                'id': log.id,
                'is_correct': log.is_correct,
                'submitted_at': log.submitted_at,
                'question_text': exercise.content,
                'selected_option': " | ".join(selected_options_text) if selected_options_text else "未选择",
                'correct_option': " | ".join(correct_options_text) if correct_options_text else "未设置正确答案",
                'options_json': json.dumps(options_text),
            }
            processed_recent_logs.append(log_data)

        exercises_with_stats.append({
            'id': exercise.id,
            'title': exercise.title,
            'points': 20,  # 如果没有points字段，使用默认值20
            'total_attempts': total_attempts,
            'correct_rate': exercise_correct_rate,
            'recent_logs': processed_recent_logs,
        })

    # 按答题次数排序
    exercises_with_stats.sort(key=lambda x: x['total_attempts'], reverse=True)

    # 按习题分组统计（保持原有功能）
    exercise_stats = {}
    for log in answer_logs:
        if log.exercise.id not in exercise_stats:
            exercise_stats[log.exercise.id] = {
                'exercise': log.exercise,
                'total': 0,
                'correct': 0,
                'logs': []
            }
        exercise_stats[log.exercise.id]['total'] += 1
        if log.is_correct:
            exercise_stats[log.exercise.id]['correct'] += 1
        exercise_stats[log.exercise.id]['logs'].append(log)

    for stat in exercise_stats.values():
        if stat['total'] > 0:
            stat['correct_rate'] = round((stat['correct'] / stat['total']) * 100, 1)
        else:
            stat['correct_rate'] = 0

    # 获取知识点掌握情况
    knowledge_stats = StudentDiagnosis.objects.filter(
        student=request.user,
        knowledge_point__subject=subject
    ).select_related('knowledge_point')

    context = {
        'subject': subject,
        'answer_logs': answer_logs,
        'total_logs': total_logs,
        'correct_logs': correct_logs,
        'incorrect_logs': incorrect_logs,
        'unmarked_logs': unmarked_logs,
        'correct_rate': correct_rate,
        'exercise_stats': exercise_stats.values(),
        'knowledge_stats': knowledge_stats,
        'has_data': total_logs > 0,
        'exercises_with_stats': exercises_with_stats,  # 新增的数据
    }

    return render(request, 'student/subject_exercise_logs.html', context)

# 单科目下的学生知识点掌握情况
@login_required
@user_passes_test(is_student)
def student_subject_diagnosis(request, subject_id):  # 添加这个参数
    # 获取科目对象
    subject = get_object_or_404(Subject, id=subject_id)

    # 获取该科目下的知识点诊断
    diagnoses = StudentDiagnosis.objects.filter(
        student=request.user,
        knowledge_point__subject=subject  # 按科目过滤
    ).select_related('knowledge_point')

    # 获取该科目下的答题记录
    answerlog = AnswerLog.objects.filter(
        student=request.user,
        exercise__subject=subject  # 按科目过滤
    )

    knowledge_mastery_diagnoses(request.user, answerlog)

    # 计算推荐学习路径
    weak_points = diagnoses.filter(mastery_level__lt=0.6).order_by('mastery_level')[:5]

    return render(request, 'student/student_subject_diagnosis.html', {
        'subject': subject,  # 传递科目对象到模板
        'diagnoses': diagnoses,
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

    return render(request, 'student/knowledge_points.html', {
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
            exercise.creator = request.user
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

    return render(request, 'student/upload_exercise.html', {
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

    return render(request, 'teacher/upload_knowledge.html', {
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

    return render(request, 'teacher/q_matrix.html', {
        'form': form,
        'q_matrix': q_matrix
    })

#当学生完成一道题目后，更新该题目涉及的所有知识点的掌握情况
def update_knowledge_mastery(student, exercise, is_correct):

    related_kps = QMatrix.objects.filter(exercise=exercise).select_related('knowledge_point')

    #对题目涉及的每个知识点都进行单独处理。
    for q_item in related_kps:
        #获取或创建学习诊断记录
        diagnosis, created = StudentDiagnosis.objects.get_or_create(
            student=student,
            knowledge_point=q_item.knowledge_point
        )

        diagnosis.practice_count += 1
        if is_correct:
            diagnosis.correct_count += 1

        #计算掌握程度
        calculate_mastery(diagnosis)
#计算掌握程度公式
def calculate_mastery(self):
    if self.practice_count > 0:
        self.mastery_level = self.correct_count / self.practice_count
    else:
        self.mastery_level = 0.0
    self.save()