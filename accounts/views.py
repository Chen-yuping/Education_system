from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from .forms import UserRegistrationForm
from .models import StudentProfile, TeacherProfile
from .forms import UserLoginForm
from django.contrib import messages
from django.http import JsonResponse
import re
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
def user_login(request):
    """用户登录视图 - 验证账号、密码和身份"""
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)

        if form.is_valid():
            # 从表单中获取已验证的用户对象
            user = form.cleaned_data.get('user')

            if user is not None:
                # 登录用户
                login(request, user)
                messages.success(request, f'欢迎回来，{user.username}！')

                # 根据用户类型重定向
                if user.user_type == 'teacher':
                    return redirect('teacher_dashboard')
                elif    user.user_type == 'student':
                    return redirect('student_dashboard')
                else:
                    return redirect('researcher_dashboard')
        else:
            # 显示表单错误
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {'form': form})

def user_logout(request):
    """用户登出视图"""
    logout(request)
    return redirect('home')

def register(request):
    """用户注册视图"""
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            try:
                # 创建用户对象但不立即保存
                user = form.save(commit=False)
                user.email = form.cleaned_data['email']
                user.user_type = form.cleaned_data['user_type']
                user.is_active = True  # 默认激活用户
                user.save()

                # 创建用户档案
                if user.user_type == 'student':
                    StudentProfile.objects.create(
                        user=user,
                        grade=form.cleaned_data.get('grade', ''),
                        school=form.cleaned_data.get('school', '')
                    )
                    messages.success(request, '🎉 学生账号注册成功！欢迎加入学习平台。')
                else:
                    TeacherProfile.objects.create(
                        user=user,
                        subject=form.cleaned_data.get('subject', ''),
                        school=form.cleaned_data.get('school', '')
                    )
                    messages.success(request, '🎉 教师账号注册成功！开始管理您的教学内容。')

                # 自动登录
                login(request, user)

                # 根据用户类型重定向
                if user.user_type == 'teacher':
                    return redirect('teacher_dashboard')
                else:
                    return redirect('student_dashboard')

            except Exception as e:
                messages.error(request, f'注册过程中出现错误：{str(e)}')
        else:
            # 显示表单错误
            messages.error(request, '请修正以下错误：')
    else:
        # 从URL参数中获取用户类型
        initial_data = {}
        user_type = request.GET.get('type')
        if user_type in ['student', 'teacher']:
            initial_data['user_type'] = user_type

        form = UserRegistrationForm(initial=initial_data)

    return render(request, 'accounts/register.html', {'form': form})