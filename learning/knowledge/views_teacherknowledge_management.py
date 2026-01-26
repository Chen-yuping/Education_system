"""
教师知识点管理视图
包括：添加、编辑、删除、查找知识点，以及管理知识点与习题的关联和知识点之间的关系
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.db.models import Q, Count
from django.core.paginator import Paginator
from ..models import KnowledgePoint, Subject, Exercise, QMatrix, KnowledgeGraph, TeacherSubject
from ..forms import KnowledgePointForm

def is_teacher(user):
    return user.user_type == 'teacher'

# ==================== 知识点列表 ====================
@login_required
@user_passes_test(is_teacher)
def knowledge_point_list(request, subject_id):
    """知识点列表页面"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        messages.error(request, '您没有权限管理此科目的知识点')
        return redirect('teacher_course_management')
    
    # 获取搜索参数
    search = request.GET.get('search', '')
    
    # 获取知识点列表
    knowledge_points = KnowledgePoint.objects.filter(subject=subject)
    
    if search:
        knowledge_points = knowledge_points.filter(name__icontains=search)
    
    # 为每个知识点添加关联的习题数量
    knowledge_points = knowledge_points.annotate(
        exercise_count=Count('qmatrix__exercise', distinct=True)
    ).order_by('id')
    
    # 分页
    paginator = Paginator(knowledge_points, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'subject': subject,
        'page_obj': page_obj,
        'search': search,
    }
    
    return render(request, 'teacher/knowledge_point_list.html', context)

# ==================== 添加知识点 ====================
@login_required
@user_passes_test(is_teacher)
def knowledge_point_add(request, subject_id):
    """添加知识点"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        messages.error(request, '您没有权限管理此科目的知识点')
        return redirect('teacher_course_management')
    
    if request.method == 'POST':
        form = KnowledgePointForm(request.POST)
        if form.is_valid():
            kp = form.save(commit=False)
            kp.subject = subject
            kp.save()
            messages.success(request, f'知识点 "{kp.name}" 添加成功')
            return redirect('knowledge_point_list', subject_id=subject_id)
    else:
        form = KnowledgePointForm()
        # 限制parent只能选择同一科目的知识点
        form.fields['parent'].queryset = KnowledgePoint.objects.filter(subject=subject)
    
    context = {
        'subject': subject,
        'form': form,
        'title': '添加知识点',
    }
    
    return render(request, 'teacher/knowledge_point_form.html', context)

# ==================== 编辑知识点 ====================
@login_required
@user_passes_test(is_teacher)
def knowledge_point_edit(request, subject_id, kp_id):
    """编辑知识点"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id, subject=subject)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        messages.error(request, '您没有权限管理此科目的知识点')
        return redirect('teacher_course_management')
    
    if request.method == 'POST':
        form = KnowledgePointForm(request.POST, instance=knowledge_point)
        if form.is_valid():
            kp = form.save()
            messages.success(request, f'知识点 "{kp.name}" 更新成功')
            return redirect('knowledge_point_list', subject_id=subject_id)
    else:
        form = KnowledgePointForm(instance=knowledge_point)
        # 限制parent只能选择同一科目的知识点，且不能选择自己
        form.fields['parent'].queryset = KnowledgePoint.objects.filter(
            subject=subject
        ).exclude(id=kp_id)
    
    context = {
        'subject': subject,
        'knowledge_point': knowledge_point,
        'form': form,
        'title': '编辑知识点',
    }
    
    return render(request, 'teacher/knowledge_point_form.html', context)

# ==================== 删除知识点 ====================
@login_required
@user_passes_test(is_teacher)
@require_POST
def knowledge_point_delete(request, subject_id, kp_id):
    """删除知识点"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id, subject=subject)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)
    
    # 检查是否有关联的习题
    exercise_count = QMatrix.objects.filter(knowledge_point=knowledge_point).count()
    if exercise_count > 0:
        return JsonResponse({
            'success': False,
            'message': f'该知识点关联了 {exercise_count} 道习题，无法删除。请先删除关联的习题。'
        })
    
    kp_name = knowledge_point.name
    knowledge_point.delete()
    
    messages.success(request, f'知识点 "{kp_name}" 已删除')
    return redirect('knowledge_point_list', subject_id=subject_id)

# ==================== 知识点与习题关联 ====================
@login_required
@user_passes_test(is_teacher)
def knowledge_point_exercise_association(request, subject_id, kp_id):
    """管理知识点与习题的关联"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id, subject=subject)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        messages.error(request, '您没有权限管理此科目的知识点')
        return redirect('teacher_course_management')
    
    # 获取该科目的所有习题
    all_exercises = Exercise.objects.filter(subject=subject).order_by('id')
    
    # 获取该知识点已关联的习题
    associated_exercises = QMatrix.objects.filter(
        knowledge_point=knowledge_point
    ).values_list('exercise_id', flat=True)
    
    # 分页
    paginator = Paginator(all_exercises, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # 为每个习题标记是否已关联
    for exercise in page_obj:
        exercise.is_associated = exercise.id in associated_exercises
    
    context = {
        'subject': subject,
        'knowledge_point': knowledge_point,
        'page_obj': page_obj,
        'associated_count': len(associated_exercises),
    }
    
    return render(request, 'teacher/knowledge_point_exercise_association.html', context)

# ==================== 关联/取消关联习题 API ====================
@login_required
@user_passes_test(is_teacher)
@require_POST
def toggle_exercise_association(request, subject_id, kp_id):
    """关联或取消关联习题"""
    try:
        teacher = request.user
        subject = get_object_or_404(Subject, id=subject_id)
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id, subject=subject)
        
        # 验证教师权限
        if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
            return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)
        
        exercise_id = request.POST.get('exercise_id')
        exercise = get_object_or_404(Exercise, id=exercise_id, subject=subject)
        
        # 检查是否已关联
        qmatrix = QMatrix.objects.filter(
            knowledge_point=knowledge_point,
            exercise=exercise
        ).first()
        
        if qmatrix:
            # 取消关联
            qmatrix.delete()
            return JsonResponse({
                'success': True,
                'action': 'removed',
                'message': '已取消关联'
            })
        else:
            # 关联
            QMatrix.objects.create(
                knowledge_point=knowledge_point,
                exercise=exercise,
                weight=1.0
            )
            return JsonResponse({
                'success': True,
                'action': 'added',
                'message': '已关联'
            })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

# ==================== 知识点关系管理 ====================
@login_required
@user_passes_test(is_teacher)
def knowledge_point_relationship(request, subject_id):
    """管理知识点之间的关系"""
    teacher = request.user
    subject = get_object_or_404(Subject, id=subject_id)
    
    # 验证教师权限
    if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
        messages.error(request, '您没有权限管理此科目的知识点')
        return redirect('teacher_course_management')
    
    # 获取所有知识点
    knowledge_points = KnowledgePoint.objects.filter(subject=subject).order_by('id')
    
    # 获取所有关系
    relationships = KnowledgeGraph.objects.filter(subject=subject).select_related(
        'source', 'target'
    )
    
    context = {
        'subject': subject,
        'knowledge_points': knowledge_points,
        'relationships': relationships,
    }
    
    return render(request, 'teacher/knowledge_point_relationship.html', context)

# ==================== 添加知识点关系 API ====================
@login_required
@user_passes_test(is_teacher)
@require_POST
def add_knowledge_relationship(request, subject_id):
    """添加知识点关系"""
    try:
        teacher = request.user
        subject = get_object_or_404(Subject, id=subject_id)
        
        # 验证教师权限
        if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
            return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)
        
        source_id = request.POST.get('source_id')
        target_id = request.POST.get('target_id')
        
        source = get_object_or_404(KnowledgePoint, id=source_id, subject=subject)
        target = get_object_or_404(KnowledgePoint, id=target_id, subject=subject)
        
        # 不能自己指向自己
        if source_id == target_id:
            return JsonResponse({
                'success': False,
                'message': '知识点不能指向自己'
            })
        
        # 检查是否已存在
        if KnowledgeGraph.objects.filter(
            subject=subject,
            source=source,
            target=target
        ).exists():
            return JsonResponse({
                'success': False,
                'message': '该关系已存在'
            })
        
        # 创建关系
        KnowledgeGraph.objects.create(
            subject=subject,
            source=source,
            target=target
        )
        
        return JsonResponse({
            'success': True,
            'message': f'已添加关系：{source.name} → {target.name}'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

# ==================== 删除知识点关系 API ====================
@login_required
@user_passes_test(is_teacher)
@require_POST
def delete_knowledge_relationship(request, subject_id, relationship_id):
    """删除知识点关系"""
    try:
        teacher = request.user
        subject = get_object_or_404(Subject, id=subject_id)
        relationship = get_object_or_404(KnowledgeGraph, id=relationship_id, subject=subject)
        
        # 验证教师权限
        if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
            return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)
        
        source_name = relationship.source.name
        target_name = relationship.target.name
        relationship.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'已删除关系：{source_name} → {target_name}'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)
