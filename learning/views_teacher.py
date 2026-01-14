from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from django.views.decorators.http import require_POST, require_GET
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .forms import ExerciseForm
from django.db.models import Count, Q
from django.db import transaction
import csv
import json
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from .models import *
#教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

# 教师面板
@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    # 获取当前教师
    teacher = request.user

    # 1. 获取教师授课的课程（使用TeacherSubject关系）
    # 方法1：通过TeacherSubject中间表
    teaching_subjects = Subject.objects.filter(
        teachers__teacher=teacher
    ).distinct()
    teacher_count = teaching_subjects.count()

    # 2. 授课知识点数量（只统计教师授课课程的知识点）
    total_knowledge_points = KnowledgePoint.objects.filter(
        subject__in=teaching_subjects
    ).count()

    # 3. 授课学生总数（统计所有选择教师授课课程的学生）
    total_students = User.objects.filter(
        enrolled_subjects__subject__in=teaching_subjects
    ).distinct().count()

    # 4. 授课活跃学生数（最近30天有答题记录的学生）
    from datetime import datetime, timedelta

    thirty_days_ago = datetime.now() - timedelta(days=30)

    active_students = User.objects.filter(
        enrolled_subjects__subject__in=teaching_subjects
    ).filter(
        answerlog__submitted_at__gte=thirty_days_ago
    ).distinct().count()

    # 5. 获取所有课程（如果需要显示全部课程）
    all_subjects = Subject.objects.all()

    # 6. 教师上传的习题文件数量
    exercise_files_count = ExerciseFile.objects.filter(teacher=teacher).count()

    # 7. 教师创建的习题数量（跨所有科目）
    # 因为你的习题模型有creator字段，可以这样统计
    from django.db.models import Count

    # 统计教师创建的所有习题
    total_exercises_created = Exercise.objects.filter(creator=teacher).count()

    return render(request, 'teacher/teacher_dashboard.html', {
        'subjects': all_subjects,  # 所有课程
        'teaching_subjects': teaching_subjects,  # 教师授课的课程
        'teacher_count': teacher_count,  # 授课课程数量
        'total_knowledge_points': total_knowledge_points,
        'total_students': total_students,
        'active_students': active_students,
        'exercise_files_count': exercise_files_count,
        'total_exercises_created': total_exercises_created,
        'teacher': teacher,  # 传递教师对象到模板
    })

# 老师选择授课
@login_required
@user_passes_test(is_teacher)
def teacher_subject_management(request):
    """教师课程（Subject）管理页面"""
    # 获取所有课程（Subject）
    all_subjects = Subject.objects.all()
    # 获取教师已选授课课程
    teaching_subjects = TeacherSubject.objects.filter(teacher=request.user).select_related('subject')

    # 关键：预处理已选授课课程的ID列表（视图中完成，避免模板中调用复杂方法）
    teaching_subject_ids = [teaching.subject.id for teaching in teaching_subjects]

    if request.method == 'POST':
        subject_id = request.POST.get('subject_id')
        action = request.POST.get('action')

        if action == 'add' and subject_id:
            subject = get_object_or_404(Subject, id=subject_id)
            TeacherSubject.objects.get_or_create(teacher=request.user, subject=subject)
            messages.success(request, f'已成功选择教授《{subject.name}》课程')
        elif action == 'remove' and subject_id:
            TeacherSubject.objects.filter(teacher=request.user, subject_id=subject_id).delete()
            messages.success(request, '已取消授课')

        return redirect('teacher_subject_management')

    context = {
        'all_subjects': all_subjects,
        'teaching_subjects': teaching_subjects,
        'teaching_subject_ids': teaching_subject_ids,  # 传递预处理后的ID列表
    }
    return render(request, 'teacher/subject_management.html', context)

# 学生信息显示
@login_required
@user_passes_test(is_teacher)
def student_info(request):
    teacher = request.user

    # 1. 获取教师所授的科目
    teacher_subjects = TeacherSubject.objects.filter(teacher=teacher).select_related('subject')

    # 2. 获取当前选中的科目
    subject_id = request.GET.get('subject')
    current_subject = None
    students = []

    if teacher_subjects.exists():
        # 如果有科目ID参数，使用该科目
        if subject_id:
            try:
                current_subject = Subject.objects.get(
                    id=subject_id,
                    teachers__teacher=teacher
                )
            except Subject.DoesNotExist:
                # 如果教师没有权限查看该科目，使用第一个科目
                current_subject = teacher_subjects.first().subject
        else:
            # 没有科目参数，使用第一个科目
            current_subject = teacher_subjects.first().subject

        # 3. 获取选了当前科目的学生
        enrolled_students = StudentSubject.objects.filter(
            subject=current_subject
        ).select_related('student', 'student__studentprofile')
        students = [enrollment.student for enrollment in enrolled_students]

    # 4. 统计活跃学生（当前科目下）
    week_ago = timezone.now() - timedelta(days=7)
    active_students_count = 0
    if students and current_subject:
        active_students_count = AnswerLog.objects.filter(
            student__in=[s.id for s in students],
            exercise__subject=current_subject,
            submitted_at__gte=week_ago
        ).values('student').distinct().count()

    # 5. 分页处理
    paginator = Paginator(students, 10)
    page_number = request.GET.get('page')
    page_students = paginator.get_page(page_number)

    # 6. 为每个学生添加学习统计数据（当前科目下）
    for student in page_students:
        if current_subject:
            # 获取学生当前科目的答题记录
            answer_logs = AnswerLog.objects.filter(
                student=student,
                exercise__subject=current_subject
            )
        else:
            answer_logs = AnswerLog.objects.filter(student=student)

        # 不重复的习题数量
        student.total_exercises = answer_logs.values('exercise').distinct().count()

        # 计算正确率（基于习题的正确率）
        if student.total_exercises > 0:
            # 获取学生做过的所有习题ID（去重）
            exercise_ids = answer_logs.values_list('exercise', flat=True).distinct()

            # 计算有多少个习题学生至少做对过一次
            correct_exercises = 0
            for exercise_id in exercise_ids:
                if answer_logs.filter(exercise_id=exercise_id, is_correct=True).exists():
                    correct_exercises += 1

            student.accuracy = (correct_exercises / student.total_exercises) * 100
        else:
            student.accuracy = 0

        # 最后学习时间
        last_log = answer_logs.order_by('-submitted_at').first()
        student.last_active = last_log.submitted_at if last_log else None

    # 7. 准备上下文
    context = {
        'students': page_students,
        'total_students': len(students),
        'active_students': active_students_count,
        'teacher_subjects': teacher_subjects,
        'current_subject': current_subject,
        'teacher_subjects_count': teacher_subjects.count(),
        'subjects': Subject.objects.all(),
    }

    return render(request, 'teacher/student_info.html', context)

#学生做题记录
@login_required
@user_passes_test(is_teacher)
def get_student_answer_records(request, student_id):
    """获取学生做题记录API"""
    try:
        teacher = request.user

        # 1. 验证学生存在
        student = User.objects.get(id=student_id, user_type='student')

        # 2. 获取科目ID参数
        subject_id = request.GET.get('subject_id')

        # 3. 验证教师权限（如果指定了科目）
        if subject_id:
            # 验证教师是否有权限查看该科目
            if not TeacherSubject.objects.filter(
                    teacher=teacher,
                    subject_id=subject_id
            ).exists():
                return JsonResponse({
                    'status': 'error',
                    'message': '您没有权限查看该科目的记录'
                }, status=403)

        # 4. 构建查询 - 包含exercise的content字段
        answer_logs = AnswerLog.objects.filter(
            student=student
        ).select_related('exercise', 'exercise__subject')

        # 5. 如果指定了科目，进行过滤
        if subject_id:
            answer_logs = answer_logs.filter(exercise__subject_id=subject_id)

        # 6. 排序和限制数量
        total_records = answer_logs.count()
        answer_logs = answer_logs.order_by('-submitted_at')[:50]  # 限制最近50条

        # 7. 准备记录数据 - 将 exercise_title 改为 exercise_content
        records = []
        for log in answer_logs:
            # 截取内容，避免过长
            content = log.exercise.content+log.exercise.option_text


            records.append({
                'submitted_at': log.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'exercise_content': content,  # 改为content
                'subject_name': log.exercise.subject.name,
                'is_correct': bool(log.is_correct),
                'time_spent': log.time_spent,
            })

        # 8. 返回数据
        data = {
            'status': 'success',
            'student_name': student.username,
            'total_records': total_records,
            'records': records
        }

        print(f"DEBUG: 返回实际数据 - 学生: {student.username}, 记录数: {total_records}")
        return JsonResponse(data)

    except User.DoesNotExist:
        print(f"DEBUG: 学生不存在 - ID: {student_id}")
        return JsonResponse({
            'status': 'error',
            'message': '学生不存在'
        }, status=404)

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"DEBUG: 发生异常: {e}")
        print(f"DEBUG: 错误追踪: {error_trace}")

        return JsonResponse({
            'status': 'error',
            'message': f'服务器错误: {str(e)}'
        }, status=500)

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





#"""题库管理主页面"""
@login_required
@user_passes_test(is_teacher)
def exercise_management(request):
    # 获取当前老师授课的科目ID列表
    teacher_subjects = TeacherSubject.objects.filter(
        teacher=request.user
    ).select_related('subject')

    # 获取科目ID列表
    teacher_subject_ids = list(teacher_subjects.values_list('subject_id', flat=True))

    # 如果老师没有授课科目，返回特殊页面
    if not teacher_subject_ids:
        context = {
            'no_subjects': True,
            'message': '您还没有分配授课科目，无法管理习题。'
        }
        return render(request, 'teacher/exercise_management.html', context)

    # 获取默认科目（第一个授课科目）
    default_subject = teacher_subjects.first().subject

    # 基础查询集 - 只查询老师授课科目的习题
    exercises = Exercise.objects.filter(
        subject_id__in=teacher_subject_ids
    ).select_related('subject', 'creator').prefetch_related(
        'qmatrix_set__knowledge_point'
    )

    # 获取所有筛选参数
    subject_id = request.GET.get('subject')
    question_type = request.GET.get('question_type')
    knowledge_point_id = request.GET.get('knowledge_point')
    creator_id = request.GET.get('creator')
    search = request.GET.get('search')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # 如果没有指定科目，使用默认科目
    if not subject_id and default_subject:
        subject_id = str(default_subject.id)
        exercises = exercises.filter(subject_id=default_subject.id)

    # 应用筛选条件
    if subject_id and subject_id.isdigit():
        # 确保筛选的科目在老师授课范围内
        if int(subject_id) in teacher_subject_ids:
            exercises = exercises.filter(subject_id=int(subject_id))

    if question_type:
        exercises = exercises.filter(question_type=question_type)

    if knowledge_point_id and knowledge_point_id.isdigit():
        exercises = exercises.filter(
            qmatrix__knowledge_point_id=int(knowledge_point_id)
        ).distinct()

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

    # 获取筛选所需的数据 - 只获取老师授课的相关数据
    subjects = Subject.objects.filter(id__in=teacher_subject_ids)

    # 根据当前筛选的科目获取知识点
    current_subject_id = subject_id if subject_id and subject_id.isdigit() else default_subject.id if default_subject else None
    if current_subject_id:
        knowledge_points = KnowledgePoint.objects.filter(
            subject_id=current_subject_id
        )
    else:
        knowledge_points = KnowledgePoint.objects.none()

    # 获取在当前筛选科目下创建习题的教师
    if current_subject_id:
        creator_ids = Exercise.objects.filter(
            subject_id=current_subject_id
        ).values_list('creator_id', flat=True).distinct()
        creators = User.objects.filter(
            user_type='teacher',
            id__in=creator_ids
        )
    else:
        creators = User.objects.none()

    # 排序和分页
    exercises = exercises.order_by('id')  # 按ID降序，最新的在前面

    # 分页 - 每页20条
    paginator = Paginator(exercises, 20)
    page_number = request.GET.get('page')
    page_exercises = paginator.get_page(page_number)

    context = {
        'exercises': page_exercises,
        'subjects': subjects,
        'knowledge_points': knowledge_points,
        'creators': creators,
        'teacher_subjects': teacher_subject_ids,
        'no_subjects': False,
        'default_subject_id': default_subject.id if default_subject else None,
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
def exercise_detail_json(request, exercise_id):
    """获取习题详情的JSON数据（用于模态框）"""
    try:
        # 获取习题详情
        exercise = get_object_or_404(
            Exercise.objects.select_related('subject', 'creator')
                .prefetch_related('qmatrix_set__knowledge_point'),
            id=exercise_id
        )

        # 检查权限：老师只能查看自己授课科目的习题
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)

        if teacher_subjects and exercise.subject_id not in teacher_subjects:
            return JsonResponse({
                'success': False,
                'message': '您无权查看此习题。'
            })

        # 获取关联的知识点
        knowledge_points = list(exercise.qmatrix_set.select_related('knowledge_point')
                                .values('knowledge_point__id', 'knowledge_point__name', 'weight'))

        # 手动映射题型
        question_type_mapping = {
            'single': '单选题',
            'multiple': '多选题',
            'vote': '投票题',
            'fill': '填空题',
            'subjective': '主观题',
            'judgment': '判断题',
            '1': '单选题',
            '2': '多选题',
            '3': '投票题',
            '4': '填空题',
            '5': '主观题',
            '6': '判断题',
        }

        # 获取题型显示名称
        question_type_display = question_type_mapping.get(
            exercise.question_type,
            exercise.question_type  # 如果不在映射中，使用原值
        )

        # 获取习题详情数据
        exercise_data = {
            'id': exercise.id,
            'title': exercise.title or '无标题',
            'content': exercise.content,
            'answer': exercise.answer or '暂无答案',
            'option_text': exercise.option_text or '无选项',
            'question_type': question_type_display,
            'question_type_code': exercise.question_type,
            'subject': exercise.subject.name if exercise.subject else '未分类',
            'creator': exercise.creator.get_full_name() or exercise.creator.username,
            'created_at': exercise.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(exercise, 'created_at') else '',
            'knowledge_points': knowledge_points,
        }

        return JsonResponse({
            'success': True,
            'exercise': exercise_data
        })

    except Exception as e:
        print(f"获取习题详情JSON错误: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取习题详情时出错: {str(e)}'
        })

"""编辑习题"""
@login_required
@user_passes_test(is_teacher)
@require_POST
def exercise_update_json(request, exercise_id):
    """更新习题的JSON API"""
    try:
        # 获取习题
        exercise = get_object_or_404(Exercise, id=exercise_id)

        # 修正权限逻辑：老师可以编辑所有习题，但科目权限需要检查
        # 检查科目权限
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)

        # 获取新科目ID
        new_subject_id = request.POST.get('subject_id')

        # 如果指定了新科目，检查权限
        if new_subject_id:
            if int(new_subject_id) not in teacher_subjects:
                return JsonResponse({
                    'success': False,
                    'message': '您无权在此科目下创建或修改习题。'
                })
            # 更新科目
            try:
                exercise.subject_id = int(new_subject_id)
            except (ValueError, TypeError):
                pass
        else:
            # 保持原科目，检查原科目权限
            if exercise.subject_id not in teacher_subjects:
                return JsonResponse({
                    'success': False,
                    'message': '您无权修改此科目的习题。'
                })

        # 更新基本字段
        exercise.title = request.POST.get('title', exercise.title)
        exercise.content = request.POST.get('content', exercise.content)

        # 处理题型
        question_type = request.POST.get('question_type', exercise.question_type)
        exercise.question_type = question_type

        # 处理选项
        option_text = request.POST.get('option_text', exercise.option_text)
        exercise.option_text = option_text if option_text else None

        exercise.answer = request.POST.get('answer', exercise.answer)

        # 保存习题
        exercise.save()

        # 处理知识点关联
        knowledge_points_json = request.POST.get('knowledge_points', '[]')
        try:
            knowledge_points_data = json.loads(knowledge_points_json)

            # 删除旧的关联
            exercise.qmatrix_set.all().delete()

            # 创建新的关联
            for kp_data in knowledge_points_data:
                knowledge_point_id = kp_data.get('id')
                weight = kp_data.get('weight', 1.0)

                try:
                    knowledge_point = KnowledgePoint.objects.get(id=knowledge_point_id)
                    # 确保知识点属于当前科目
                    if knowledge_point.subject_id == exercise.subject_id:
                        QMatrix.objects.create(
                            knowledge_point=knowledge_point,
                            exercise=exercise,
                            weight=float(weight)
                        )
                except (KnowledgePoint.DoesNotExist, ValueError):
                    continue

        except json.JSONDecodeError:
            # 如果JSON解析失败，跳过知识点处理
            pass

        return JsonResponse({
            'success': True,
            'message': '习题更新成功！',
            'exercise_id': exercise.id
        })

    except Exception as e:
        print(f"更新习题JSON错误: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'更新习题时出错: {str(e)}'
        })

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