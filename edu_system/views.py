#我修改了
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from learning.models import Subject
from learning.models import Subject, Exercise

def home(request):
    """学堂在线风格主页"""
    # 获取热门科目和课程
    popular_subjects = Subject.objects.all()[:6]
    featured_exercises = Exercise.objects.filter()[:4]

    context = {
        'popular_subjects': popular_subjects,
        'featured_exercises': featured_exercises,
    }
    return render(request, 'home.html', context)

def csrf_failure(request, reason=""):
    """自定义 CSRF 验证失败页面"""
    return render(request, 'csrf_error.html', {'reason': reason}, status=403)