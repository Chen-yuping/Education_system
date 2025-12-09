from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from ..models import *
from learning.models import DiagnosisModel

def knowledge_mastery_diagnoses(user, answerlog):

    return


def is_student(user):
    return user.user_type == 'student'
# 获取学生的知识点掌握情况，学习诊断页面
@login_required
@user_passes_test(is_student)
def student_diagnosis(request):
    try:
        # 获取所有可用模型
        available_models = DiagnosisModel.objects.filter(is_active=True)

        # 获取选择的模型ID
        selected_model = None
        model_id = request.GET.get('model_id')

        if available_models.exists():
            if model_id:
                try:
                    selected_model = DiagnosisModel.objects.get(id=model_id, is_active=True)
                except DiagnosisModel.DoesNotExist:
                    selected_model = available_models.first()
            else:
                selected_model = available_models.first()

        context = {
            'available_models': available_models,
            'selected_model': selected_model,
        }

    except Exception as e:
        # 处理异常
        context = {
            'available_models': [],
            'selected_model': None,
        }

    return render(request, 'student/student_diagnosis.html', context)