# D:\Project\Learning platform\Github\Education_system\learning\diagnosis\views_diagnosis.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, Avg, Q as DjangoQ, F, Sum
from django.db import transaction
from .data_export import export_training_data
from ..models import *
import threading
import os
import sys

# 教师身份判断
def is_teacher(user):
    return user.user_type == 'teacher'

"""学生诊断分析页面"""
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

"""运行诊断分析API"""
@login_required
@user_passes_test(is_teacher)
@csrf_exempt
def run_diagnosis(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        subject_id = data.get('subject_id')
        model_id = data.get('model_id')

        if not subject_id or not model_id:
            return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)

        # 验证权限
        teacher = request.user
        if not TeacherSubject.objects.filter(teacher=teacher, subject_id=subject_id).exists():
            return JsonResponse({'status': 'error', 'message': '无权限访问该科目'}, status=403)

        # 检查模型是否存在
        try:
            diagnosis_model = DiagnosisModel.objects.get(id=model_id, is_active=True)
        except DiagnosisModel.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '诊断模型不存在或已禁用'}, status=404)

        # 1. 导出训练数据
        try:
            export_result = export_training_data(subject_id)
            print(f"数据导出成功: {export_result}")
        except Exception as e:
            print(f"数据导出失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'数据导出失败: {str(e)}'}, status=500)

        # 2. 训练模型
        model_name = diagnosis_model.name
        if export_result['success']:
            run_training(subject_id, model_name)

        # 3. 推理获取诊断数据
        from inference_and_save import infer_and_get_diagnosis_data
        diagnosis_data = infer_and_get_diagnosis_data(subject_id, model_name)

        if diagnosis_data is None:
            return JsonResponse({'status': 'error', 'message': '推理失败'}, status=500)

        # 4. 构建响应数据
        subject = Subject.objects.get(id=subject_id)
        enrolled_students_count = StudentSubject.objects.filter(subject=subject).count()

        # 获取知识点覆盖信息
        covered_kp_ids = QMatrix.objects.filter(
            exercise__in=AnswerLog.objects.filter(
                exercise__subject=subject,
                is_correct__isnull=False
            ).values_list('exercise_id', flat=True).distinct()
        ).values_list('knowledge_point_id', flat=True).distinct()
        covered_kp_count = len(set(covered_kp_ids))

        # 计算平均掌握度
        overall_scores = [r['overall_score'] for r in diagnosis_data['diagnosis_results'].values()]
        avg_mastery = (sum(overall_scores) / len(overall_scores) * 100) if overall_scores else 0

        response_data = {
            'status': 'success',
            'message': f'诊断完成，共分析了{len(diagnosis_data["diagnosis_results"])}名学生',
            'diagnosis_summary': {
                'subject_name': subject.name,
                'subject_id': subject.id,
                'total_students': len(diagnosis_data['diagnosis_results']),
                'enrolled_students_count': enrolled_students_count,
                'diagnosed_students': len(diagnosis_data['diagnosis_results']),
                'total_kp_count': diagnosis_data['total_kp_count'],
                'covered_kp_count': covered_kp_count,
                'avg_mastery': round(avg_mastery, 2),
                'diagnosis_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                'model_used': diagnosis_model.name,
                'model_id': model_id
            },
            'diagnosis_data': diagnosis_data
        }

        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'JSON解析错误'}, status=400)
    except Subject.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '科目不存在'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': f'诊断分析失败: {str(e)}'}, status=500)


# 添加 CMD_survey 到路径
CMD_SURVEY_PATH = os.path.join(os.path.dirname(__file__), 'CMD_survey')
if CMD_SURVEY_PATH not in sys.path:
    sys.path.insert(0, os.path.dirname(CMD_SURVEY_PATH))

# """同步执行模型训练（会阻塞直到训练完成）"""
def run_training(subject_id, model_name):

    try:
        # 设置环境变量
        os.environ['CD_DATASET'] = str(subject_id)

        from main import model_functions

        # 模型名称需要与 main.py 中的键匹配（大写）
        # 数据库存储的是 "IRT"、"NCDM" 等，直接使用
        if model_name in model_functions:
            print(f"开始训练 {model_name} 模型...")
            model_functions[model_name]()
        else:
            print(f"未知模型: {model_name}")
            print(f"可用模型: {list(model_functions.keys())}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"训练失败: {str(e)}")

@login_required
@user_passes_test(is_teacher)
def get_diagnosis_result(request, diagnosis_id):
    """获取特定诊断结果详情（现在通过学生和科目获取）"""
    try:
        # 由于移除了DiagnosisResult，我们通过学生和科目获取最新的诊断
        return JsonResponse({
            'status': 'success',
            'message': '请使用学生诊断详情接口',
            'diagnosis': {}
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
def get_student_diagnosis_detail(request, student_id, subject_id):
    """获取学生详细诊断数据和历史"""
    try:
        student = get_object_or_404(User, id=student_id, user_type='student')
        subject = get_object_or_404(Subject, id=subject_id)

        # 获取模型ID参数（可选）
        model_id = request.GET.get('model_id')

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

        # 获取该学生该科目的所有诊断结果（基于知识点）
        student_diagnoses = StudentDiagnosis.objects.filter(
            student=student,
            knowledge_point__subject=subject
        ).select_related('knowledge_point', 'diagnosis_model').order_by('-last_practiced')

        # 如果指定了模型ID，只获取该模型的诊断结果
        if model_id:
            student_diagnoses_filtered = student_diagnoses.filter(diagnosis_model_id=model_id)
        else:
            # 没有指定模型ID，获取最新的诊断模型
            latest_diagnosis = student_diagnoses.first()
            if latest_diagnosis:
                student_diagnoses_filtered = student_diagnoses.filter(
                    diagnosis_model=latest_diagnosis.diagnosis_model
                )
            else:
                student_diagnoses_filtered = student_diagnoses.none()

        # 获取知识点详细信息
        knowledge_points = KnowledgePoint.objects.filter(
            subject=subject
        ).order_by('id')

        # 构建知识点掌握度数据
        knowledge_data = []
        for kp in knowledge_points:
            # 使用filter().first()代替get()，避免多条记录错误
            diagnosis = student_diagnoses_filtered.filter(knowledge_point=kp).first()
            
            if diagnosis:
                mastery = diagnosis.mastery_level
                practice_count = diagnosis.practice_count
                correct_count = diagnosis.correct_count
            else:
                mastery = 0
                practice_count = 0
                correct_count = 0

            correct_rate = round((correct_count / practice_count * 100), 2) if practice_count > 0 else 0

            knowledge_data.append({
                'id': kp.id,
                'name': kp.name,
                'mastery': round(mastery * 100, 2),
                'status': '优秀' if mastery >= 0.8 else '良好' if mastery >= 0.6 else '需加强',
                'practice_count': practice_count,
                'correct_rate': correct_rate
            })

        # 计算总体掌握度
        overall_score = 0
        if knowledge_data:
            overall_score = round(sum([kp['mastery'] for kp in knowledge_data]) / len(knowledge_data), 2)

        # 获取学生答题统计
        answer_stats = AnswerLog.objects.filter(
            student=student,
            exercise__subject=subject,
            is_correct__isnull=False
        ).aggregate(
            total_answers=Count('id'),
            correct_answers=Count('id', filter=DjangoQ(is_correct=True)),
            avg_time=Avg('time_spent')
        )

        if answer_stats['total_answers'] and answer_stats['total_answers'] > 0:
            correct_rate = round((answer_stats['correct_answers'] / answer_stats['total_answers']) * 100, 2)
        else:
            correct_rate = 0

        # 获取当前使用的诊断模型名称
        current_model = student_diagnoses_filtered.first()
        model_name = current_model.diagnosis_model.name if current_model else '暂无'

        result = {
            'status': 'success',
            'student': {
                'id': student.id,
                'username': student.username,
                'first_name': student.first_name or '',
                'last_name': student.last_name or '',
                'full_name': f"{student.first_name or ''}{student.last_name or ''}" or student.username,
                'email': student.email if hasattr(student, 'email') else '',
                'total_answers': answer_stats['total_answers'] or 0,
                'correct_rate': correct_rate,
                'avg_time': round(answer_stats['avg_time'] or 0, 2)
            },
            'subject_name': subject.name,
            'overall_score': overall_score,
            'model_used': model_name,
            'knowledge_data': knowledge_data,
            'weak_points': [kp for kp in knowledge_data if kp['mastery'] < 60],
            'strong_points': [kp for kp in knowledge_data if kp['mastery'] >= 80],
            'diagnosis_history': [
                {
                    'knowledge_point': diagnosis.knowledge_point.name,
                    'mastery_level': round(diagnosis.mastery_level * 100, 2),
                    'model_name': diagnosis.diagnosis_model.name,
                    'practice_count': diagnosis.practice_count,
                    'correct_count': diagnosis.correct_count,
                    'last_practiced': diagnosis.last_practiced.strftime('%Y-%m-%d %H:%M')
                }
                for diagnosis in student_diagnoses[:10]  # 显示最近10条（所有模型）
            ]
        }

        return JsonResponse(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@csrf_exempt
def get_diagnosis_summary(request, subject_id):
    """获取科目诊断摘要"""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': '仅支持GET请求'}, status=405)

    try:
        teacher = request.user
        
        # 检查科目是否存在
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return JsonResponse({'success': False, 'error': f'科目ID {subject_id} 不存在'}, status=404)

        # 验证权限
        if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
            return JsonResponse({'success': False, 'error': '无权限访问该科目'}, status=403)

        # 从做题记录中获取该科目所有有答题记录的学生
        student_ids_with_logs = AnswerLog.objects.filter(
            exercise__subject=subject,
            is_correct__isnull=False
        ).values_list('student_id', flat=True).distinct()
        
        students_with_logs = User.objects.filter(
            id__in=student_ids_with_logs,
            user_type='student'
        )
        
        # 获取该科目的选课学生总数
        enrolled_students_count = StudentSubject.objects.filter(subject=subject).count()

        # 获取该科目的知识点
        knowledge_points = KnowledgePoint.objects.filter(subject=subject)
        total_kp_count = knowledge_points.count()
        
        # 获取学生做题覆盖的知识点（通过Q矩阵和答题记录）
        covered_kp_ids = QMatrix.objects.filter(
            exercise__in=AnswerLog.objects.filter(
                exercise__subject=subject,
                is_correct__isnull=False
            ).values_list('exercise_id', flat=True).distinct()
        ).values_list('knowledge_point_id', flat=True).distinct()
        covered_kp_count = len(set(covered_kp_ids))

        # 获取诊断数据
        student_diagnoses = StudentDiagnosis.objects.filter(
            knowledge_point__subject=subject
        ).select_related('student', 'knowledge_point', 'diagnosis_model')

        # 计算统计信息
        student_count = students_with_logs.count()
        diagnosed_student_ids = student_diagnoses.values('student').distinct()
        diagnosed_students = diagnosed_student_ids.count()

        # 计算每个学生的总体掌握度
        student_scores = []
        for student in students_with_logs:
            student_kps = student_diagnoses.filter(student=student)

            if student_kps.exists():
                avg_mastery = student_kps.aggregate(
                    avg_mastery=Avg('mastery_level')
                )['avg_mastery'] or 0
                student_scores.append(avg_mastery * 100)  # 转换为百分比

        avg_score = round(sum(student_scores) / len(student_scores), 2) if student_scores else 0

        # 计算知识点统计
        kp_stats = []
        for kp in knowledge_points:
            kp_diagnoses = student_diagnoses.filter(knowledge_point=kp)
            if kp_diagnoses.exists():
                avg_mastery = kp_diagnoses.aggregate(
                    avg_mastery=Avg('mastery_level')
                )['avg_mastery'] or 0
                avg_mastery_pct = round(avg_mastery * 100, 2)
            else:
                avg_mastery_pct = 0

            kp_stats.append({
                'id': kp.id,
                'name': kp.name,
                'avg_mastery': avg_mastery_pct,
                'status': '优秀' if avg_mastery_pct >= 80 else '良好' if avg_mastery_pct >= 60 else '需加强',
                'diagnosed_students': kp_diagnoses.values('student').distinct().count(),
                'total_students': student_count
            })

        # 获取最近诊断时间
        last_diagnosis = student_diagnoses.order_by('-last_practiced').first()
        last_diagnosis_time = last_diagnosis.last_practiced.strftime('%Y-%m-%d %H:%M') if last_diagnosis else '暂无'

        # 找出薄弱和优势知识点
        weak_knowledge_points = [kp for kp in kp_stats if kp['avg_mastery'] < 60]
        strong_knowledge_points = [kp for kp in kp_stats if kp['avg_mastery'] >= 80]

        summary = {
            'subject_id': subject.id,
            'subject_name': subject.name,
            'student_count': student_count,  # 有做题记录的学生数
            'enrolled_students_count': enrolled_students_count,  # 选课学生总数
            'diagnosed_count': diagnosed_students,
            'diagnosis_rate': round((diagnosed_students / student_count * 100), 2) if student_count > 0 else 0,
            'avg_overall_score': avg_score,
            'knowledge_points': kp_stats,
            'total_kp_count': total_kp_count,  # 知识点总数
            'covered_kp_count': covered_kp_count,  # 学生做题覆盖的知识点数
            'weak_knowledge_points': weak_knowledge_points,
            'strong_knowledge_points': strong_knowledge_points,
            'last_diagnosis_time': last_diagnosis_time
        }

        return JsonResponse({
            'success': True,
            'summary': summary
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)