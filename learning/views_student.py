from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
import json
from itertools import groupby
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from .diagnosis.views_diagnosis import *
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

#学习面板
@login_required
@user_passes_test(is_student)
def student_dashboard(request):
    enrolled_records = request.user.enrolled_subjects.all().select_related('subject').order_by('subject__name')
    subjects = [record.subject for record in enrolled_records]
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:5]
    total_answers = AnswerLog.objects.filter(student=request.user).count()
    # 计算总体掌握情况
    total_diagnosis = StudentDiagnosis.objects.filter(student=request.user)
    if total_diagnosis.exists():
        avg_mastery = total_diagnosis.aggregate(avg=Avg('mastery_level'))['avg']
    else:
        avg_mastery = 0

    # 只传递账号创建时间（不做计算，交给模板处理）
    account_joined = request.user.date_joined
    current_time = timezone.now()
    days_since_creation = (current_time - account_joined).days + 1

    first_subject = subjects[0] if subjects else None  # 推荐：用索引判断（最简洁）

    return render(request, 'student/student_dashboard.html', {
        'total_answers': total_answers,
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': first_subject,
        'days_since_creation': days_since_creation
    })

#我的科目
@login_required
@user_passes_test(is_student)
def my_subjects(request):

    # 获取当前学生已选的科目记录（包含科目信息和选课时间）
    enrolled_records = StudentSubject.objects.filter(
        student=request.user
    ).select_related('subject').order_by('-enrolled_at')

    # 无需额外处理，直接将记录传递给模板（每条记录都包含 subject 和 enrolled_at）
    context = {
        'enrolled_records': enrolled_records,  # 直接传递完整记录
    }
    return render(request, 'student/my_subjects.html', context)

#所有课程
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

#课程选择
@login_required
@user_passes_test(is_student)
def student_subject_selection(request):
    """学生选课页面（选择Subject=课程）"""
    # 获取所有课程（Subject）
    all_subjects = Subject.objects.all()
    # 获取学生已选课程
    enrolled_subjects = StudentSubject.objects.filter(student=request.user).select_related('subject')

    # 关键：预处理已选课程的ID列表（在视图中完成，避免模板中调用复杂方法）
    enrolled_subject_ids = [enrollment.subject.id for enrollment in enrolled_subjects]

    if request.method == 'POST':
        subject_id = request.POST.get('subject_id')
        action = request.POST.get('action')

        if action == 'enroll' and subject_id:
            subject = get_object_or_404(Subject, id=subject_id)
            StudentSubject.objects.get_or_create(student=request.user, subject=subject)
            messages.success(request, f'已成功选修《{subject.name}》课程')
        elif action == 'drop' and subject_id:
            StudentSubject.objects.filter(student=request.user, subject_id=subject_id).delete()
            messages.success(request, '已退选课程')

        return redirect('student_subject_selection')

    context = {
        'all_subjects': all_subjects,
        'enrolled_subjects': enrolled_subjects,
        'enrolled_subject_ids': enrolled_subject_ids,  # 传递预处理后的ID列表
    }
    return render(request, 'student/subject_selection.html', context)

#"单个课程列表页面"""
@login_required
@user_passes_test(is_student)
def exercise_list(request, subject_id):
    # 获取科目
    subject = get_object_or_404(Subject, id=subject_id)

    # 获取该科目的所有习题
    exercises = Exercise.objects.filter(subject_id=subject_id).order_by('title', 'id')

    # 获取答题记录
    answer_logs = AnswerLog.objects.filter(
        student=request.user,
        exercise__in=exercises
    )

    # 统计
    completed_exercise_ids = answer_logs.values_list('exercise_id', flat=True).distinct()
    total_attempts = answer_logs.count()
    correct_attempts = answer_logs.filter(is_correct=True).count()

    # 标记已完成
    for exercise in exercises:
        exercise.completed = exercise.id in completed_exercise_ids

    # 进度计算
    total_exercises = exercises.count()
    completed_count = len(completed_exercise_ids)

    percentage = 0
    if total_exercises > 0:
        percentage = min(100, round((completed_count / total_exercises) * 100, 1))

    accuracy = 0
    if total_attempts > 0:
        accuracy = round((correct_attempts / total_attempts) * 100, 1)

    # 进度数据
    progress = {
        'total': total_exercises,
        'completed': completed_count,
        'percentage': percentage,
        'total_attempts': total_attempts,
        'correct_attempts': correct_attempts,
        'accuracy': accuracy,
    }

    # 按标题分组（已按title排序）
    grouped_exercises = []
    current_title = None
    current_group = []

    for exercise in exercises:
        if exercise.title != current_title:
            if current_group:
                # 完成上一个分组
                grouped_exercises.append({
                    'title': current_title,
                    'exercises': current_group,
                    'exercise_count': len(current_group),
                    'completed': all(ex.completed for ex in current_group)
                })
            # 开始新分组
            current_title = exercise.title
            current_group = [exercise]
        else:
            current_group.append(exercise)

    # 添加最后一个分组
    if current_group:
        grouped_exercises.append({
            'title': current_title,
            'exercises': current_group,
            'exercise_count': len(current_group),
            'completed': all(ex.completed for ex in current_group)
        })

    return render(request, 'student/exercise_list.html', {
        'subject': subject,
        'grouped_exercises': grouped_exercises,
        'progress': progress,
        # 其他可选参数...
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

        # 处理选择题（单选题、多选题、判断题）
        if exercise.question_type in ['1', '2', '6']:
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

#显示答题结果，并提供下一题链接
@login_required
@user_passes_test(is_student)
def exercise_result(request, log_id):
    # 1. 获取答题记录并验证权限
    answer_log = get_object_or_404(
        AnswerLog.objects.select_related(
            'exercise__subject',
            'student'
        ).prefetch_related(
            'selected_choices',
            'exercise__choices'
        ),
        id=log_id,
        student=request.user  # 确保学生只能查看自己的答题记录
    )

    current_exercise = answer_log.exercise
    current_subject = current_exercise.subject

    # 2. 验证学生是否选修该科目（可选，但推荐添加）
    if not StudentSubject.objects.filter(
            student=request.user,
            subject=current_subject
    ).exists():
        # 如果没有选修该科目，返回错误页面
        return render(request, 'errors/403.html', {
            'message': '您未选修此科目，无法查看答题结果'
        }, status=403)

    # 3. 获取用户选择的选项ID列表（如果需要的话）
    selected_choice_ids = list(answer_log.selected_choices.values_list('id', flat=True))

    # 4. 查找同一科目、同一标题的下一题
    # 先查找同一习题集中的下一题（假设同一标题属于同一习题集）
    next_exercise = Exercise.objects.filter(
        subject=current_subject,
        title=current_exercise.title,  # 同一习题集
        id__gt=current_exercise.id,  # ID比当前大
    ).order_by('id').first()  # 按ID排序取第一个

    # 如果没有同一习题集的下一题，则查找同科目的其他题目
    if not next_exercise:
        next_exercise = Exercise.objects.filter(
            subject=current_subject,
            id__gt=current_exercise.id
        ).exclude(
            id__in=AnswerLog.objects.filter(
                student=request.user,
                exercise__subject=current_subject
            ).values_list('exercise_id', flat=True)
        ).order_by('id').first()

    # 5. 准备上下文数据
    context = {
        'answer_log': answer_log,
        'selected_choice_ids': selected_choice_ids,
        'next_exercise': next_exercise,
    }

    return render(request, 'student/exercise_result.html', context)



# 学习诊断，知识点掌握情况
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
        # 使用filter().first()代替get_or_create，避免MultipleObjectsReturned错误
        diagnosis = StudentDiagnosis.objects.filter(
            student=student,
            knowledge_point=q_item.knowledge_point
        ).first()
        
        if not diagnosis:
            # 如果不存在，创建新记录
            diagnosis = StudentDiagnosis.objects.create(
                student=student,
                knowledge_point=q_item.knowledge_point,
                practice_count=0,
                correct_count=0,
                mastery_level=0.0
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