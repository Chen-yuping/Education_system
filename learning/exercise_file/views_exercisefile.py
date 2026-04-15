from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone

# 🎯 引入咱们无敌的智能管家函数
from learning.utils_ai import smart_handle_upload

# 引入模型
from learning.models import Subject, ExerciseFile
# 引入表单
from .forms import ExerciseFileForm


# 登录用户判断
def is_teacher(user):
    return user.user_type == 'teacher'


# 删除功能 (配合前端的删除按钮)
@login_required
@user_passes_test(is_teacher)
def delete_exercise_file(request, file_id):
    file_obj = get_object_or_404(ExerciseFile, id=file_id)
    # 只能删除自己的文件
    if file_obj.teacher == request.user:
        file_obj.delete()
        messages.success(request, "记录及文件已删除")
    return redirect(request.META.get('HTTP_REFERER', '/'))


# 上传习题主视图
@login_required
@user_passes_test(is_teacher)
def upload_exercise(request):
    subjects = Subject.objects.all()

    # 1. 获取 subject_id 参数 (优先从POST获取，其次GET)
    subject_id = request.POST.get('subject_id') or request.GET.get('subject_id')
    subject = None

    if subject_id:
        subject = get_object_or_404(Subject, id=subject_id)
    else:
        # 容错：如果没传ID，默认取第一个科目，防止报错
        subject = subjects.first()

    if request.method == 'POST':
        form = ExerciseFileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # --- A. 保存文件记录 ---
                exercise_file = form.save(commit=False)
                exercise_file.teacher = request.user
                exercise_file.subject = subject  # 必填：关联当前科目
                exercise_file.original_filename = request.FILES['file'].name

                # 自动识别文件类型 (增加 txt 支持)
                ext = exercise_file.original_filename.split('.')[-1].lower()
                if 'xls' in ext:
                    exercise_file.file_type = 'xlsx'
                elif 'doc' in ext:
                    exercise_file.file_type = 'docx'
                elif 'pdf' in ext:
                    exercise_file.file_type = 'pdf'
                elif 'txt' in ext:
                    exercise_file.file_type = 'txt'
                else:
                    exercise_file.file_type = 'txt'

                exercise_file.status = 'processing'
                exercise_file.save()  # 这一步执行后，文件保存到磁盘

                # --- B. 🎯 核心逻辑升级：调用智能管家分发任务 ---

                # 获取网页下拉框传来的模式（如果没有选，默认走 'direct' 传统模式保底）
                upload_mode = request.POST.get('upload_mode', 'direct')

                # 一行代码代替原来的 if/else 判断！智能管家会帮我们处理一切！
                count = smart_handle_upload(exercise_file, mode=upload_mode)

                # --- C. 更新处理结果 ---
                exercise_file.status = 'completed' if count > 0 else 'error'
                exercise_file.exercise_count = count
                exercise_file.processed_at = timezone.now()
                exercise_file.save()

                if count > 0:
                    if upload_mode == 'ai':
                        messages.success(request, f'✨ AI 发力成功！根据资料为您智能生成了 {count} 道习题。')
                    else:
                        messages.success(request, f'✅ 提取成功！共导入 {count} 道习题。')
                else:
                    messages.warning(request, '文件上传成功，但未解析出有效习题，请检查格式或资料内容。')

            except Exception as e:
                # 异常处理：更新状态为失败
                if 'exercise_file' in locals():
                    exercise_file.status = 'error'
                    exercise_file.error_message = str(e)
                    exercise_file.save()
                messages.error(request, f'处理失败: {str(e)}')

            # 刷新页面 (带上 subject_id 以保持当前科目选中状态)
            return redirect(f'{request.path}?subject_id={subject.id}')

    else:
        form = ExerciseFileForm()

    # 获取上传历史 (仅显示当前科目，按时间倒序)
    if subject:
        upload_history = ExerciseFile.objects.filter(subject=subject).order_by('-uploaded_at')
    else:
        upload_history = []

    return render(request, 'teacher/upload_exercise.html', {
        'form': form,
        'subjects': subjects,
        'upload_history': upload_history,
        'subject': subject,
        # 兼容模板变量名
        'course': subject
    })