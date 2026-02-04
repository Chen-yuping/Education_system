from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from ..models import *
from .forms import ExerciseFileForm

#登录用户判断
def is_teacher(user):
    return user.user_type == 'teacher'



#上传习题
@login_required
@user_passes_test(is_teacher)
def upload_exercise(request):
    subjects = Subject.objects.all()
    
    # 获取subject_id参数
    subject_id = request.GET.get('subject_id')
    subject = None
    if subject_id:
        subject = get_object_or_404(Subject, id=subject_id)
    
    if request.method == 'POST':
        form = ExerciseFileForm(request.POST, request.FILES)
        if form.is_valid():
            exercise_file = form.save(commit=False)
            exercise_file.teacher = request.user
            exercise_file.original_filename = request.FILES['file'].name
            exercise_file.file_type = request.FILES['file'].name.split('.')[-1].lower()
            exercise_file.save()

            messages.success(request, '习题上传成功！')
            return redirect('exercise_file_list')
    else:
        form = ExerciseFileForm()
        # 添加上传历史
        upload_history = ExerciseFile.objects.filter(teacher=request.user).order_by('-uploaded_at')[:10]

    return render(request, 'teacher/upload_exercise.html', {
        'form': form,
        'subjects': subjects,
        'upload_history': upload_history,
        'subject': subject,
    })
