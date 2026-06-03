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
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from .models import *
import logging

logger = logging.getLogger(__name__)
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
    thirty_days_ago = timezone.now() - timedelta(days=30)

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

    # 8. 学生活跃度分布（按周几统计最近30天的活跃学生）
    
    activity_by_day = [0] * 7  # 周一到周日
    for i in range(7):
        day_start = timezone.now() - timedelta(days=30-i)
        day_end = day_start + timedelta(days=1)
        active_count = AnswerLog.objects.filter(
            student__enrolled_subjects__subject__in=teaching_subjects,
            submitted_at__gte=day_start,
            submitted_at__lt=day_end
        ).values('student').distinct().count()
        activity_by_day[i] = active_count

    # 9. 授课科目分布（统计每个科目的学生数）
    subject_distribution = []
    subject_labels = []
    teaching_subjects_data = []
    
    for subject in teaching_subjects:
        student_count = User.objects.filter(
            enrolled_subjects__subject=subject
        ).distinct().count()
        exercise_count = Exercise.objects.filter(subject=subject).count()
        knowledge_point_count = KnowledgePoint.objects.filter(subject=subject).count()
        
        subject_distribution.append(student_count)
        subject_labels.append(subject.name)
        teaching_subjects_data.append({
            'name': subject.name,
            'exercise_count': exercise_count,
            'knowledge_point_count': knowledge_point_count,
            'student_count': student_count
        })

    return render(request, 'teacher/teacher_dashboard.html', {
        'subjects': all_subjects,  # 所有课程
        'teaching_subjects': teaching_subjects,  # 教师授课的课程
        'teaching_subjects_data': teaching_subjects_data,  # 教师授课课程的详细数据
        'teacher_count': teacher_count,  # 授课课程数量
        'total_knowledge_points': total_knowledge_points,
        'total_students': total_students,
        'active_students': active_students,
        'exercise_files_count': exercise_files_count,
        'total_exercises_created': total_exercises_created,
        'teacher': teacher,  # 传递教师对象到模板
        'activity_by_day': activity_by_day,  # 学生活跃度分布
        'subject_distribution': subject_distribution,  # 科目分布数据
        'subject_labels': subject_labels,  # 科目标签
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

@login_required
@user_passes_test(is_teacher)
def teacher_create_subject(request):
    """教师创建新课程并直接进入授课管理界面"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, '课程名称不能为空')
            return redirect('teacher_course_management')

        # 创建新课程
        subject = Subject.objects.create(name=name, description=description)

        # 创建教师授课关系
        TeacherSubject.objects.get_or_create(teacher=request.user, subject=subject)

        messages.success(request, f'课程《{name}》创建成功！')
        return redirect(reverse('upload_resource') + f'?subject_id={subject.id}')

    return redirect('teacher_course_management')


@login_required
@user_passes_test(is_teacher)
@require_POST
def subject_delete(request, subject_id):
    """删除课程（Subject）及其所有相关数据"""
    subject = get_object_or_404(Subject, id=subject_id)
    subject_name = subject.name
    subject.delete()
    messages.success(request, f'课程《{subject_name}》已成功删除')
    return redirect('teacher_subject_management')

@login_required
@user_passes_test(is_teacher)
def teacher_course_management(request):
    """教师课程管理页面"""
    # 获取教师授课的科目
    teaching_subjects = TeacherSubject.objects.filter(teacher=request.user).select_related('subject')
    
    context = {
        'teaching_subjects': teaching_subjects,
    }
    return render(request, 'teacher/course_management.html', context)

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

    # 6. 为每个学生添加学习统计数据（当前科目下）- 优化查询
    if current_subject and page_students:
        # 一次性获取所有学生的答题记录
        student_ids = [s.id for s in page_students]
        all_answer_logs = AnswerLog.objects.filter(
            student_id__in=student_ids,
            exercise__subject=current_subject
        ).select_related('exercise').values('student_id', 'exercise_id', 'is_correct', 'submitted_at')
        
        # 按学生ID分组处理数据
        student_logs_map = {}
        for log in all_answer_logs:
            student_id = log['student_id']
            if student_id not in student_logs_map:
                student_logs_map[student_id] = []
            student_logs_map[student_id].append(log)
        
        # 为每个学生计算统计数据
        for student in page_students:
            logs = student_logs_map.get(student.id, [])
            
            # 不重复的习题数量
            exercise_ids = set(log['exercise_id'] for log in logs)
            student.total_exercises = len(exercise_ids)
            
            # 计算正确率
            if student.total_exercises > 0:
                correct_exercises = 0
                for exercise_id in exercise_ids:
                    if any(log['exercise_id'] == exercise_id and log['is_correct'] for log in logs):
                        correct_exercises += 1
                student.accuracy = (correct_exercises / student.total_exercises) * 100
            else:
                student.accuracy = 0
            
            # 最后学习时间
            if logs:
                last_log = max(logs, key=lambda x: x['submitted_at'])
                student.last_active = last_log['submitted_at']
            else:
                student.last_active = None
    else:
        # 如果没有当前科目或没有学生，设置默认值
        for student in page_students:
            student.total_exercises = 0
            student.accuracy = 0
            student.last_active = None

    # 7. 准备上下文
    context = {
        'students': page_students,
        'total_students': len(students),
        'active_students': active_students_count,
        'teacher_subjects': teacher_subjects,
        'current_subject': current_subject,
        'subject': current_subject,  # 为course_management_base.html提供subject
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
        type_mapping = {
            '1': ['1'],
            '2': ['2'],
            '3': ['3'],
            '4': ['4'],
            '5': ['5'],
            '6': ['6'],
        }
        type_filter = type_mapping.get(question_type, [question_type])
        exercises = exercises.filter(question_type__in=type_filter)

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

    # 获取当前科目下创建习题的教师
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

    # 获取教师所有授课科目的知识点（供添加/编辑习题使用）
    all_knowledge_points = list(KnowledgePoint.objects.filter(
        subject_id__in=teacher_subject_ids
    ).values('id', 'name', 'subject_id'))

    # 排序和分页
    exercises = exercises.order_by('id')  # 按ID降序，最新的在前面

    # 分页 - 每页10条
    paginator = Paginator(exercises, 10)
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
        'subject': Subject.objects.get(id=current_subject_id) if current_subject_id else None,
        'all_knowledge_points': all_knowledge_points,
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
                .prefetch_related('qmatrix_set__knowledge_point', 'choices'),
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

        # 获取选项列表
        choices = list(exercise.choices.order_by('order').values('id', 'content', 'is_correct', 'order'))

        # 获取当前科目的所有知识点
        all_knowledge_points = list(KnowledgePoint.objects.filter(
            subject_id=exercise.subject_id
        ).values('id', 'name'))

        # 手动映射题型
        question_type_mapping = {
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
            'solution': exercise.solution or '',
            'option_text': exercise.option_text or '',
            'choices': choices,
            'question_type': question_type_display,
            'question_type_code': exercise.question_type,
            'subject': exercise.subject.name if exercise.subject else '未分类',
            'subject_id': exercise.subject_id,
            'creator': exercise.creator.get_full_name() or exercise.creator.username,
            'created_at': exercise.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(exercise, 'created_at') and exercise.created_at else '',
            'knowledge_points': knowledge_points,
            'all_knowledge_points': all_knowledge_points,
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
        else:
            # 保持原科目，检查原科目权限
            if exercise.subject_id not in teacher_subjects:
                return JsonResponse({
                    'success': False,
                    'message': '您无权修改此科目的习题。'
                })

        # 更新题目内容
        exercise.content = request.POST.get('content', exercise.content)
        
        # 更新答案解析
        exercise.solution = request.POST.get('solution', exercise.solution)

        # 保存习题
        exercise.save()

        # 处理选项更新
        choices_json = request.POST.get('choices', '[]')
        try:
            choices_data = json.loads(choices_json)
            for choice_item in choices_data:
                choice_id = choice_item.get('id')
                choice_content = choice_item.get('content', '')
                if choice_id and choice_content:
                    try:
                        choice = Choice.objects.get(id=choice_id, exercise=exercise)
                        choice.content = choice_content
                        choice.save()
                    except Choice.DoesNotExist:
                        continue
        except json.JSONDecodeError:
            pass

        # 处理知识点关联（Q矩阵）
        knowledge_points_json = request.POST.get('knowledge_points', '[]')
        try:
            knowledge_points_data = json.loads(knowledge_points_json)

            # 删除旧的关联
            exercise.qmatrix_set.all().delete()

            # 创建新的关联
            for kp_data in knowledge_points_data:
                knowledge_point_id = kp_data.get('id')
                # 如果没有权重，使用默认值 1.0
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

"""添加习题 - JSON API"""
@login_required
@user_passes_test(is_teacher)
@require_POST
def exercise_add_json(request):
    """通过JSON API添加习题"""
    try:
        # 获取表单数据
        subject_id = request.POST.get('subject_id')
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        question_type = request.POST.get('question_type', '1')
        answer = request.POST.get('answer', '').strip()
        solution = request.POST.get('solution', '').strip()
        choices_json = request.POST.get('choices', '[]')

        # 验证必填字段
        if not subject_id:
            return JsonResponse({'success': False, 'message': '请选择科目'})
        if not title:
            return JsonResponse({'success': False, 'message': '请输入习题标题'})
        if not content:
            return JsonResponse({'success': False, 'message': '请输入习题内容'})

        # 检查科目权限
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)

        if int(subject_id) not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '您无权在此科目下添加习题'})

        with transaction.atomic():
            # 构建 option_text
            try:
                choices_data = json.loads(choices_json)
                opt_dict = {}
                for idx, choice_item in enumerate(choices_data):
                    label = chr(65 + idx)  # A, B, C, D...
                    choice_content = choice_item.get('content', '').strip()
                    if choice_content:
                        opt_dict[label] = choice_content
                full_option_text = repr(opt_dict) if opt_dict else ""
            except json.JSONDecodeError:
                choices_data = []
                full_option_text = ""

            # 创建习题
            exercise = Exercise.objects.create(
                subject_id=int(subject_id),
                title=title,
                content=content,
                question_type=question_type,
                option_text=full_option_text,
                answer=answer,
                solution=solution,
                creator=request.user
            )

            # 处理选项
            for choice_item in choices_data:
                choice_content = choice_item.get('content', '').strip()
                if choice_content:
                    Choice.objects.create(
                        exercise=exercise,
                        content=choice_content,
                        is_correct=choice_item.get('is_correct', False),
                        order=choice_item.get('order', 0)
                    )

            # 关联知识点
            knowledge_points_json = request.POST.get('knowledge_points', '[]')
            try:
                kp_ids = json.loads(knowledge_points_json)
                for kp_id in kp_ids:
                    if kp_id:
                        QMatrix.objects.get_or_create(
                            exercise=exercise,
                            knowledge_point_id=int(kp_id),
                            defaults={'weight': 1.0}
                        )
            except json.JSONDecodeError:
                pass

            return JsonResponse({
                'success': True,
                'message': '习题添加成功！',
                'exercise_id': exercise.id
            })

    except Exception as e:
        print(f"添加习题JSON错误: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'添加习题时出错: {str(e)}'
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
                    question_type = form.cleaned_data.get('question_type', '1')

                    if question_type in ['1', '2', '3']:
                        # 处理选择题（含投票题）
                        choices_data = request.POST.getlist('choices')
                        is_correct_data = request.POST.getlist('is_correct')

                        # 设置答案
                        correct_choices = []
                        for i, choice_text in enumerate(choices_data):
                            if choice_text.strip():  # 非空选项
                                is_correct = str(i) in is_correct_data
                                if is_correct:
                                    correct_choices.append(choice_text.strip())

                        if question_type == '1' and len(correct_choices) > 1:
                            form.add_error(None, '单选题只能有一个正确答案')
                            return render(request, 'teacher/exercise_form.html', {'form': form})

                        if question_type != '3':
                            exercise.answer = ', '.join(correct_choices)
                        else:
                            exercise.answer = ''
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

                    elif question_type == '6':
                        # 处理判断题
                        is_correct = form.cleaned_data.get('judgment_answer')
                        exercise.answer = '正确' if is_correct else '错误'
                        exercise.save()

                    elif question_type in ['4', '5']:
                        # 处理填空题和主观题
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
@login_required
@user_passes_test(is_teacher)
def exercise_delete(request, exercise_id):

    if request.method == 'POST':
        try:
            exercise = Exercise.objects.get(id=exercise_id)

            # 检查权限：教师只能删除自己授课科目的习题
            teacher_subjects = TeacherSubject.objects.filter(
                teacher=request.user
            ).values_list('subject_id', flat=True)
            
            if exercise.subject_id not in teacher_subjects:
                return JsonResponse({
                    'success': False,
                    'message': '您无权删除此科目的习题'
                }, status=403)

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
        type_mapping = {
            '1': ['1'],
            '2': ['2'],
            '3': ['3'],
            '4': ['4'],
            '5': ['5'],
            '6': ['6'],
        }
        type_filter = type_mapping.get(question_type, [question_type])
        exercises = exercises.filter(question_type__in=type_filter)

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
        if exercise.question_type in ['1', '2']:
            choices = exercise.choices.all().order_by('order')
            choices_list = []
            for choice in choices:
                prefix = "✓" if choice.is_correct else ""
                choices_list.append(f"{prefix}{choice.content}")
            choices_text = " | ".join(choices_list)
        elif exercise.question_type == '6':
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


"""批改主观题作业"""
@login_required
@user_passes_test(is_teacher)
def grade_subjective(request):
    """主观题批改页面"""
    teacher = request.user
    
    # 获取教师授课的科目
    teacher_subjects = TeacherSubject.objects.filter(
        teacher=teacher
    ).select_related('subject')
    
    teacher_subject_ids = list(teacher_subjects.values_list('subject_id', flat=True))
    
    if not teacher_subject_ids:
        return render(request, 'teacher/grade_subjective.html', {
            'no_subjects': True
        })
    
    # 获取筛选参数
    subject_id = request.GET.get('subject_id')  # 从课程管理页面传递的科目ID
    exercise_id = request.GET.get('exercise')  # 按题目筛选
    status = request.GET.get('status', 'pending')  # pending: 待批改, graded: 已批改
    
    # 如果没有指定科目，使用第一个授课科目
    if not subject_id:
        subject_id = teacher_subject_ids[0] if teacher_subject_ids else None
    elif not (int(subject_id) in teacher_subject_ids):
        # 如果指定的科目不在授课范围内，使用第一个
        subject_id = teacher_subject_ids[0] if teacher_subject_ids else None
    
    # 基础查询：主观题的答题记录 (question_type = '5')
    answer_logs = AnswerLog.objects.filter(
        exercise__subject_id__in=teacher_subject_ids,
        exercise__question_type__in=['5']
    ).select_related('student', 'exercise', 'exercise__subject').order_by('-submitted_at')
    
    # 按科目筛选
    if subject_id:
        answer_logs = answer_logs.filter(exercise__subject_id=int(subject_id))
    
    # 按题目筛选
    if exercise_id and exercise_id.isdigit():
        answer_logs = answer_logs.filter(exercise_id=int(exercise_id))
    
    # 按状态筛选
    if status == 'pending':
        answer_logs = answer_logs.filter(is_correct__isnull=True)
    elif status == 'graded':
        answer_logs = answer_logs.filter(is_correct__isnull=False)
    
    # 统计数量
    pending_count = AnswerLog.objects.filter(
        exercise__subject_id__in=teacher_subject_ids,
        exercise__question_type__in=['5'],
        is_correct__isnull=True
    ).count()
    
    graded_count = AnswerLog.objects.filter(
        exercise__subject_id__in=teacher_subject_ids,
        exercise__question_type__in=['5'],
        is_correct__isnull=False
    ).count()
    
    # 获取当前科目的所有主观题
    exercises = Exercise.objects.filter(
        subject_id=subject_id,
        question_type__in=['5']
    ).order_by('title')
    
    # 分页
    paginator = Paginator(answer_logs, 20)
    page_number = request.GET.get('page')
    page_logs = paginator.get_page(page_number)
    
    context = {
        'answer_logs': page_logs,
        'exercises': exercises,
        'current_subject': subject_id,
        'current_exercise': exercise_id,
        'current_status': status,
        'pending_count': pending_count,
        'graded_count': graded_count,
        'no_subjects': False,
        'subject': Subject.objects.get(id=subject_id) if subject_id else None,
    }
    
    return render(request, 'teacher/grade_subjective.html', context)


@login_required
@user_passes_test(is_teacher)
def get_answer_detail(request, log_id):
    """获取答题详情"""
    try:
        log = get_object_or_404(
            AnswerLog.objects.select_related('student', 'exercise', 'exercise__subject'),
            id=log_id
        )
        
        # 检查权限
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)
        
        if log.exercise.subject_id not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权查看此记录'})
        
        cached_score = None
        try:
            from .ai_scoring.scoring_agent import get_cached_score
            cached_score = get_cached_score(log.id)
        except Exception:
            pass

        data = {
            'success': True,
            'log': {
                'id': log.id,
                'student_name': f"{log.student.first_name}{log.student.last_name}" if log.student.first_name else log.student.username,
                'exercise_title': log.exercise.title,
                'exercise_content': log.exercise.content,
                'exercise_answer': log.exercise.answer or '',
                'exercise_solution': log.exercise.solution or '',
                'text_answer': log.text_answer or '',
                'is_correct': log.is_correct,
                'submitted_at': log.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'subject_name': log.exercise.subject.name
            },
            'cached_score': cached_score,
        }
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

# 1. 手动评分（最核心的写回接口）
@login_required
@user_passes_test(is_teacher)
@require_POST
def grade_answer(request, log_id):
    """批改答题 — 接受分值，自动判定正确/错误"""
    try:
        log = get_object_or_404(AnswerLog, id=log_id)

        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)

        if log.exercise.subject_id not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权批改此记录'})

        # 兼容旧的 is_correct 参数
        is_correct = request.POST.get('is_correct')
        manual_score = request.POST.get('manual_score')

        if manual_score is not None:
            manual_score = float(manual_score)
        elif is_correct is not None:
            full = float(log.exercise.score)
            manual_score = full if is_correct == 'true' else 0.0
        else:
            return JsonResponse({'success': False, 'message': '请提供分值'})

        full_score = float(log.exercise.score)
        threshold = full_score * 0.6 if full_score > 0 else 0
        log.is_correct = manual_score >= threshold
        log.score = manual_score
        log.feedback = 'Manual score: {}/{}'.format(manual_score, full_score)
        log.graded_at = timezone.now()
        log.graded_by = request.user
        log.grading_confidence = None
        log.save()

        # 缓存评分结果（保留已有 AI 评分详情）
        try:
            from .ai_scoring.scoring_agent import _scoring_result_cache
            existing = _scoring_result_cache.get(str(log_id), {})
            manual_note = '【手动评分】{}/{}，判定：{}'.format(
                manual_score, full_score, '正确' if log.is_correct else '错误')
            # 合并：保留 AI 模型分数和过程，叠加手动评分信息
            merged = {
                'success': True,
                'final_score': manual_score,
                'full_score': full_score,
                'ds_score': existing.get('ds_score'),
                'km_score': existing.get('km_score'),
                'xf_score': existing.get('xf_score'),
                'manual': True,
                'process': (existing.get('process', '') + '\n' + manual_note).strip(),
            }
            _scoring_result_cache[str(log_id)] = merged
            try:
                from .ai_scoring.scoring_agent import _save_cache, _scoring_result_cache as cache_obj
                _save_cache(cache_obj)
            except Exception:
                pass
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': f'评分成功！{manual_score}/{full_score}',
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@user_passes_test(is_teacher)
@require_POST
def ai_grade_answer(request, log_id):
    """使用AI模型批改答题"""
    try:
        from .llm_grading import grade_subjective_answer
        
        log = get_object_or_404(AnswerLog, id=log_id)
        
        # 检查权限
        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)
        
        if log.exercise.subject_id not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权批改此记录'})
        
        # 调用LLM进行评分
        grading_result = grade_subjective_answer(
            exercise_content=log.exercise.content,
            reference_answer=log.exercise.answer or '',
            student_answer=log.text_answer or '',
            exercise_solution=log.exercise.solution or ''
        )
        
        if grading_result.get('error'):
            return JsonResponse({
                'success': False,
                'message': f"AI评分失败: {grading_result['error']}"
            })
        
        return JsonResponse({
            'success': True,
            'grading': {
                'is_correct': grading_result.get('is_correct'),
                'score': grading_result.get('score'),
                'feedback': grading_result.get('feedback'),
                'reasoning': grading_result.get('reasoning'),
                'confidence': grading_result.get('confidence')
            }
        })
        
    except Exception as e:
        import traceback
        logger.error(f"AI grading error: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'AI评分服务出错: {str(e)}'
        }, status=500)

# 2. 智能体评分（三模型仲裁）
@login_required
@user_passes_test(is_teacher)
@require_POST
def ai_agent_score(request, log_id):
    """使用智能体（三模型仲裁）评分，结果写入 is_correct + 返回详细 JSON"""
    try:
        from .ai_scoring.scoring_agent import auto_score_answer

        log = get_object_or_404(AnswerLog, id=log_id)

        teacher_subjects = TeacherSubject.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)

        if log.exercise.subject_id not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权批改此记录'})

        result = auto_score_answer(log_id)

        if not result.get('success'):
            return JsonResponse({'success': False, 'message': result.get('error', '评分失败')})

        full = result['full_score']
        score = result['final_score']
        threshold = full * 0.6 if full > 0 else 0
        log.is_correct = score >= threshold
        log.score = score
        log.ai_feedback = result.get('process', '')
        log.graded_at = timezone.now()
        log.graded_by = request.user
        log.grading_confidence = 0.85
        log.save()

        return JsonResponse({
            'success': True,
            'grading': {
                'is_correct': log.is_correct,
                'final_score': score,
                'full_score': full,
                'ds_score': result.get('ds_score'),
                'km_score': result.get('km_score'),
                'xf_score': result.get('xf_score'),
                'process': result.get('process', ''),
                'question': result.get('question', ''),
                'student_answer': result.get('student_answer', ''),
                'std_answer': result.get('std_answer', ''),
            }
        })

    except Exception as e:
        import traceback
        logger.error(f"Agent scoring error: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'智能体评分出错: {str(e)}'
        }, status=500)

# 3. 批量评分
@login_required
@user_passes_test(is_teacher)
@require_POST
def batch_ai_agent_score(request):
    """批量一键批改"""
    try:
        teacher = request.user
        subject_id = request.POST.get('subject_id') or request.GET.get('subject_id')

        teacher_subjects = TeacherSubject.objects.filter(
            teacher=teacher
        ).values_list('subject_id', flat=True)

        if not subject_id:
            return JsonResponse({'success': False, 'message': '请指定科目'})
        if int(subject_id) not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权批改此科目'})

        pending_logs = AnswerLog.objects.filter(
            exercise__subject_id=int(subject_id),
            exercise__question_type__in=['5'],
            is_correct__isnull=True,
        ).exclude(text_answer__isnull=True).exclude(text_answer='')

        total = pending_logs.count()
        if total == 0:
            return JsonResponse({'success': False, 'message': '没有待批改的记录'})

        from .ai_scoring.scoring_agent import auto_score_answer

        success_count = 0
        fail_count = 0
        results = []

        for log in pending_logs:
            result = auto_score_answer(log.id)
            if result.get('success'):
                full = result['full_score']
                score = result['final_score']
                threshold = full * 0.6 if full > 0 else 0
                log.is_correct = score >= threshold
                log.score = score
                log.ai_feedback = result.get('process', '')
                log.graded_at = timezone.now()
                log.graded_by = request.user
                log.grading_confidence = 0.85
                log.save()
                success_count += 1
                results.append({
                    'log_id': log.id,
                    'student': log.student.username,
                    'final_score': score,
                    'is_correct': log.is_correct,
                })
            else:
                fail_count += 1
                results.append({
                    'log_id': log.id,
                    'student': log.student.username,
                    'error': result.get('error', '评分失败'),
                })

        return JsonResponse({
            'success': True,
            'message': f'批量批改完成：成功 {success_count}，失败 {fail_count}，共 {total} 题',
            'total': total,
            'success_count': success_count,
            'fail_count': fail_count,
            'results': results,
        })

    except Exception as e:
        import traceback
        logger.error(f"Batch scoring error: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'批量批改出错: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def clear_grading_records(request):
    """临时功能：清除指定科目的批改记录（重置 is_correct + 清缓存）"""
    try:
        teacher = request.user
        subject_id = request.POST.get('subject_id') or request.GET.get('subject_id')

        teacher_subjects = TeacherSubject.objects.filter(
            teacher=teacher
        ).values_list('subject_id', flat=True)

        if not subject_id:
            return JsonResponse({'success': False, 'message': '请指定科目'})
        if int(subject_id) not in teacher_subjects:
            return JsonResponse({'success': False, 'message': '无权操作此科目'})

        logs_to_clear = AnswerLog.objects.filter(
            exercise__subject_id=int(subject_id),
            exercise__question_type__in=['5'],
            is_correct__isnull=False,
        )
        cleared_ids = list(logs_to_clear.values_list('id', flat=True))
        updated_count = logs_to_clear.update(
            is_correct=None,
            score=None,
            ai_feedback='',
            feedback='',
            graded_at=None,
            graded_by=None,
            grading_confidence=None,
        )

        try:
            from .ai_scoring.scoring_agent import _scoring_result_cache
            for lid in cleared_ids:
                _scoring_result_cache.pop(str(lid), None)
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': f'已清除 {updated_count} 条批改记录（含评分缓存）',
            'cleared_count': updated_count,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'清除失败: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(is_teacher)
def export_students(request):
    """导出选课学生列表 API"""
    try:
        teacher = request.user
        subject_id = request.GET.get('subject')
        
        if not subject_id:
            return JsonResponse({
                'success': False,
                'message': '请指定科目'
            })
        
        # 验证教师权限
        if not TeacherSubject.objects.filter(
            teacher=teacher,
            subject_id=subject_id
        ).exists():
            return JsonResponse({
                'success': False,
                'message': '您没有权限导出此科目的学生'
            }, status=403)
        
        # 获取所有选了该科目的学生
        enrolled_students = StudentSubject.objects.filter(
            subject_id=subject_id
        ).select_related('student', 'student__studentprofile')
        
        students_data = []
        for enrollment in enrolled_students:
            student = enrollment.student
            students_data.append({
                'name': f"{student.first_name}{student.last_name}" if student.first_name else student.username,
                'email': student.email or '无邮箱',
                'grade': student.studentprofile.grade if student.studentprofile else '-',
                'school': student.studentprofile.school if student.studentprofile else '-'
            })
        
        return JsonResponse({
            'success': True,
            'students': students_data
        })
    
    except Exception as e:
        import traceback
        print(f"导出学生列表错误: {e}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'message': f'导出失败: {str(e)}'
        }, status=500)
