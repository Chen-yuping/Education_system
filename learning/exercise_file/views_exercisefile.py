from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings

from learning.utils_ai import smart_handle_upload, quick_build_course_from_textbook
from learning.knowledge_graph_builder.text_extractor import extract_text_from_file
from learning.knowledge_graph_builder.pipeline import KnowledgeGraphPipeline

# 引入模型
from learning.models import Subject, ExerciseFile, ResourceFile, TextbookCourseBuilder, KnowledgePoint, Exercise, ResourceKnowledgeExtraction, ResourceReviewKnowledgePoint, ResourceReviewRelationship, KnowledgeGraph
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

                resource_file.save()  # 这一步执行后，文件保存到磁盘

                # --- 根据资料类型分流处理 ---
                extraction = None

                if resource_file.resource_type == '习题':
                    # === 习题上传处理流程 ===
                    resource_file.status = 'processing'
                    resource_file.save(update_fields=['status'])

                    upload_mode = request.POST.get('upload_mode', 'direct')

                    try:
                        count = smart_handle_upload(resource_file, mode=upload_mode)
                        resource_file.status = 'completed' if count > 0 else 'error'
                        resource_file.exercise_count = count
                        resource_file.processed_at = timezone.now()
                        resource_file.save(update_fields=['status', 'exercise_count', 'processed_at'])

                        if count > 0:
                            if upload_mode == 'ai':
                                messages.success(request, f'✨ AI 发力成功！根据资料为您智能生成了 {count} 道习题。')
                            else:
                                messages.success(request, f'✅ 提取成功！共导入 {count} 道习题。')
                        else:
                            messages.warning(request, '文件上传成功，但未解析出有效习题，请检查格式或资料内容。')
                    except Exception as e:
                        resource_file.status = 'error'
                        resource_file.error_message = str(e)
                        resource_file.processed_at = timezone.now()
                        resource_file.save(update_fields=['status', 'error_message', 'processed_at'])
                        messages.error(request, f'习题处理失败: {str(e)}')

                else:
                    # === 教学资料处理流程（文本提取 + 知识图谱） ===
                    text_extract_ok = False
                    try:
                        file_path = resource_file.file.path
                        extracted = extract_text_from_file(file_path, resource_file.file_type)
                        resource_file.extracted_text = extracted
                        resource_file.status = 'completed'
                        text_extract_ok = bool(extracted and extracted.strip())
                    except Exception as extract_err:
                        resource_file.extracted_text = ''
                        resource_file.status = 'completed'
                        resource_file.error_message = f'文本提取失败: {extract_err}'
                        print(f"[WARN] 文本提取失败: {extract_err}")

                    resource_file.processed_at = timezone.now()
                    resource_file.save(update_fields=['extracted_text', 'status', 'error_message', 'processed_at'])

                    # --- 教案/教材/课件 → 自动抽取知识三元组 ---
                    if resource_file.resource_type in ('教材', '教案', '课件'):
                        if not resource_file.extracted_text:
                            if not text_extract_ok:
                                messages.warning(request, f'⚠️ {resource_file.get_resource_type_display()}文本提取失败，无法进行知识点抽取。请检查文件内容是否为空或格式是否正确。')
                            else:
                                messages.info(request, f'ℹ️ {resource_file.get_resource_type_display()}文本内容为空，跳过知识抽取。')
                        else:
                            try:
                                pipeline = KnowledgeGraphPipeline()
                                pipeline_result = pipeline.run(
                                    text=resource_file.extracted_text,
                                    subject=subject,
                                    subject_name=subject.name,
                                    source=resource_file.resource_type,
                                    resource_file=resource_file
                                )
                                if pipeline_result.get("success"):
                                    kp_count = pipeline_result.get('kp_count', 0)
                                    rel_count = pipeline_result.get('rel_count', 0)
                                    if kp_count > 0 and rel_count > 0:
                                        print(f"[INFO] 知识图谱构建成功: {kp_count} 知识点, {rel_count} 关系")
                                        extraction = ResourceKnowledgeExtraction.objects.create(
                                            resource_file=resource_file,
                                            teacher=request.user,
                                            subject=subject,
                                            status='review_pending',
                                            kp_count=kp_count,
                                            rel_count=rel_count,
                                        )
                                        # 获取置信度映射
                                        kp_confidence = pipeline_result.get('kp_confidence', {})
                                        rel_confidence = pipeline_result.get('rel_confidence', {})

                                        auto_kp_count = 0
                                        pending_kp_count = 0
                                        for kp in pipeline_result.get('created_kps', []):
                                            conf = kp_confidence.get(kp.name, '高')
                                            is_high_conf = (conf == '高')
                                            ResourceReviewKnowledgePoint.objects.create(
                                                extraction=extraction,
                                                knowledge_point=kp,
                                                original_name=kp.name,
                                                confidence=conf,
                                                is_approved=is_high_conf,
                                                reviewed_at=timezone.now() if is_high_conf else None,
                                            )
                                            if is_high_conf:
                                                auto_kp_count += 1
                                            else:
                                                pending_kp_count += 1

                                        auto_rel_count = 0
                                        pending_rel_count = 0
                                        for rel in pipeline_result.get('created_rels', []):
                                            rkey = (rel.source.name, rel.target.name, rel.relationship_type)
                                            conf = rel_confidence.get(rkey, '高')
                                            is_high_conf = (conf == '高')
                                            ResourceReviewRelationship.objects.create(
                                                extraction=extraction,
                                                from_knowledge_point=rel.source,
                                                to_knowledge_point=rel.target,
                                                relationship_type=rel.relationship_type,
                                                confidence=conf,
                                                is_approved=is_high_conf,
                                                reviewed_at=timezone.now() if is_high_conf else None,
                                            )
                                            if is_high_conf:
                                                auto_rel_count += 1
                                            else:
                                                pending_rel_count += 1

                                        msg = f'✅ 知识图谱构建成功：{kp_count}个知识点，{rel_count}条关系。'
                                        if auto_kp_count > 0 or auto_rel_count > 0:
                                            msg += f' 已自动通过 {auto_kp_count} 个知识点、{auto_rel_count} 条关系。'
                                        if pending_kp_count > 0 or pending_rel_count > 0:
                                            msg += f' 还有 {pending_kp_count} 个知识点、{pending_rel_count} 条关系待人工审核。'
                                        else:
                                            msg += ' 所有提取结果均已自动通过审核。'
                                        messages.success(request, msg)
                                    else:
                                        messages.warning(request, '⚠️ 知识抽取完成但未提取到有效知识点和关系，请检查资料内容是否包含足够的专业知识点。')
                                else:
                                    err_msg = pipeline_result.get('error', '未知错误')
                                    print(f"[WARN] 知识图谱构建失败: {err_msg}")
                                    messages.warning(request, f'⚠️ 知识图谱构建失败：{err_msg}')
                            except Exception as kg_err:
                                import traceback
                                print(f"[WARN] 知识图谱构建异常: {kg_err}\n{traceback.format_exc()}")
                                messages.warning(request, f'⚠️ 知识图谱构建异常：{kg_err}')

                messages.success(request, f'✅ 资料上传成功！标题：{resource_file.title}')

                # 如果有知识提取审核，跳转到审核页面
                if extraction:
                    return redirect('resource_extraction_review', extraction_id=extraction.id)

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

    # 构建资源文件 → 审核记录ID的映射（含审核状态显示文字）
    resource_ids = [r.id for r in upload_history]
    extraction_map = {}
    if resource_ids:
        extractions = ResourceKnowledgeExtraction.objects.filter(
            resource_file_id__in=resource_ids
        ).values('resource_file_id', 'id', 'status')
        for ext in extractions:
            extraction_map[ext['resource_file_id']] = ext['id']

    # 为upload_history中每个资源文件注入extraction_id属性
    for resource in upload_history:
        resource.extraction_id = extraction_map.get(resource.id, 0)

    return render(request, 'teacher/upload_resource.html', {
        'form': form,
        'subjects': subjects,
        'upload_history': upload_history,
        'extraction_map': extraction_map,
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

                # 确保上传目录存在（解决Windows [Errno 22]问题）
                import os
                upload_dir = os.path.join(settings.MEDIA_ROOT, 'textbooks', str(request.user.id))
                os.makedirs(upload_dir, exist_ok=True)

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
                    return redirect(request.path)

            except Exception as e:
                messages.error(request, f'上传失败: {str(e)}')
                return redirect(request.path)
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
                original_description=''
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
                relationship_type=relationship.relationship_type
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
            if reviewed_description and reviewed_description != review.original_description:
                # KnowledgePoint model does not have a description field, skip saving to it
                pass
            
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


# ==================== 资源文件知识提取审核 ====================

@login_required
@user_passes_test(is_teacher)
def resource_extraction_review(request, extraction_id):
    """资源知识提取审核仪表板"""
    extraction = get_object_or_404(ResourceKnowledgeExtraction, id=extraction_id, teacher=request.user)

    kp_reviews = ResourceReviewKnowledgePoint.objects.filter(extraction=extraction)
    rel_reviews = ResourceReviewRelationship.objects.filter(extraction=extraction)

    auto_approved_kps = kp_reviews.filter(confidence='高').count()
    auto_approved_rels = rel_reviews.filter(confidence='高').count()

    stats = {
        'total_kps': kp_reviews.count(),
        'reviewed_kps': kp_reviews.filter(reviewed_at__isnull=False).count(),
        'approved_kps': kp_reviews.filter(is_approved=True).count(),
        'auto_approved_kps': auto_approved_kps,
        'pending_kps': kp_reviews.filter(confidence='低', reviewed_at__isnull=True).count(),
        'total_rels': rel_reviews.count(),
        'reviewed_rels': rel_reviews.filter(reviewed_at__isnull=False).count(),
        'approved_rels': rel_reviews.filter(is_approved=True).count(),
        'auto_approved_rels': auto_approved_rels,
        'pending_rels': rel_reviews.filter(confidence='低', reviewed_at__isnull=True).count(),
    }

    return render(request, 'teacher/resource_review_dashboard.html', {
        'extraction': extraction,
        'stats': stats,
    })


@login_required
@user_passes_test(is_teacher)
def resource_review_knowledge_points(request, extraction_id):
    """审核知识点"""
    extraction = get_object_or_404(ResourceKnowledgeExtraction, id=extraction_id, teacher=request.user)

    if extraction.status not in ('review_pending', 'reviewing_knowledge'):
        if extraction.status == 'reviewing_graph':
            messages.info(request, '知识点已审核完成，请继续审核知识图谱关系。')
            return redirect('resource_review_relationships', extraction_id=extraction_id)
        elif extraction.status == 'completed':
            messages.info(request, '该提取已完成审核。')
            return redirect('resource_extraction_review', extraction_id=extraction_id)

    if extraction.status != 'reviewing_knowledge':
        extraction.status = 'reviewing_knowledge'
        extraction.save()

    unreviewed = ResourceReviewKnowledgePoint.objects.filter(
        extraction=extraction,
        reviewed_at__isnull=True
    ).order_by('id')[:10]

    return render(request, 'teacher/resource_review_knowledge_points.html', {
        'extraction': extraction,
        'knowledge_points': unreviewed,
    })


@login_required
@user_passes_test(is_teacher)
def resource_review_relationships(request, extraction_id):
    """审核知识图谱关系"""
    extraction = get_object_or_404(ResourceKnowledgeExtraction, id=extraction_id, teacher=request.user)

    if extraction.status == 'review_pending':
        messages.info(request, '请先完成知识点审核。')
        return redirect('resource_review_knowledge_points', extraction_id=extraction_id)
    if extraction.status == 'completed':
        messages.info(request, '该提取已完成审核。')
        return redirect('resource_extraction_review', extraction_id=extraction_id)

    if extraction.status != 'reviewing_graph':
        extraction.status = 'reviewing_graph'
        extraction.save()

    unreviewed = ResourceReviewRelationship.objects.filter(
        extraction=extraction,
        reviewed_at__isnull=True
    ).order_by('id')[:10]

    return render(request, 'teacher/resource_review_relationships.html', {
        'extraction': extraction,
        'relationships': unreviewed,
    })


@login_required
@user_passes_test(is_teacher)
def resource_submit_review(request, extraction_id, review_type):
    """提交单个审核结果（AJAX）"""
    extraction = get_object_or_404(ResourceKnowledgeExtraction, id=extraction_id, teacher=request.user)

    if request.method == 'POST':
        if review_type == 'knowledge':
            kp_id = request.POST.get('knowledge_id')
            is_approved = request.POST.get('is_approved') == 'true'
            reviewed_name = request.POST.get('reviewed_name', '')
            review_notes = request.POST.get('review_notes', '')

            review = ResourceReviewKnowledgePoint.objects.get(
                extraction=extraction,
                knowledge_point_id=kp_id,
            )
            review.is_approved = is_approved
            review.reviewed_name = reviewed_name
            review.review_notes = review_notes
            review.reviewed_at = timezone.now()
            review.save()

            if reviewed_name and reviewed_name != review.knowledge_point.name:
                review.knowledge_point.name = reviewed_name
                review.knowledge_point.save()

            extraction.kp_reviewed = ResourceReviewKnowledgePoint.objects.filter(
                extraction=extraction, reviewed_at__isnull=False
            ).count()
            extraction.kp_approved = ResourceReviewKnowledgePoint.objects.filter(
                extraction=extraction, is_approved=True
            ).count()
            extraction.save()

            return JsonResponse({'success': True})

        elif review_type == 'relationship':
            rel_id = request.POST.get('relationship_id')
            is_approved = request.POST.get('is_approved') == 'true'
            is_rejected = request.POST.get('is_rejected') == 'true'
            review_notes = request.POST.get('review_notes', '')

            review = ResourceReviewRelationship.objects.get(
                extraction=extraction,
                id=rel_id,
            )
            review.is_approved = is_approved
            review.is_rejected = is_rejected
            review.review_notes = review_notes
            review.reviewed_at = timezone.now()
            review.save()

            extraction.rel_reviewed = ResourceReviewRelationship.objects.filter(
                extraction=extraction, reviewed_at__isnull=False
            ).count()
            extraction.rel_approved = ResourceReviewRelationship.objects.filter(
                extraction=extraction, is_approved=True
            ).count()
            extraction.save()

            return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
@user_passes_test(is_teacher)
def resource_complete_review(request, extraction_id):
    """完成审核"""
    extraction = get_object_or_404(ResourceKnowledgeExtraction, id=extraction_id, teacher=request.user)

    total_kps = ResourceReviewKnowledgePoint.objects.filter(extraction=extraction).count()
    reviewed_kps = ResourceReviewKnowledgePoint.objects.filter(
        extraction=extraction, reviewed_at__isnull=False
    ).count()
    total_rels = ResourceReviewRelationship.objects.filter(extraction=extraction).count()
    reviewed_rels = ResourceReviewRelationship.objects.filter(
        extraction=extraction, reviewed_at__isnull=False
    ).count()

    if reviewed_kps < total_kps or reviewed_rels < total_rels:
        messages.warning(request, '还有未审核的内容，请完成所有审核后再提交。')
        return redirect('resource_extraction_review', extraction_id=extraction_id)

    extraction.status = 'completed'
    extraction.completed_at = timezone.now()
    extraction.save()

    # --- 清理未通过审核的知识点和关系 ---
    # 删除被拒绝的知识图谱关系
    rejected_rels = ResourceReviewRelationship.objects.filter(
        extraction=extraction,
        is_rejected=True,
    )
    deleted_rel_count = 0
    for rel_review in rejected_rels:
        deleted_rel_count += KnowledgeGraph.objects.filter(
            subject=extraction.subject,
            source=rel_review.from_knowledge_point,
            target=rel_review.to_knowledge_point,
            relation_source=extraction.resource_file.resource_type,
        ).delete()[0]

    # 删除未通过审核的知识点
    unapproved_kps = ResourceReviewKnowledgePoint.objects.filter(
        extraction=extraction,
        is_approved=False,
    )
    deleted_kp_count = 0
    for kp_review in unapproved_kps:
        deleted_kp_count += kp_review.knowledge_point.delete()[0]

    if deleted_kp_count > 0 or deleted_rel_count > 0:
        msg_parts = []
        if deleted_kp_count > 0:
            msg_parts.append(f'已移除 {deleted_kp_count} 个未通过的知识点')
        if deleted_rel_count > 0:
            msg_parts.append(f'已移除 {deleted_rel_count} 条被拒绝的关系')
        messages.info(request, 'ℹ️ ' + '，'.join(msg_parts) + '。')

    messages.success(request, '✅ 知识提取审核完成！已提取的知识点已加入到知识图谱中。')
    return redirect(reverse('upload_resource') + f'?subject_id={extraction.subject.id}')