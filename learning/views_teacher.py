from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.core.paginator import Paginator
import json
from datetime import datetime, timedelta
from .models import Exercise, Subject, KnowledgePoint, Choice, QMatrix
from accounts.models import *
from .forms import ExerciseForm

from django.db.models import Count, Q
from django.db import transaction
import csv
from datetime import datetime
#教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

#教师控制面板
@login_required
def dashboard(request):
    if request.user.user_type == 'teacher':
        return redirect('teacher_dashboard')
    else:
        return redirect('student_dashboard')

#教师面板
@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    subjects = Subject.objects.all()
    total_exercises = Exercise.objects.filter(creator=request.user).count()
    total_knowledge_points = KnowledgePoint.objects.count()

    return render(request, 'teacher/teacher_dashboard.html', {
        'subjects': subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
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
    subjects = Subject.objects.all()
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
        'subjects': subjects,
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


# 学生信息显示
@login_required
@user_passes_test(is_teacher)
def student_info(request):
    # 获取所有学生
    students = User.objects.filter(user_type='student').select_related('studentprofile')

    # 获取年级列表
    grade_list = StudentProfile.objects.values_list('grade', flat=True).distinct()


    # 获取近7天有学习记录的学生
    week_ago = datetime.now() - timedelta(days=7)
    active_students_count = AnswerLog.objects.filter(
        submitted_at__gte=week_ago
    ).values('student').distinct().count()

    # 分页处理
    paginator = Paginator(students, 10)  # 每页10个学生
    page_number = request.GET.get('page')
    page_students = paginator.get_page(page_number)

    # 为每个学生添加学习统计数据
    for student in page_students:
        # 答题统计
        answer_logs = AnswerLog.objects.filter(student=student)
        student.total_exercises = answer_logs.count()

        if student.total_exercises > 0:
            correct_count = answer_logs.filter(is_correct=True).count()
            student.accuracy = (correct_count / student.total_exercises) * 100
        else:
            student.accuracy = 0

        # 最后学习时间
        last_log = answer_logs.order_by('-submitted_at').first()
        student.last_active = last_log.submitted_at if last_log else None

    context = {
        'students': page_students,
        'total_students': students.count(),
        'active_students': active_students_count,
        'grade_list': grade_list,
        'subjects': Subject.objects.all(),  # 侧边栏需要的科目
    }

    return render(request, 'teacher/student_info.html', context)


"""题库管理主页面"""
@login_required
@user_passes_test(is_teacher)
def exercise_management(request):

    # 获取所有筛选参数
    subject_id = request.GET.get('subject')
    question_type = request.GET.get('question_type')
    knowledge_point_id = request.GET.get('knowledge_point')
    creator_id = request.GET.get('creator')
    search = request.GET.get('search')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # 基础查询集
    exercises = Exercise.objects.all().select_related('subject', 'creator').prefetch_related(
        'qmatrix_set__knowledge_point')

    # 应用筛选条件
    if subject_id and subject_id.isdigit():
        exercises = exercises.filter(subject_id=int(subject_id))

    if question_type:
        exercises = exercises.filter(question_type=question_type)

    if knowledge_point_id and knowledge_point_id.isdigit():
        exercises = exercises.filter(qmatrix__knowledge_point_id=int(knowledge_point_id)).distinct()

    if creator_id and creator_id.isdigit():
        exercises = exercises.filter(creator_id=int(creator_id))

    if search:
        exercises = exercises.filter(
            Q(title__icontains=search) |
            Q(content__icontains=search)
        )

    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            exercises = exercises.filter(created_at__date__gte=start_date_obj)
        except ValueError:
            pass

    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            exercises = exercises.filter(created_at__date__lte=end_date_obj)
        except ValueError:
            pass

    # 获取筛选所需的数据
    subjects = Subject.objects.all()
    knowledge_points = KnowledgePoint.objects.all()
    creators = User.objects.filter(user_type='teacher').distinct()

    # 排序和分页
    exercises = exercises.order_by('-id')  # 按ID降序，最新的在前面

    # 分页 - 每页20条
    paginator = Paginator(exercises, 20)
    page_number = request.GET.get('page')
    page_exercises = paginator.get_page(page_number)

    context = {
        'exercises': page_exercises,
        'subjects': subjects,
        'knowledge_points': knowledge_points,
        'creators': creators,
        'filters': {
            'subject': subject_id,
            'question_type': question_type,
            'knowledge_point': knowledge_point_id,
            'creator': creator_id,
            'search': search,
            'start_date': start_date,
            'end_date': end_date,
        }
    }

    return render(request, 'teacher/exercise_management.html', context)

"""查看习题详情"""
@login_required
@user_passes_test(is_teacher)
def exercise_detail(request, exercise_id):

    try:
        exercise = Exercise.objects.select_related('subject', 'creator').prefetch_related(
            'choices', 'qmatrix_set__knowledge_point'
        ).get(id=exercise_id)
    except Exercise.DoesNotExist:
        messages.error(request, '习题不存在')
        return redirect('exercise_management')

    context = {
        'exercise': exercise,
    }
    return render(request, 'teacher/exercise_detail.html', context)

"""添加习题"""
@login_required
@user_passes_test(is_teacher)
def exercise_add(request):

    if request.method == 'POST':
        form = ExerciseForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    exercise = form.save(commit=False)
                    exercise.creator = request.user

                    # 处理不同的题型
                    question_type = form.cleaned_data.get('question_type', 'single')

                    if question_type in ['single', 'multiple']:
                        # 处理选择题
                        choices_data = request.POST.getlist('choices')
                        is_correct_data = request.POST.getlist('is_correct')

                        # 设置答案
                        correct_choices = []
                        for i, choice_text in enumerate(choices_data):
                            if choice_text.strip():  # 非空选项
                                is_correct = str(i) in is_correct_data
                                if is_correct:
                                    correct_choices.append(choice_text.strip())

                        if question_type == 'single' and len(correct_choices) > 1:
                            form.add_error(None, '单选题只能有一个正确答案')
                            return render(request, 'teacher/exercise_form.html', {'form': form})

                        exercise.answer = ', '.join(correct_choices)
                        exercise.save()

                        # 保存选项
                        for i, choice_text in enumerate(choices_data):
                            if choice_text.strip():
                                Choice.objects.create(
                                    exercise=exercise,
                                    content=choice_text.strip(),
                                    is_correct=str(i) in is_correct_data,
                                    order=i
                                )

                    elif question_type == 'judgment':
                        # 处理判断题
                        is_correct = form.cleaned_data.get('judgment_answer')
                        exercise.answer = '正确' if is_correct else '错误'
                        exercise.save()

                    elif question_type == 'text':
                        # 处理文本题
                        text_answer = form.cleaned_data.get('text_answer', '')
                        exercise.answer = text_answer
                        exercise.save()

                    # 处理知识点关联
                    knowledge_point_ids = request.POST.getlist('knowledge_points')
                    for kp_id in knowledge_point_ids:
                        if kp_id:
                            try:
                                kp = KnowledgePoint.objects.get(id=int(kp_id))
                                QMatrix.objects.create(
                                    exercise=exercise,
                                    knowledge_point=kp,
                                    weight=1.0
                                )
                            except (ValueError, KnowledgePoint.DoesNotExist):
                                pass

                    messages.success(request, '习题添加成功')
                    return redirect('exercise_management')

            except Exception as e:
                messages.error(request, f'添加习题失败: {str(e)}')
    else:
        form = ExerciseForm()

    context = {
        'form': form,
        'title': '添加习题',
        'subjects': Subject.objects.all(),
        'knowledge_points': KnowledgePoint.objects.all(),
    }

    return render(request, 'teacher/exercise_form.html', context)

"""编辑习题"""
@login_required
@user_passes_test(is_teacher)
def exercise_edit(request, exercise_id):

    try:
        exercise = Exercise.objects.select_related('subject').prefetch_related(
            'choices', 'qmatrix_set__knowledge_point'
        ).get(id=exercise_id)
    except Exercise.DoesNotExist:
        messages.error(request, '习题不存在')
        return redirect('exercise_management')

    if request.method == 'POST':
        form = ExerciseForm(request.POST, instance=exercise)
        if form.is_valid():
            try:
                with transaction.atomic():
                    updated_exercise = form.save(commit=False)

                    # 处理不同的题型
                    question_type = form.cleaned_data.get('question_type', 'single')

                    # 删除旧的选项
                    exercise.choices.all().delete()

                    if question_type in ['single', 'multiple']:
                        # 处理选择题
                        choices_data = request.POST.getlist('choices')
                        is_correct_data = request.POST.getlist('is_correct')

                        # 设置答案
                        correct_choices = []
                        for i, choice_text in enumerate(choices_data):
                            if choice_text.strip():
                                is_correct = str(i) in is_correct_data
                                if is_correct:
                                    correct_choices.append(choice_text.strip())

                        if question_type == 'single' and len(correct_choices) > 1:
                            form.add_error(None, '单选题只能有一个正确答案')
                            return render(request, 'teacher/exercise_form.html', {'form': form})

                        updated_exercise.answer = ', '.join(correct_choices)
                        updated_exercise.save()

                        # 保存新选项
                        for i, choice_text in enumerate(choices_data):
                            if choice_text.strip():
                                Choice.objects.create(
                                    exercise=updated_exercise,
                                    content=choice_text.strip(),
                                    is_correct=str(i) in is_correct_data,
                                    order=i
                                )

                    elif question_type == 'judgment':
                        # 处理判断题
                        is_correct = form.cleaned_data.get('judgment_answer')
                        updated_exercise.answer = '正确' if is_correct else '错误'
                        updated_exercise.save()

                    elif question_type == 'text':
                        # 处理文本题
                        text_answer = form.cleaned_data.get('text_answer', '')
                        updated_exercise.answer = text_answer
                        updated_exercise.save()

                    # 更新知识点关联
                    exercise.qmatrix_set.all().delete()
                    knowledge_point_ids = request.POST.getlist('knowledge_points')
                    for kp_id in knowledge_point_ids:
                        if kp_id:
                            try:
                                kp = KnowledgePoint.objects.get(id=int(kp_id))
                                QMatrix.objects.create(
                                    exercise=updated_exercise,
                                    knowledge_point=kp,
                                    weight=1.0
                                )
                            except (ValueError, KnowledgePoint.DoesNotExist):
                                pass

                    messages.success(request, '习题更新成功')
                    return redirect('exercise_management')

            except Exception as e:
                messages.error(request, f'更新习题失败: {str(e)}')
    else:
        form = ExerciseForm(instance=exercise)

    # 获取已关联的知识点
    related_knowledge_points = exercise.qmatrix_set.values_list('knowledge_point_id', flat=True)

    context = {
        'form': form,
        'exercise': exercise,
        'title': '编辑习题',
        'subjects': Subject.objects.all(),
        'knowledge_points': KnowledgePoint.objects.all(),
        'related_knowledge_points': list(related_knowledge_points),
    }

    return render(request, 'teacher/exercise_form.html', context)

"""删除单个习题"""
@login_required
@user_passes_test(is_teacher)
def exercise_delete(request, exercise_id):

    if request.method == 'POST':
        try:
            exercise = Exercise.objects.get(id=exercise_id)

            # 检查是否有答题记录
            answer_logs_count = AnswerLog.objects.filter(exercise=exercise).count()
            if answer_logs_count > 0:
                return JsonResponse({
                    'success': False,
                    'message': f'该习题有 {answer_logs_count} 条答题记录，无法删除'
                })

            exercise.delete()
            messages.success(request, '习题删除成功')
            return JsonResponse({'success': True})

        except Exercise.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': '习题不存在'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'删除失败: {str(e)}'
            })

    return JsonResponse({'success': False, 'message': '无效的请求方法'})

"""批量删除习题"""
@login_required
@user_passes_test(is_teacher)
def exercise_batch_delete(request):

    if request.method == 'POST':
        try:
            exercise_ids = request.POST.getlist('exercise_ids')

            if not exercise_ids:
                return JsonResponse({
                    'success': False,
                    'message': '请选择要删除的习题'
                })

            # 验证所有习题都存在且没有答题记录
            exercises = Exercise.objects.filter(id__in=exercise_ids)

            # 检查是否有习题不存在
            if exercises.count() != len(exercise_ids):
                return JsonResponse({
                    'success': False,
                    'message': '部分习题不存在'
                })

            # 检查是否有答题记录
            exercises_with_logs = []
            for exercise in exercises:
                log_count = AnswerLog.objects.filter(exercise=exercise).count()
                if log_count > 0:
                    exercises_with_logs.append(f"{exercise.title}({log_count}条记录)")

            if exercises_with_logs:
                return JsonResponse({
                    'success': False,
                    'message': f'以下习题有答题记录，无法删除: {", ".join(exercises_with_logs)}'
                })

            # 执行删除
            deleted_count = exercises.count()
            exercises.delete()

            return JsonResponse({
                'success': True,
                'deleted_count': deleted_count,
                'message': f'成功删除 {deleted_count} 个习题'
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'删除失败: {str(e)}'
            })

    return JsonResponse({'success': False, 'message': '无效的请求方法'})

"""导出习题为CSV"""
@login_required
@user_passes_test(is_teacher)
def export_exercises(request):

    # 应用相同的筛选条件
    exercises = Exercise.objects.all().select_related('subject', 'creator').prefetch_related('choices')

    # 筛选条件
    subject_id = request.GET.get('subject')
    question_type = request.GET.get('question_type')
    knowledge_point_id = request.GET.get('knowledge_point')
    search = request.GET.get('search')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if subject_id and subject_id.isdigit():
        exercises = exercises.filter(subject_id=int(subject_id))

    if question_type:
        exercises = exercises.filter(question_type=question_type)

    if knowledge_point_id and knowledge_point_id.isdigit():
        exercises = exercises.filter(qmatrix__knowledge_point_id=int(knowledge_point_id)).distinct()

    if search:
        exercises = exercises.filter(
            Q(title__icontains=search) |
            Q(content__icontains=search)
        )

    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            exercises = exercises.filter(created_at__date__gte=start_date_obj)
        except ValueError:
            pass

    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            exercises = exercises.filter(created_at__date__lte=end_date_obj)
        except ValueError:
            pass

    # 创建CSV响应
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response[
        'Content-Disposition'] = f'attachment; filename="exercises_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    # 使用csv.writer
    writer = csv.writer(response)

    # 写入标题行
    writer.writerow(['ID', '标题', '题目内容', '科目', '题型', '选项内容', '答案', '创建者', '创建时间', '关联知识点'])

    # 写入数据行
    for exercise in exercises:
        # 获取选项文本
        choices_text = ""
        if exercise.question_type in ['single', 'multiple']:
            choices = exercise.choices.all().order_by('order')
            choices_list = []
            for choice in choices:
                prefix = "✓" if choice.is_correct else ""
                choices_list.append(f"{prefix}{choice.content}")
            choices_text = " | ".join(choices_list)
        elif exercise.question_type == 'judgment':
            choices_text = "正确 | 错误"

        # 获取答案
        answer_text = exercise.answer if exercise.answer else ""

        # 获取关联知识点
        knowledge_points = []
        for qmatrix in exercise.qmatrix_set.select_related('knowledge_point').all():
            knowledge_points.append(qmatrix.knowledge_point.name)
        knowledge_text = " | ".join(knowledge_points)

        # 获取创建时间
        created_at = ""
        if hasattr(exercise, 'created_at') and exercise.created_at:
            created_at = exercise.created_at.strftime('%Y-%m-%d %H:%M:%S')

        writer.writerow([
            exercise.id,
            exercise.title,
            exercise.content.replace('\n', ' ').replace('\r', ''),
            exercise.subject.name if exercise.subject else "",
            exercise.get_question_type_display() if hasattr(exercise,
                                                            'get_question_type_display') else exercise.question_type,
            choices_text,
            answer_text,
            exercise.creator.username if exercise.creator else "",
            created_at,
            knowledge_text
        ])

    return response