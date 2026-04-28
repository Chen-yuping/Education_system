from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse

from learning.utils_ai import smart_handle_upload, quick_build_course_from_textbook

# 引入模型
from learning.models import Subject, ExerciseFile, ResourceFile, TextbookCourseBuilder, KnowledgePoint, Exercise
# 引入表单
from .forms import ExerciseFileForm, ResourceFileForm, TextbookCourseBuilderForm


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


# 上传教学资料视图
@login_required
@user_passes_test(is_teacher)
def upload_resource(request):
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
        form = ResourceFileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # --- A. 保存资料记录 ---
                resource_file = form.save(commit=False)
                resource_file.teacher = request.user
                resource_file.subject = subject  # 必填：关联当前科目
                resource_file.original_filename = request.FILES['file'].name

                # 自动识别文件类型
                ext = resource_file.original_filename.split('.')[-1].lower()
                if ext in ['docx', 'doc']:
                    resource_file.file_type = 'docx'
                elif ext in ['xlsx', 'xls']:
                    resource_file.file_type = 'xlsx'
                elif ext in ['pptx', 'ppt']:
                    resource_file.file_type = 'pptx'
                elif ext == 'pdf':
                    resource_file.file_type = 'pdf'
                elif ext == 'txt':
                    resource_file.file_type = 'txt'
                elif ext in ['jpg', 'jpeg']:
                    resource_file.file_type = 'jpg'
                elif ext == 'png':
                    resource_file.file_type = 'png'
                elif ext == 'gif':
                    resource_file.file_type = 'gif'
                elif ext == 'mp4':
                    resource_file.file_type = 'mp4'
                elif ext == 'mp3':
                    resource_file.file_type = 'mp3'
                elif ext == 'wav':
                    resource_file.file_type = 'wav'
                else:
                    resource_file.file_type = '其他'

                resource_file.status = 'completed'  # 资料上传直接标记为完成
                resource_file.processed_at = timezone.now()
                resource_file.save()  # 这一步执行后，文件保存到磁盘

                messages.success(request, f'✅ 资料上传成功！标题：{resource_file.title}')

            except Exception as e:
                # 异常处理
                messages.error(request, f'上传失败: {str(e)}')

            # 刷新页面 (带上 subject_id 以保持当前科目选中状态)
            return redirect(f'{request.path}?subject_id={subject.id}')

    else:
        form = ResourceFileForm()

    # 获取上传历史 (仅显示当前科目，按时间倒序)
    if subject:
        upload_history = ResourceFile.objects.filter(subject=subject).order_by('-uploaded_at')
    else:
        upload_history = []

    return render(request, 'teacher/upload_resource.html', {
        'form': form,
        'subjects': subjects,
        'upload_history': upload_history,
        'subject': subject,
        # 兼容模板变量名
        'course': subject
    })


# 删除教学资料功能
@login_required
@user_passes_test(is_teacher)
def delete_resource_file(request, file_id):
    resource_file = get_object_or_404(ResourceFile, id=file_id)
    # 只能删除自己的文件
    if resource_file.teacher == request.user:
        resource_file.delete()
        messages.success(request, "教学资料已删除")
    return redirect(request.META.get('HTTP_REFERER', '/'))


# 快速构建课程视图
@login_required
@user_passes_test(is_teacher)
def quick_build_course(request):
    """快速构建课程页面"""
    if request.method == 'POST':
        form = TextbookCourseBuilderForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # 保存课本记录
                textbook_builder = form.save(commit=False)
                textbook_builder.teacher = request.user
                textbook_builder.original_filename = request.FILES['textbook_file'].name
                textbook_builder.save()
                
                # 异步处理PDF（这里简化处理，实际应该用Celery等异步任务）
                # 这里我们先同步处理，实际项目中应该使用异步任务队列
                from learning.utils_ai import quick_build_course_from_textbook
                result = quick_build_course_from_textbook(textbook_builder)
                
                if result.get('success'):
                    # 更新状态为待审核
                    textbook_builder.status = 'review_pending'
                    textbook_builder.save()
                    
                    # 创建审核记录
                    create_review_records(textbook_builder)
                    
                    messages.success(request, f'✅ 课程初步构建完成！已生成{result.get("exercises", 0)}道习题，{result.get("knowledge_points", 0)}个知识点。请开始审核。')
                    return redirect('course_review_dashboard', builder_id=textbook_builder.id)
                else:
                    messages.error(request, f'课程构建失败: {result.get("error", "未知错误")}')
                    
            except Exception as e:
                messages.error(request, f'上传失败: {str(e)}')
    else:
        form = TextbookCourseBuilderForm()
    
    # 获取构建历史
    build_history = TextbookCourseBuilder.objects.filter(teacher=request.user).order_by('-uploaded_at')[:10]
    
    return render(request, 'teacher/quick_build_course.html', {
        'form': form,
        'build_history': build_history
    })


@login_required
@user_passes_test(is_teacher)
def course_build_result(request, builder_id):
    """课程构建结果页面"""
    textbook_builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 获取生成的课程信息
    subject = textbook_builder.generated_subject
    knowledge_points = []
    exercises = []
    
    if subject:
        knowledge_points = KnowledgePoint.objects.filter(subject=subject)[:20]
        exercises = Exercise.objects.filter(subject=subject)[:10]
    
    return render(request, 'teacher/course_build_result.html', {
        'builder': textbook_builder,
        'subject': subject,
        'knowledge_points': knowledge_points,
        'exercises': exercises
    })

def create_review_records(builder):
    """为课本构建创建审核记录"""
    from learning.models import TextbookReviewExercise, TextbookReviewKnowledgePoint, TextbookReviewRelationship, KnowledgeGraph
    
    # 创建习题审核记录
    if builder.generated_subject:
        exercises = builder.generated_subject.exercise_set.all()
        for exercise in exercises:
            TextbookReviewExercise.objects.create(
                builder=builder,
                exercise=exercise,
                original_content=exercise.content
            )
    
    # 创建知识点审核记录
    if builder.generated_subject:
        knowledge_points = builder.generated_subject.knowledgepoint_set.all()
        for kp in knowledge_points:
            TextbookReviewKnowledgePoint.objects.create(
                builder=builder,
                knowledge_point=kp,
                original_name=kp.name,
                original_description=kp.description or ''
            )
    
    # 创建关系审核记录
    if builder.generated_subject:
        # 获取知识图谱关系
        relationships = KnowledgeGraph.objects.filter(subject=builder.generated_subject)
        for relationship in relationships:
            TextbookReviewRelationship.objects.create(
                builder=builder,
                from_knowledge_point=relationship.source,
                to_knowledge_point=relationship.target,
                relationship_type='相关'  # 默认关系类型
            )


# 课程审核仪表板
@login_required
@user_passes_test(is_teacher)
def course_review_dashboard(request, builder_id):
    """课程审核仪表板"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 获取审核统计
    from learning.models import TextbookReviewExercise, TextbookReviewKnowledgePoint, TextbookReviewRelationship
    
    exercise_reviews = TextbookReviewExercise.objects.filter(builder=builder)
    knowledge_reviews = TextbookReviewKnowledgePoint.objects.filter(builder=builder)
    relationship_reviews = TextbookReviewRelationship.objects.filter(builder=builder)
    
    stats = {
        'total_exercises': exercise_reviews.count(),
        'reviewed_exercises': exercise_reviews.filter(reviewed_at__isnull=False).count(),
        'approved_exercises': exercise_reviews.filter(is_approved=True).count(),
        'total_knowledge_points': knowledge_reviews.count(),
        'reviewed_knowledge_points': knowledge_reviews.filter(reviewed_at__isnull=False).count(),
        'approved_knowledge_points': knowledge_reviews.filter(is_approved=True).count(),
        'total_relationships': relationship_reviews.count(),
        'reviewed_relationships': relationship_reviews.filter(reviewed_at__isnull=False).count(),
        'approved_relationships': relationship_reviews.filter(is_approved=True).count(),
    }
    
    return render(request, 'teacher/course_review_dashboard.html', {
        'builder': builder,
        'stats': stats
    })


# 习题审核页面
@login_required
@user_passes_test(is_teacher)
def review_exercises(request, builder_id):
    """审核习题页面"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 更新状态
    if builder.status != 'reviewing_exercises':
        builder.status = 'reviewing_exercises'
        builder.save()
    
    # 获取待审核的习题（一次10个）
    from learning.models import TextbookReviewExercise
    unreviewed_exercises = TextbookReviewExercise.objects.filter(
        builder=builder,
        reviewed_at__isnull=True
    ).order_by('id')[:10]
    
    return render(request, 'teacher/review_exercises.html', {
        'builder': builder,
        'exercises': unreviewed_exercises
    })


# 知识点审核页面
@login_required
@user_passes_test(is_teacher)
def review_knowledge_points(request, builder_id):
    """审核知识点页面"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 更新状态
    if builder.status != 'reviewing_knowledge':
        builder.status = 'reviewing_knowledge'
        builder.save()
    
    # 获取待审核的知识点（一次10个）
    from learning.models import TextbookReviewKnowledgePoint
    unreviewed_knowledge = TextbookReviewKnowledgePoint.objects.filter(
        builder=builder,
        reviewed_at__isnull=True
    ).order_by('id')[:10]
    
    return render(request, 'teacher/review_knowledge_points.html', {
        'builder': builder,
        'knowledge_points': unreviewed_knowledge
    })


# 知识图谱关系审核页面
@login_required
@user_passes_test(is_teacher)
def review_relationships(request, builder_id):
    """审核知识图谱关系页面"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 更新状态
    if builder.status != 'reviewing_graph':
        builder.status = 'reviewing_graph'
        builder.save()
    
    # 获取待审核的关系（一次10个）
    from learning.models import TextbookReviewRelationship
    unreviewed_relationships = TextbookReviewRelationship.objects.filter(
        builder=builder,
        reviewed_at__isnull=True
    ).order_by('id')[:10]
    
    return render(request, 'teacher/review_relationships.html', {
        'builder': builder,
        'relationships': unreviewed_relationships
    })


# 提交审核结果
@login_required
@user_passes_test(is_teacher)
def submit_review(request, builder_id, review_type):
    """提交审核结果"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    if request.method == 'POST':
        if review_type == 'exercise':
            # 处理习题审核
            exercise_id = request.POST.get('exercise_id')
            is_approved = request.POST.get('is_approved') == 'true'
            reviewed_content = request.POST.get('reviewed_content', '')
            review_notes = request.POST.get('review_notes', '')
            
            from learning.models import TextbookReviewExercise
            review = TextbookReviewExercise.objects.get(
                builder=builder,
                exercise_id=exercise_id
            )
            
            review.is_approved = is_approved
            review.reviewed_content = reviewed_content
            review.review_notes = review_notes
            review.reviewed_at = timezone.now()
            review.is_modified = reviewed_content != review.original_content
            review.save()
            
            # 更新习题内容（如果修改了）
            if reviewed_content and reviewed_content != review.exercise.content:
                review.exercise.content = reviewed_content
                review.exercise.save()
            
            # 更新审核统计
            builder.exercises_reviewed = TextbookReviewExercise.objects.filter(
                builder=builder,
                reviewed_at__isnull=False
            ).count()
            builder.exercises_approved = TextbookReviewExercise.objects.filter(
                builder=builder,
                is_approved=True
            ).count()
            builder.save()
            
            return JsonResponse({'success': True})
            
        elif review_type == 'knowledge':
            # 处理知识点审核
            knowledge_id = request.POST.get('knowledge_id')
            is_approved = request.POST.get('is_approved') == 'true'
            reviewed_name = request.POST.get('reviewed_name', '')
            reviewed_description = request.POST.get('reviewed_description', '')
            review_notes = request.POST.get('review_notes', '')
            
            from learning.models import TextbookReviewKnowledgePoint
            review = TextbookReviewKnowledgePoint.objects.get(
                builder=builder,
                knowledge_point_id=knowledge_id
            )
            
            review.is_approved = is_approved
            review.reviewed_name = reviewed_name
            review.reviewed_description = reviewed_description
            review.review_notes = review_notes
            review.reviewed_at = timezone.now()
            review.is_modified = (reviewed_name != review.original_name or 
                                 reviewed_description != review.original_description)
            review.save()
            
            # 更新知识点内容（如果修改了）
            if reviewed_name and reviewed_name != review.knowledge_point.name:
                review.knowledge_point.name = reviewed_name
                review.knowledge_point.save()
            if reviewed_description and reviewed_description != review.knowledge_point.description:
                review.knowledge_point.description = reviewed_description
                review.knowledge_point.save()
            
            # 更新审核统计
            builder.knowledge_points_reviewed = TextbookReviewKnowledgePoint.objects.filter(
                builder=builder,
                reviewed_at__isnull=False
            ).count()
            builder.knowledge_points_approved = TextbookReviewKnowledgePoint.objects.filter(
                builder=builder,
                is_approved=True
            ).count()
            builder.save()
            
            return JsonResponse({'success': True})
            
        elif review_type == 'relationship':
            # 处理关系审核
            relationship_id = request.POST.get('relationship_id')
            is_approved = request.POST.get('is_approved') == 'true'
            is_rejected = request.POST.get('is_rejected') == 'true'
            review_notes = request.POST.get('review_notes', '')
            
            from learning.models import TextbookReviewRelationship
            review = TextbookReviewRelationship.objects.get(
                builder=builder,
                id=relationship_id
            )
            
            review.is_approved = is_approved
            review.is_rejected = is_rejected
            review.review_notes = review_notes
            review.reviewed_at = timezone.now()
            review.save()
            
            # 更新审核统计
            builder.relationships_reviewed = TextbookReviewRelationship.objects.filter(
                builder=builder,
                reviewed_at__isnull=False
            ).count()
            builder.relationships_approved = TextbookReviewRelationship.objects.filter(
                builder=builder,
                is_approved=True
            ).count()
            builder.save()
            
            return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


# 完成审核并提交课程
@login_required
@user_passes_test(is_teacher)
def complete_review(request, builder_id):
    """完成审核并提交课程"""
    builder = get_object_or_404(TextbookCourseBuilder, id=builder_id, teacher=request.user)
    
    # 检查是否所有内容都已审核
    from learning.models import TextbookReviewExercise, TextbookReviewKnowledgePoint, TextbookReviewRelationship
    
    total_exercises = TextbookReviewExercise.objects.filter(builder=builder).count()
    reviewed_exercises = TextbookReviewExercise.objects.filter(builder=builder, reviewed_at__isnull=False).count()
    
    total_knowledge = TextbookReviewKnowledgePoint.objects.filter(builder=builder).count()
    reviewed_knowledge = TextbookReviewKnowledgePoint.objects.filter(builder=builder, reviewed_at__isnull=False).count()
    
    total_relationships = TextbookReviewRelationship.objects.filter(builder=builder).count()
    reviewed_relationships = TextbookReviewRelationship.objects.filter(builder=builder, reviewed_at__isnull=False).count()
    
    # 如果还有未审核的内容，提示用户
    if reviewed_exercises < total_exercises or reviewed_knowledge < total_knowledge or reviewed_relationships < total_relationships:
        messages.warning(request, '还有未审核的内容，请完成所有审核后再提交。')
        return redirect('course_review_dashboard', builder_id=builder_id)
    
    # 更新状态为已完成
    builder.status = 'completed'
    builder.review_completed_at = timezone.now()
    builder.save()
    
    messages.success(request, '✅ 课程审核完成！课程已正式提交到系统。')
    return redirect('course_build_result', builder_id=builder_id)