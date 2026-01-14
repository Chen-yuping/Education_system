from ..models import *
from learning.models import DiagnosisModel
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
import json
from django.utils import timezone
#教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

# 添加诊断相关的视图函数
@login_required
@user_passes_test(is_teacher)
def diagnosis(request):
    """学生诊断分析页面"""
    teacher = request.user

    # 获取教师所授科目
    teacher_subjects = TeacherSubject.objects.filter(
        teacher=teacher
    ).select_related('subject')

    # 获取可用模型
    available_models = DiagnosisModel.objects.filter(
        is_active=True
    )

    context = {
        'teacher_subjects': teacher_subjects,
        'diagnosis_models': available_models,
    }

    return render(request, 'teacher/diagnosis.html', context)


@login_required
@user_passes_test(is_teacher)
def run_diagnosis(request):
    """运行诊断分析API"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        subject_id = data.get('subject_id')
        model_id = data.get('model_id')

        # 验证权限
        teacher = request.user
        if not TeacherSubject.objects.filter(
                teacher=teacher,
                subject_id=subject_id
        ).exists():
            return JsonResponse({
                'status': 'error',
                'message': '无权限访问该科目'
            }, status=403)

        # 获取科目和学生数据
        subject = Subject.objects.get(id=subject_id)
        students = StudentSubject.objects.filter(
            subject=subject
        ).select_related('student')

        # 获取诊断模型
        diagnosis_model = DiagnosisModel.objects.get(id=model_id)

        # 获取学生答题数据
        student_ids = [s.student.id for s in students]
        answer_logs = AnswerLog.objects.filter(
            student__in=student_ids,
            exercise__subject=subject
        ).select_related('exercise')

        # 这里应该调用实际的诊断模型算法
        # 例如: result = run_ncd_model(answer_logs, diagnosis_model)

        # 返回诊断结果
        result = {
            'status': 'success',
            'subject_name': subject.name,
            'total_students': len(students),
            'diagnosis_time': timezone.now().isoformat(),
            'analysis_data': generate_mock_analysis_data()  # 实际开发中替换为真实结果
        }

        return JsonResponse(result)

    except Exception as e:
        print(f"诊断分析错误: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'诊断分析失败: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(is_teacher)
def get_diagnosis_result(request, diagnosis_id):
    """获取诊断结果API"""
    # 获取特定诊断结果
    pass


@login_required
@user_passes_test(is_teacher)
def get_student_diagnosis_detail(request, student_id, subject_id):
    """获取学生详细诊断数据"""
    try:
        student = User.objects.get(id=student_id, user_type='student')
        subject = Subject.objects.get(id=subject_id)

        # 验证教师权限
        teacher = request.user
        if not TeacherSubject.objects.filter(
                teacher=teacher,
                subject=subject
        ).exists():
            return JsonResponse({
                'status': 'error',
                'message': '无权限访问'
            }, status=403)

        # 获取学生诊断数据
        diagnosis_data = StudentDiagnosis.objects.filter(
            student=student,
            knowledge_point__subject=subject
        ).select_related('knowledge_point')

        # 获取答题记录
        answer_logs = AnswerLog.objects.filter(
            student=student,
            exercise__subject=subject
        ).order_by('-submitted_at')[:20]

        # 构建响应数据
        result = {
            'status': 'success',
            'student_name': student.username,
            'subject_name': subject.name,
            'overall_mastery': calculate_overall_mastery(diagnosis_data),
            'knowledge_points': [
                {
                    'name': d.knowledge_point.name,
                    'mastery': d.mastery_level * 100,  # 转换为百分比
                    'practice_count': d.practice_count,
                    'correct_count': d.correct_count,
                    'last_practiced': d.last_practiced.strftime('%Y-%m-%d %H:%M') if d.last_practiced else None
                }
                for d in diagnosis_data
            ],
            'recent_logs': [
                {
                    'exercise_title': log.exercise.title,
                    'is_correct': log.is_correct,
                    'submitted_at': log.submitted_at.strftime('%Y-%m-%d %H:%M'),
                    'time_spent': log.time_spent
                }
                for log in answer_logs
            ]
        }

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


def calculate_overall_mastery(diagnosis_data):
    """计算总体掌握度"""
    if not diagnosis_data:
        return 0

    total_mastery = sum(d.mastery_level for d in diagnosis_data)
    return (total_mastery / len(diagnosis_data)) * 100