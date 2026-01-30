from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.contrib import messages
from django.views.decorators.http import require_http_methods
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

#一.学习面板
@login_required
@user_passes_test(is_student)
def student_dashboard(request):
    enrolled_records = request.user.enrolled_subjects.all().select_related('subject').order_by('subject__name')
    subjects = [record.subject for record in enrolled_records]
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:10]
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

    # 计算每个科目的统计数据
    subject_stats = []
    for subject in subjects:
        # 该科目的所有习题数
        total_exercises = Exercise.objects.filter(subject=subject).count()
        
        # 该科目的已完成习题数（去重）
        completed_exercises = AnswerLog.objects.filter(
            student=request.user,
            exercise__subject=subject
        ).values('exercise_id').distinct().count()
        
        # 该科目的正确率
        correct_count = AnswerLog.objects.filter(
            student=request.user,
            exercise__subject=subject,
            is_correct=True
        ).count()
        
        total_count = AnswerLog.objects.filter(
            student=request.user,
            exercise__subject=subject
        ).count()
        
        accuracy = (correct_count / total_count * 100) if total_count > 0 else 0
        
        subject_stats.append({
            'name': subject.name,
            'total_exercises': total_exercises,
            'completed_exercises': completed_exercises,
            'accuracy': round(accuracy, 1),
            'answer_count': total_count
        })
    
    # 获取薄弱知识点（掌握程度最低的5个）
    weak_knowledge_points = StudentDiagnosis.objects.filter(
        student=request.user
    ).select_related('knowledge_point').order_by('mastery_level')[:5]
    
    weak_kp_data = []
    for kp in weak_knowledge_points:
        weak_kp_data.append({
            'name': kp.knowledge_point.name,
            'mastery': round(kp.mastery_level * 100, 1),
            'subject': kp.knowledge_point.subject.name
        })

    return render(request, 'student/student_dashboard.html', {
        'total_answers': total_answers,
        'subjects': subjects,
        'recent_logs': recent_logs,
        'avg_mastery': round(avg_mastery * 100, 1),
        'first_subject': first_subject,
        'days_since_creation': days_since_creation,
        'subject_stats': subject_stats,
        'weak_knowledge_points': weak_kp_data,
        'subject_stats_json': json.dumps(subject_stats),
        'weak_kp_json': json.dumps(weak_kp_data)
    })

# 推荐习题页面
@login_required
@user_passes_test(is_student)
def recommended_exercises(request, subject_id):
    """根据学生学习情况推荐习题并直接跳转到第一道题"""
    subject = get_object_or_404(Subject, id=subject_id)
    
    # 获取该科目的所有习题
    all_exercises = Exercise.objects.filter(subject=subject).select_related('subject')
    
    # 获取学生的答题记录
    answer_logs = AnswerLog.objects.filter(
        student=request.user,
        exercise__subject=subject
    ).values_list('exercise_id', flat=True)
    
    # 获取学生在该科目的知识点掌握情况
    student_diagnosis = StudentDiagnosis.objects.filter(
        student=request.user,
        knowledge_point__subject=subject
    ).select_related('knowledge_point')
    
    # 构建推荐逻辑
    recommended_exercise = None
    
    # 1. 优先推荐未做过的习题
    unanswered = all_exercises.exclude(id__in=answer_logs)
    
    if unanswered.exists():
        # 从未做过的习题中，优先推荐与薄弱知识点相关的
        weak_kps = student_diagnosis.filter(mastery_level__lt=0.6).values_list('knowledge_point_id', flat=True)
        
        if weak_kps:
            # 推荐与薄弱知识点相关的未做习题（随机选择）
            weak_related = unanswered.filter(
                qmatrix__knowledge_point_id__in=weak_kps
            ).distinct().order_by('?').first()
            if weak_related:
                recommended_exercise = weak_related
        
        # 如果没有找到薄弱知识点相关的，推荐随机未做的
        if not recommended_exercise:
            recommended_exercise = unanswered.order_by('?').first()
    else:
        # 如果所有习题都做过，推荐做错过的习题
        wrong_exercises = AnswerLog.objects.filter(
            student=request.user,
            exercise__subject=subject,
            is_correct=False
        ).values_list('exercise_id', flat=True).distinct()
        
        if wrong_exercises:
            recommended_exercise = all_exercises.filter(id__in=wrong_exercises).order_by('?').first()
        else:
            # 如果全部正确，随机推荐
            recommended_exercise = all_exercises.order_by('?').first()
    
    # 直接跳转到推荐的习题
    if recommended_exercise:
        return redirect('take_exercise', exercise_id=recommended_exercise.id)
    else:
        # 如果没有习题，返回学习面板
        messages.warning(request, '该科目暂无习题')
        return redirect('student_dashboard')

#二.在线学习
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
    return render(request, 'student/student_onlinelearning.html', context)

#所有课程
@login_required
@user_passes_test(is_student)
def student_subject(request):
    subjects = Subject.objects.all()
    recent_logs = AnswerLog.objects.filter(student=request.user).order_by('-submitted_at')[:10]

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

#课程管理
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

#四.课程管理
@login_required
@user_passes_test(is_student)
def student_course_management(request):
    """学生课程管理页面 - 选课和查看课程详情"""
    # 获取学生已选课程
    my_subjects = StudentSubject.objects.filter(
        student=request.user
    ).select_related('subject').prefetch_related(
        'subject__exercise_set',
        'subject__knowledgepoint_set'
    )
    
    # 获取已选课程的ID列表
    enrolled_subject_ids = [ss.subject.id for ss in my_subjects]
    
    # 获取可选课程（排除已选的）
    available_subjects = Subject.objects.exclude(
        id__in=enrolled_subject_ids
    ).prefetch_related('exercise_set', 'knowledgepoint_set')
    
    if request.method == 'POST':
        subject_id = request.POST.get('subject_id')
        action = request.POST.get('action')
        
        if action == 'select' and subject_id:
            # 选课
            subject = get_object_or_404(Subject, id=subject_id)
            StudentSubject.objects.get_or_create(student=request.user, subject=subject)
            messages.success(request, f'已成功选修《{subject.name}》课程')
        elif action == 'remove' and subject_id:
            # 退课
            subject = get_object_or_404(Subject, id=subject_id)
            StudentSubject.objects.filter(student=request.user, subject_id=subject_id).delete()
            messages.success(request, f'已退选《{subject.name}》课程')
        
        return redirect('student_course_management')
    
    context = {
        'my_subjects': my_subjects,
        'available_subjects': available_subjects,
    }
    return render(request, 'student/student_coursemanage.html', context)

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
@login_required
@user_passes_test(is_student)
def take_exercise(request, exercise_id):
    exercise = get_object_or_404(Exercise, id=exercise_id)
    single_mode = request.GET.get('single', '0') == '1'  # 检查是否是单个习题模式

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

        # 设置单题模式标志到session
        if single_mode:
            request.session['single_mode'] = True

        return redirect('exercise_result', log_id=answer_log.id)

    # 获取推荐习题列表（如果存在且不是单个习题模式）
    subject = exercise.subject
    session_key = f'recommended_exercises_{subject.id}'
    recommended_exercises = []
    current_exercise_index = -1
    
    if not single_mode and session_key in request.session:
        exercise_ids = request.session[session_key]
        current_exercise_index = exercise_ids.index(exercise_id) if exercise_id in exercise_ids else -1
        
        # 获取所有推荐习题对象
        if current_exercise_index >= 0:
            recommended_exercises = Exercise.objects.filter(id__in=exercise_ids).order_by(
                'id'
            )
            # 按照session中的顺序排序
            id_order = {eid: i for i, eid in enumerate(exercise_ids)}
            recommended_exercises = sorted(recommended_exercises, key=lambda x: id_order.get(x.id, 999))

    return render(request, 'student/take_exercise.html', {
        'exercise': exercise,
        'recommended_exercises': recommended_exercises,
        'current_exercise_index': current_exercise_index,
        'single_mode': single_mode,
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

    # 4. 检查是否在单题模式中
    single_mode = request.session.get('single_mode', False)
    
    # 5. 检查是否在推荐练习集中 - 如果是，提供"下一题"功能
    next_exercise = None
    session_key = f'recommended_exercises_{current_subject.id}'
    
    if not single_mode and session_key in request.session:
        # 用户在做推荐练习集（非单题模式）
        exercise_ids = request.session[session_key]
        current_index = exercise_ids.index(current_exercise.id) if current_exercise.id in exercise_ids else -1
        
        # 如果不是最后一题，获取下一题
        if current_index >= 0 and current_index < len(exercise_ids) - 1:
            next_exercise_id = exercise_ids[current_index + 1]
            next_exercise = Exercise.objects.get(id=next_exercise_id)

    # 6. 准备上下文数据
    # 检查是否已收藏
    from .models import ExerciseFavorite
    is_favorited = ExerciseFavorite.objects.filter(
        student=request.user,
        exercise=current_exercise
    ).exists()
    
    context = {
        'answer_log': answer_log,
        'selected_choice_ids': selected_choice_ids,
        'next_exercise': next_exercise,
        'is_favorited': is_favorited,
        'single_mode': single_mode,
    }

    # 如果在单题模式中，清除session标志
    if single_mode:
        if 'single_mode' in request.session:
            del request.session['single_mode']

    return render(request, 'student/exercise_result.html', context)



# 三.学习诊断，知识点掌握情况
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
    from collections import defaultdict
    from datetime import datetime, timedelta
    
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

    # ===== 图表数据准备 =====
    
    # 1. 答题趋势数据（最近30天）
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_logs = answer_logs.filter(submitted_at__gte=thirty_days_ago)
    
    # 按日期分组统计
    daily_stats = defaultdict(lambda: {'total': 0, 'correct': 0})
    for log in recent_logs:
        date_str = log.submitted_at.strftime('%m-%d')
        daily_stats[date_str]['total'] += 1
        if log.is_correct:
            daily_stats[date_str]['correct'] += 1
    
    # 生成最近30天的日期列表
    trend_dates = []
    trend_total = []
    trend_correct = []
    for i in range(29, -1, -1):
        date = timezone.now() - timedelta(days=i)
        date_str = date.strftime('%m-%d')
        trend_dates.append(date_str)
        trend_total.append(daily_stats[date_str]['total'])
        trend_correct.append(daily_stats[date_str]['correct'])
    
    # 2. 每日答题活跃度（最近14天）
    fourteen_days_ago = timezone.now() - timedelta(days=14)
    recent_14_logs = answer_logs.filter(submitted_at__gte=fourteen_days_ago)
    
    daily_counts_dict = defaultdict(int)
    for log in recent_14_logs:
        date_str = log.submitted_at.strftime('%m-%d')
        daily_counts_dict[date_str] += 1
    
    daily_dates = []
    daily_counts = []
    for i in range(13, -1, -1):
        date = timezone.now() - timedelta(days=i)
        date_str = date.strftime('%m-%d')
        daily_dates.append(date_str)
        daily_counts.append(daily_counts_dict[date_str])
    
    # 3. 题型分布统计
    type_stats = defaultdict(int)
    type_names_map = {
        '1': '单选题',
        '2': '多选题',
        '3': '填空题',
        '4': '简答题',
        '5': '主观题',
        '6': '判断题',
    }
    
    for log in answer_logs:
        q_type = log.exercise.question_type
        type_name = type_names_map.get(q_type, '其他')
        type_stats[type_name] += 1
    
    type_names = list(type_stats.keys())
    type_counts = list(type_stats.values())

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
        recent_logs_3m = [log for log in exercise_logs if log.submitted_at >= three_months_ago][:31]  # 最多显示31个

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
        for i, log in enumerate(recent_logs_3m, 1):
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
                'question_type': exercise.question_type,
                'selected_option': " | ".join(selected_options_text) if selected_options_text else "未选择",
                'correct_option': " | ".join(correct_options_text) if correct_options_text else "未设置正确答案",
                'options_json': json.dumps(options_text, ensure_ascii=False),
                'text_answer': log.text_answer if log.text_answer else "",  # 主观题答案
            }
            processed_recent_logs.append(log_data)

        exercises_with_stats.append({
            'id': exercise.id,
            'title': exercise.title,
            'points': 20,
            'total_attempts': total_attempts,
            'correct_rate': exercise_correct_rate,
            'recent_logs': processed_recent_logs,
        })

    # 按答题次数排序
    exercises_with_stats.sort(key=lambda x: x['total_attempts'], reverse=True)

    # 计算习题总数和已完成习题数
    total_exercises = len(exercises_with_stats)
    completed_exercises = len([ex for ex in exercises_with_stats if ex['total_attempts'] > 0])

    # 添加分页功能 - 10题一页
    from django.core.paginator import Paginator
    paginator = Paginator(exercises_with_stats, 10)  # 每页10题
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'subject': subject,
        'answer_logs': answer_logs,
        'total_logs': total_logs,
        'correct_logs': correct_logs,
        'incorrect_logs': incorrect_logs,
        'unmarked_logs': unmarked_logs,
        'correct_rate': correct_rate,
        'has_data': total_logs > 0,
        'exercises_with_stats': page_obj.object_list,  # 当前页的习题
        'page_obj': page_obj,  # 分页对象
        'total_exercises': total_exercises,
        'completed_exercises': completed_exercises,
        # 图表数据
        'trend_dates': json.dumps(trend_dates),
        'trend_total': json.dumps(trend_total),
        'trend_correct': json.dumps(trend_correct),
        'daily_dates': json.dumps(daily_dates),
        'daily_counts': json.dumps(daily_counts),
        'type_names': json.dumps(type_names),
        'type_counts': json.dumps(type_counts),
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


# 收藏习题
@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def add_favorite(request):
    """添加收藏"""
    import json
    from .models import ExerciseFavorite
    
    try:
        data = json.loads(request.body)
        exercise_id = data.get('exercise_id')
        
        if not exercise_id:
            return JsonResponse({'success': False, 'message': '缺少习题ID'})
        
        exercise = get_object_or_404(Exercise, id=exercise_id)
        
        # 创建收藏，如果已存在则忽略
        favorite, created = ExerciseFavorite.objects.get_or_create(
            student=request.user,
            exercise=exercise
        )
        
        if created:
            return JsonResponse({'success': True, 'message': '收藏成功'})
        else:
            return JsonResponse({'success': True, 'message': '已经收藏过了'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def remove_favorite(request):
    """取消收藏"""
    import json
    from .models import ExerciseFavorite
    
    try:
        data = json.loads(request.body)
        exercise_id = data.get('exercise_id')
        
        if not exercise_id:
            return JsonResponse({'success': False, 'message': '缺少习题ID'})
        
        # 删除收藏
        deleted_count = ExerciseFavorite.objects.filter(
            student=request.user,
            exercise_id=exercise_id
        ).delete()[0]
        
        if deleted_count > 0:
            return JsonResponse({'success': True, 'message': '取消收藏成功'})
        else:
            return JsonResponse({'success': False, 'message': '未找到收藏记录'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def update_favorite_note(request):
    """更新收藏笔记"""
    import json
    from .models import ExerciseFavorite
    
    try:
        data = json.loads(request.body)
        exercise_id = data.get('exercise_id')
        note = data.get('note', '')
        
        if not exercise_id:
            return JsonResponse({'success': False, 'message': '缺少习题ID'})
        
        # 获取收藏记录
        favorite = ExerciseFavorite.objects.get(
            student=request.user,
            exercise_id=exercise_id
        )
        
        # 更新笔记
        favorite.note = note
        favorite.save()
        
        return JsonResponse({'success': True, 'message': '笔记已保存'})
    
    except ExerciseFavorite.DoesNotExist:
        return JsonResponse({'success': False, 'message': '未找到收藏记录'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
def my_favorites(request):
    """我的收藏夹"""
    from .models import ExerciseFavorite
    
    favorites = ExerciseFavorite.objects.filter(
        student=request.user
    ).select_related('exercise__subject').prefetch_related('exercise__choices')
    
    # 按科目分组
    favorites_by_subject = {}
    for favorite in favorites:
        subject_name = favorite.exercise.subject.name
        if subject_name not in favorites_by_subject:
            favorites_by_subject[subject_name] = []
        favorites_by_subject[subject_name].append(favorite)
    
    context = {
        'favorites': favorites,
        'favorites_by_subject': favorites_by_subject,
        'total_count': favorites.count()
    }
    
    return render(request, 'student/my_favorites.html', context)


# 错题本功能
@login_required
@user_passes_test(is_student)
def my_error_notebook(request):
    """我的错题本"""
    from .models import ErrorNotebook
    
    error_notebooks = ErrorNotebook.objects.filter(
        student=request.user
    ).select_related('exercise__subject', 'answer_log').prefetch_related('exercise__choices')
    
    # 按科目分组
    errors_by_subject = {}
    for error in error_notebooks:
        subject_name = error.exercise.subject.name
        if subject_name not in errors_by_subject:
            errors_by_subject[subject_name] = []
        errors_by_subject[subject_name].append(error)
    
    context = {
        'error_notebooks': error_notebooks,
        'errors_by_subject': errors_by_subject,
        'total_count': error_notebooks.count(),
        'mastered_count': error_notebooks.filter(is_mastered=True).count(),
    }
    
    return render(request, 'student/my_error_notebook.html', context)


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def add_to_error_notebook(request):
    """添加到错题本"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        answer_log_id = data.get('answer_log_id')
        
        if not answer_log_id:
            return JsonResponse({'success': False, 'message': '缺少答题记录ID'})
        
        answer_log = get_object_or_404(
            AnswerLog.objects.select_related('exercise'),
            id=answer_log_id,
            student=request.user
        )
        
        # 只有答题错误才能添加到错题本
        if answer_log.is_correct:
            return JsonResponse({'success': False, 'message': '只能添加错题到错题本'})
        
        # 创建错题本记录，如果已存在则忽略
        error_notebook, created = ErrorNotebook.objects.get_or_create(
            student=request.user,
            answer_log=answer_log,
            defaults={'exercise': answer_log.exercise}
        )
        
        if created:
            return JsonResponse({'success': True, 'message': '已添加到错题本'})
        else:
            return JsonResponse({'success': True, 'message': '已经在错题本中了'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def remove_from_error_notebook(request):
    """从错题本中移除"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        error_notebook_id = data.get('error_notebook_id')
        
        if not error_notebook_id:
            return JsonResponse({'success': False, 'message': '缺少错题本ID'})
        
        # 删除错题本记录
        deleted_count = ErrorNotebook.objects.filter(
            student=request.user,
            id=error_notebook_id
        ).delete()[0]
        
        if deleted_count > 0:
            return JsonResponse({'success': True, 'message': '已从错题本中移除'})
        else:
            return JsonResponse({'success': False, 'message': '未找到记录'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def mark_error_as_mastered(request):
    """标记错题为已掌握"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        error_notebook_id = data.get('error_notebook_id')
        
        if not error_notebook_id:
            return JsonResponse({'success': False, 'message': '缺少错题本ID'})
        
        error_notebook = get_object_or_404(
            ErrorNotebook,
            id=error_notebook_id,
            student=request.user
        )
        
        error_notebook.is_mastered = not error_notebook.is_mastered
        error_notebook.save()
        
        return JsonResponse({
            'success': True,
            'message': '已标记为已掌握' if error_notebook.is_mastered else '已取消标记',
            'is_mastered': error_notebook.is_mastered
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# 错题本功能
@login_required
@user_passes_test(is_student)
def my_error_notebook(request):
    """我的错题本"""
    from .models import ErrorNotebook
    
    error_notebooks = ErrorNotebook.objects.filter(
        student=request.user
    ).select_related('exercise__subject', 'answer_log').prefetch_related('exercise__choices')
    
    # 按科目分组
    errors_by_subject = {}
    for error in error_notebooks:
        subject_name = error.exercise.subject.name
        if subject_name not in errors_by_subject:
            errors_by_subject[subject_name] = []
        errors_by_subject[subject_name].append(error)
    
    context = {
        'error_notebooks': error_notebooks,
        'errors_by_subject': errors_by_subject,
        'total_count': error_notebooks.count(),
        'mastered_count': error_notebooks.filter(is_mastered=True).count(),
    }
    
    return render(request, 'student/my_error_notebook.html', context)


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def add_to_error_notebook(request):
    """添加到错题本"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        answer_log_id = data.get('answer_log_id')
        
        if not answer_log_id:
            return JsonResponse({'success': False, 'message': '缺少答题记录ID'})
        
        answer_log = get_object_or_404(
            AnswerLog.objects.select_related('exercise'),
            id=answer_log_id,
            student=request.user
        )
        
        # 只有答题错误才能添加到错题本
        if answer_log.is_correct:
            return JsonResponse({'success': False, 'message': '只能添加错题到错题本'})
        
        # 创建错题本记录，如果已存在则忽略
        error_notebook, created = ErrorNotebook.objects.get_or_create(
            student=request.user,
            answer_log=answer_log,
            defaults={'exercise': answer_log.exercise}
        )
        
        if created:
            return JsonResponse({'success': True, 'message': '已添加到错题本'})
        else:
            return JsonResponse({'success': True, 'message': '已经在错题本中了'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def remove_from_error_notebook(request):
    """从错题本中移除"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        error_notebook_id = data.get('error_notebook_id')
        
        if not error_notebook_id:
            return JsonResponse({'success': False, 'message': '缺少错题本ID'})
        
        # 删除错题本记录
        deleted_count = ErrorNotebook.objects.filter(
            student=request.user,
            id=error_notebook_id
        ).delete()[0]
        
        if deleted_count > 0:
            return JsonResponse({'success': True, 'message': '已从错题本中移除'})
        else:
            return JsonResponse({'success': False, 'message': '未找到记录'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_student)
@require_http_methods(["POST"])
def mark_error_as_mastered(request):
    """标记错题为已掌握"""
    import json
    from .models import ErrorNotebook
    
    try:
        data = json.loads(request.body)
        error_notebook_id = data.get('error_notebook_id')
        
        if not error_notebook_id:
            return JsonResponse({'success': False, 'message': '缺少错题本ID'})
        
        error_notebook = get_object_or_404(
            ErrorNotebook,
            id=error_notebook_id,
            student=request.user
        )
        
        error_notebook.is_mastered = not error_notebook.is_mastered
        error_notebook.save()
        
        return JsonResponse({
            'success': True,
            'message': '已标记为已掌握' if error_notebook.is_mastered else '已取消标记',
            'is_mastered': error_notebook.is_mastered
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# 科目学习页面（新窗口）
@login_required
@user_passes_test(is_student)
def subject_learning(request, subject_id):
    """科目学习页面 - 显示章节和课程卡片"""
    # 获取科目
    subject = get_object_or_404(Subject, id=subject_id)

    # 获取该科目的所有习题，按 problemsets 排序
    exercises = Exercise.objects.filter(subject_id=subject_id).order_by('problemsets', 'id')

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

    # 按标题分组
    grouped_exercises = []
    current_title = None
    current_group = []

    for exercise in exercises:
        if exercise.title != current_title:
            if current_group:
                grouped_exercises.append({
                    'title': current_title,
                    'exercises': current_group,
                    'exercise_count': len(current_group),
                    'completed': all(ex.completed for ex in current_group)
                })
            current_title = exercise.title
            current_group = [exercise]
        else:
            current_group.append(exercise)

    if current_group:
        grouped_exercises.append({
            'title': current_title,
            'exercises': current_group,
            'exercise_count': len(current_group),
            'completed': all(ex.completed for ex in current_group)
        })

    # 获取课程统计数据
    total_knowledge_points = KnowledgePoint.objects.filter(subject=subject).count()
    total_students = User.objects.filter(enrolled_subjects__subject=subject).distinct().count()

    return render(request, 'student/subject_learning.html', {
        'subject': subject,
        'grouped_exercises': grouped_exercises,
        'progress': progress,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
        'total_students': total_students,
    })


# 科目收藏页面（使用learning_base布局）
@login_required
@user_passes_test(is_student)
def subject_favorites(request, subject_id):
    """科目收藏页面 - 使用learning_base布局"""
    from .models import ExerciseFavorite
    
    subject = get_object_or_404(Subject, id=subject_id)
    
    favorites = ExerciseFavorite.objects.filter(
        student=request.user,
        exercise__subject=subject
    ).select_related('exercise').prefetch_related('exercise__choices').order_by('-created_at')
    
    context = {
        'subject': subject,
        'favorites': favorites,
        'total_count': favorites.count()
    }
    
    return render(request, 'student/subject_favorites.html', context)
