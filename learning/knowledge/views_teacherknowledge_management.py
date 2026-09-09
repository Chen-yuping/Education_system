"""
教师知识点管理视图
包括：添加、编辑、删除、查找知识点，以及管理知识点与习题的关联和知识点之间的关系
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction
from django.db.models import Q, Count
from ..models import KnowledgePoint, Subject, Exercise, QMatrix, KnowledgeGraph, TeacherSubject, ResourceFile
from ..forms import KnowledgePointForm
from ..utils_ai import llm_review_knowledge_points
from django.utils import timezone
from urllib.parse import quote
from io import BytesIO

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
    
    # 获取所有知识点（用于父知识点下拉菜单）
    all_knowledge_points = KnowledgePoint.objects.filter(subject=subject).order_by('id')
    
    context = {
        'subject': subject,
        'page_obj': knowledge_points,
        'knowledge_point_count': all_knowledge_points.count(),
        'search': search,
        'all_knowledge_points': all_knowledge_points,
    }
    
    return render(request, 'teacher/knowledge_point_list.html', context)


@login_required
@user_passes_test(is_teacher)
@require_POST
def review_knowledge_points_ai(request, subject_id):
    """调用大模型检查知识点质量，只返回建议，不修改数据。"""
    subject = get_object_or_404(Subject, id=subject_id)
    if not TeacherSubject.objects.filter(teacher=request.user, subject=subject).exists():
        return JsonResponse({'success': False, 'message': '您没有权限检查此科目的知识点'}, status=403)

    points = list(KnowledgePoint.objects.filter(subject=subject).select_related('parent').annotate(
        exercise_count=Count('qmatrix__exercise', distinct=True)
    ).order_by('id'))
    if not points:
        return JsonResponse({'success': False, 'message': '本科目暂无知识点'}, status=400)

    try:
        raw_issues = llm_review_knowledge_points(subject, points)
        point_map = {point.id: point for point in points}
        issues = []
        seen_ids = set()
        for item in raw_issues:
            try:
                point_id = int(item.get('id'))
            except (AttributeError, TypeError, ValueError):
                continue
            action = item.get('action')
            if point_id not in point_map or point_id in seen_ids or action not in ('modify', 'delete'):
                continue
            seen_ids.add(point_id)
            issues.append({
                'id': point_id,
                'name': point_map[point_id].name,
                'action': action,
                'reason': str(item.get('reason', '')).strip(),
                'suggested_name': str(item.get('suggested_name', '')).strip(),
            })
        request.session[f'knowledge_review_{subject.id}'] = {
            'subject_name': subject.name,
            'total': len(points),
            'issues': issues,
            'reviewed_at': timezone.localtime().strftime('%Y-%m-%d %H:%M:%S'),
        }
        return JsonResponse({
            'success': True,
            'total': len(points),
            'issues': issues,
            'message': '未发现明显问题' if not issues else f'发现 {len(issues)} 个建议关注的知识点',
        })
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'大模型检查失败：{exc}'}, status=500)


@login_required
@user_passes_test(is_teacher)
@require_GET
def export_knowledge_review_pdf(request, subject_id):
    """导出当前教师最近一次 AI 知识点检查报告。"""
    subject = get_object_or_404(Subject, id=subject_id)
    if not TeacherSubject.objects.filter(teacher=request.user, subject=subject).exists():
        return HttpResponse('您没有权限导出此科目的检查报告', status=403)

    report = request.session.get(f'knowledge_review_{subject.id}')
    if not report:
        return HttpResponse('请先执行一次 AI 知识点检查，再导出 PDF。', status=400)

    try:
        from html import escape
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    except ImportError:
        return HttpResponse('服务器缺少 PDF 生成组件 reportlab，请安装后重试。', status=500)

    buffer = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=f'{subject.name} - AI 知识点检查报告', author=request.user.username,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ChineseTitle', parent=styles['Title'], fontName='STSong-Light',
        fontSize=20, leading=28, alignment=TA_CENTER, textColor=colors.HexColor('#3730a3'),
    )
    body_style = ParagraphStyle(
        'ChineseBody', parent=styles['BodyText'], fontName='STSong-Light',
        fontSize=10.5, leading=17, textColor=colors.HexColor('#333333'),
    )
    heading_style = ParagraphStyle(
        'ChineseHeading', parent=body_style, fontSize=13, leading=20,
        textColor=colors.HexColor('#4338ca'), spaceBefore=8, spaceAfter=6,
    )
    issues = report.get('issues', [])
    story = [
        Paragraph('AI 知识点检查报告', title_style), Spacer(1, 6 * mm),
        Paragraph(f"<b>课程：</b>{escape(str(report.get('subject_name', subject.name)))}", body_style),
        Paragraph(f"<b>检查时间：</b>{escape(str(report.get('reviewed_at', '')))}", body_style),
        Paragraph(f"<b>知识点总数：</b>{int(report.get('total', 0))}", body_style),
        Paragraph(f"<b>建议关注：</b>{len(issues)} 个", body_style), Spacer(1, 6 * mm),
    ]
    if not issues:
        story.extend([
            Paragraph('检查结论', heading_style),
            Paragraph('未发现明显需要修改或删除的知识点。', body_style),
        ])
    else:
        story.append(Paragraph('检查建议', heading_style))
        for index, issue in enumerate(issues, 1):
            action = '建议删除' if issue.get('action') == 'delete' else '建议修改'
            rows = [
                [Paragraph(f"<b>{index}. {escape(str(issue.get('name', '')))}</b>", body_style), Paragraph(action, body_style)],
                [Paragraph('<b>原因</b>', body_style), Paragraph(escape(str(issue.get('reason', '') or '模型未提供原因')), body_style)],
            ]
            if issue.get('action') == 'modify' and issue.get('suggested_name'):
                rows.append([Paragraph('<b>建议名称</b>', body_style), Paragraph(escape(str(issue.get('suggested_name'))), body_style)])
            table = Table(rows, colWidths=[38 * mm, 116 * mm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'STSong-Light'),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2ff')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ]))
            story.append(KeepTogether([table, Spacer(1, 4 * mm)]))
    story.extend([Spacer(1, 4 * mm), Paragraph('说明：本报告由大模型生成，仅供教师审核参考，不会自动修改或删除知识点。', body_style)])

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('STSong-Light', 9)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawCentredString(A4[0] / 2, 10 * mm, f'第 {doc.page} 页')
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'{subject.name}-AI知识点检查报告.pdf'
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response

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
    associated_exercise_ids = QMatrix.objects.filter(
        knowledge_point=knowledge_point
    ).values_list('exercise_id', flat=True)
    
    associated_exercises = Exercise.objects.filter(
        id__in=associated_exercise_ids
    ).order_by('id')
    
    # 为每个习题标记是否已关联
    for exercise in all_exercises:
        exercise.is_associated = exercise.id in associated_exercise_ids
    
    context = {
        'subject': subject,
        'knowledge_point': knowledge_point,
        'all_exercises': all_exercises,
        'associated_exercises': associated_exercises,
        'associated_count': len(associated_exercise_ids),
        'total_exercises': all_exercises.count(),
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
        'source', 'target', 'resource_file'
    )

    # 获取该科目下有关联的资源文件（用于关系来源下拉框）
    resource_file_ids = KnowledgePoint.objects.filter(
        subject=subject,
        resource_files__isnull=False
    ).values_list('resource_files', flat=True).distinct()
    resource_files = ResourceFile.objects.filter(id__in=set(resource_file_ids))

    context = {
        'subject': subject,
        'knowledge_points': knowledge_points,
        'relationships': relationships,
        'resource_files': resource_files,
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
        rel_type = request.POST.get('relationship_type', '相似')
        if rel_type not in dict(KnowledgeGraph.RELATION_CHOICES):
            return JsonResponse({'success': False, 'message': '无效的关系类型'}, status=400)
        resource_file_id = request.POST.get('resource_file_id')

        source = get_object_or_404(KnowledgePoint, id=source_id, subject=subject)
        target = get_object_or_404(KnowledgePoint, id=target_id, subject=subject)

        # 不能自己指向自己
        if source_id == target_id:
            return JsonResponse({
                'success': False,
                'message': '知识点不能指向自己'
            })

        # 查找资源文件
        resource_file = None
        rel_source = '教材'
        if resource_file_id:
            try:
                resource_file = ResourceFile.objects.get(id=resource_file_id, subject=subject)
                rel_source = resource_file.resource_type
            except ResourceFile.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': '所选资料文件不存在'
                }, status=400)

        # 检查是否已存在（以 resource_file 为准，兼容旧版 relation_source）
        dup_filter = {'subject': subject, 'source': source, 'target': target}
        if resource_file:
            dup_filter['resource_file'] = resource_file
        else:
            dup_filter['resource_file__isnull'] = True
            dup_filter['relation_source'] = rel_source
        if KnowledgeGraph.objects.filter(**dup_filter).exists():
            return JsonResponse({
                'success': False,
                'message': '该关系已存在'
            })

        # 创建关系
        kg = KnowledgeGraph.objects.create(
            subject=subject,
            source=source,
            target=target,
            relationship_type=rel_type,
            relation_source=rel_source,
            resource_file=resource_file,
        )

        # 关联知识点的 resource_files M2M（删除关系后保留，用于分图谱节点展示）
        if resource_file:
            for kp in (source, target):
                kp.resource_files.add(resource_file)

        # 更新知识点来源记录（向后兼容）
        for kp in (source, target):
            if rel_source not in kp.sources.split(','):
                kp.sources = (kp.sources + ',' + rel_source) if kp.sources else rel_source
                kp.save(update_fields=['sources'])

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

# ==================== API 端点 ====================

@login_required
@user_passes_test(is_teacher)
@require_GET
def get_knowledge_point(request, kp_id):
    """获取知识点详情"""
    try:
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id)
        
        return JsonResponse({
            'success': True,
            'knowledge_point': {
                'id': knowledge_point.id,
                'name': knowledge_point.name,
                'parent_id': knowledge_point.parent_id,
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def update_knowledge_point(request, kp_id):
    """更新知识点"""
    try:
        import json
        data = json.loads(request.body)
        
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id)
        
        knowledge_point.name = data.get('name', knowledge_point.name)
        
        parent_id = data.get('parent')
        if parent_id:
            knowledge_point.parent_id = parent_id
        else:
            knowledge_point.parent = None
        
        knowledge_point.save()
        
        return JsonResponse({
            'success': True,
            'message': '知识点已更新'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_GET
def get_knowledge_point_exercises(request, kp_id):
    """获取知识点的习题列表"""
    try:
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id)
        
        # 获取该科目的所有习题
        all_exercises = Exercise.objects.filter(subject=knowledge_point.subject).values(
            'id', 'title', 'content', 'question_type'
        ).order_by('id')
        
        # 获取该知识点已关联的习题ID
        associated_exercise_ids = list(QMatrix.objects.filter(
            knowledge_point=knowledge_point
        ).values_list('exercise_id', flat=True))
        
        # 格式化习题类型显示
        question_type_map = {
            '1': '单选题',
            '2': '多选题',
            '3': '投票题',
            '4': '填空题',
            '5': '主观题',
            '6': '判断题',
            'short': '简答题',
            'essay': '论述题',
        }
        
        exercises_list = []
        for ex in all_exercises:
            question_type_display = question_type_map.get(ex['question_type'], ex['question_type'])
            exercises_list.append({
                'id': ex['id'],
                'title': ex['title'],
                'content': ex['content'][:100] if ex['content'] else '',  # 截断内容
                'question_type': question_type_display
            })
        
        return JsonResponse({
            'success': True,
            'all_exercises': exercises_list,
            'associated_exercise_ids': associated_exercise_ids
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def toggle_exercise_association_api(request, kp_id):
    """关联或取消关联习题 (API版本)"""
    try:
        import json
        data = json.loads(request.body)
        
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id)
        exercise_id = data.get('exercise_id')
        
        exercise = get_object_or_404(Exercise, id=exercise_id, subject=knowledge_point.subject)
        
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
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_GET
def get_knowledge_point_relationships(request, subject_id):
    """获取知识点关系列表"""
    try:
        subject = get_object_or_404(Subject, id=subject_id)
        
        # 获取所有关系
        relationships = KnowledgeGraph.objects.filter(subject=subject).select_related(
            'source', 'target'
        ).values('id', 'source__id', 'source__name', 'target__id', 'target__name', 'relationship_type')

        relationships_list = []
        for rel in relationships:
            relationships_list.append({
                'id': rel['id'],
                'source': {
                    'id': rel['source__id'],
                    'name': rel['source__name']
                },
                'target': {
                    'id': rel['target__id'],
                    'name': rel['target__name']
                },
                'relationship_type': rel['relationship_type'],
            })
        
        return JsonResponse({
            'success': True,
            'relationships': relationships_list
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


def _knowledge_graph_ai_input(subject):
    """构造只包含当前科目合法节点和边的 AI 输入。"""
    knowledge_points = list(
        KnowledgePoint.objects.filter(subject=subject)
        .order_by('id')
        .values('id', 'name')
    )
    relationships = list(
        KnowledgeGraph.objects.filter(subject=subject)
        .order_by('id')
        .values('id', 'source_id', 'target_id', 'relationship_type')
    )
    return knowledge_points, relationships


@login_required
@user_passes_test(is_teacher)
@require_POST
def ai_optimize_knowledge_relationships(request, subject_id):
    """AI 修正已有关系类型/方向并补充缺失关系。"""
    subject = get_object_or_404(Subject, id=subject_id)
    if not TeacherSubject.objects.filter(teacher=request.user, subject=subject).exists():
        return JsonResponse({'success': False, 'message': '您没有权限管理此科目'}, status=403)

    knowledge_points, relationships = _knowledge_graph_ai_input(subject)
    if len(knowledge_points) < 2:
        return JsonResponse({'success': False, 'message': '当前科目至少需要两个知识点'}, status=400)

    try:
        from ..knowledge_graph_builder.relation_ai import optimize_relations, VALID_RELATION_TYPES

        ai_result = optimize_relations(subject.name, knowledge_points, relationships)
        valid_kp_ids = {item['id'] for item in knowledge_points}
        existing_by_id = {
            relation.id: relation
            for relation in KnowledgeGraph.objects.filter(subject=subject)
        }
        updated = []
        created = []
        skipped = []

        with transaction.atomic():
            for item in ai_result.get('updates', []):
                try:
                    relation_id = int(item.get('relationship_id'))
                    source_id = int(item.get('source_id'))
                    target_id = int(item.get('target_id'))
                except (TypeError, ValueError):
                    skipped.append('AI 返回了无效的关系 ID')
                    continue

                relation_type = item.get('relationship_type')
                relation = existing_by_id.get(relation_id)
                if (not relation or source_id not in valid_kp_ids or
                        target_id not in valid_kp_ids or source_id == target_id or
                        relation_type not in VALID_RELATION_TYPES):
                    skipped.append(f'关系 #{relation_id} 的修改数据无效')
                    continue

                duplicate_exists = KnowledgeGraph.objects.filter(
                    subject=subject,
                    source_id=source_id,
                    target_id=target_id,
                    relation_source=relation.relation_source,
                ).exclude(id=relation.id).exists()
                if duplicate_exists:
                    skipped.append(f'关系 #{relation_id} 修改后会与已有关系重复')
                    continue

                changed = (
                    relation.source_id != source_id or
                    relation.target_id != target_id or
                    relation.relationship_type != relation_type
                )
                if changed:
                    relation.source_id = source_id
                    relation.target_id = target_id
                    relation.relationship_type = relation_type
                    relation.save(update_fields=['source', 'target', 'relationship_type'])
                    updated.append({
                        'id': relation.id,
                        'source_id': source_id,
                        'target_id': target_id,
                        'relationship_type': relation_type,
                        'reason': item.get('reason', ''),
                    })

            for item in ai_result.get('additions', []):
                try:
                    source_id = int(item.get('source_id'))
                    target_id = int(item.get('target_id'))
                except (TypeError, ValueError):
                    skipped.append('AI 返回了无效的知识点 ID')
                    continue

                relation_type = item.get('relationship_type')
                if (source_id not in valid_kp_ids or target_id not in valid_kp_ids or
                        source_id == target_id or relation_type not in VALID_RELATION_TYPES):
                    skipped.append(f'新增关系 {source_id} → {target_id} 的数据无效')
                    continue

                if KnowledgeGraph.objects.filter(
                        subject=subject, source_id=source_id, target_id=target_id).exists():
                    skipped.append(f'关系 {source_id} → {target_id} 已存在')
                    continue

                relation = KnowledgeGraph.objects.create(
                    subject=subject,
                    source_id=source_id,
                    target_id=target_id,
                    relationship_type=relation_type,
                    relation_source='融合',
                )
                created.append({
                    'id': relation.id,
                    'source_id': source_id,
                    'target_id': target_id,
                    'relationship_type': relation_type,
                    'reason': item.get('reason', ''),
                })

        return JsonResponse({
            'success': True,
            'message': f'AI 优化完成：修改 {len(updated)} 条，新增 {len(created)} 条',
            'summary': ai_result.get('summary', ''),
            'updated': updated,
            'created': created,
            'skipped': skipped,
        })
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'AI 优化失败：{exc}'}, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def ai_check_knowledge_relationships(request, subject_id):
    """只读检查当前科目已有知识点关系的合理性。"""
    subject = get_object_or_404(Subject, id=subject_id)
    if not TeacherSubject.objects.filter(teacher=request.user, subject=subject).exists():
        return JsonResponse({'success': False, 'message': '您没有权限查看此科目'}, status=403)

    knowledge_points, relationships = _knowledge_graph_ai_input(subject)
    if len(knowledge_points) < 2:
        return JsonResponse({'success': False, 'message': '当前科目至少需要两个知识点'}, status=400)

    try:
        from ..knowledge_graph_builder.relation_ai import check_relations, VALID_RELATION_TYPES

        ai_result = check_relations(subject.name, knowledge_points, relationships)
        kp_names = {item['id']: item['name'] for item in knowledge_points}
        relation_ids = {item['id'] for item in relationships}
        relationships_by_id = {item['id']: item for item in relationships}

        issues = []
        for item in ai_result.get('issues', []):
            try:
                relation_id = int(item.get('relationship_id'))
            except (TypeError, ValueError):
                continue
            if relation_id in relation_ids:
                relation = relationships_by_id[relation_id]
                issues.append({
                    'relationship_id': relation_id,
                    'source_name': kp_names.get(relation['source_id'], str(relation['source_id'])),
                    'target_name': kp_names.get(relation['target_id'], str(relation['target_id'])),
                    'relationship_type': relation['relationship_type'],
                    'severity': item.get('severity', '中'),
                    'problem': item.get('problem', ''),
                    'suggestion': item.get('suggestion', ''),
                })

        missing_relations = []
        for item in ai_result.get('missing_relations', []):
            try:
                source_id = int(item.get('source_id'))
                target_id = int(item.get('target_id'))
            except (TypeError, ValueError):
                continue
            relation_type = item.get('relationship_type')
            if (source_id in kp_names and target_id in kp_names and source_id != target_id and
                    relation_type in VALID_RELATION_TYPES):
                missing_relations.append({
                    'source_id': source_id,
                    'source_name': kp_names[source_id],
                    'target_id': target_id,
                    'target_name': kp_names[target_id],
                    'relationship_type': relation_type,
                    'reason': item.get('reason', ''),
                })

        try:
            score = max(0, min(100, int(ai_result.get('score', 0))))
        except (TypeError, ValueError):
            score = 0

        return JsonResponse({
            'success': True,
            'overall': ai_result.get('overall', ''),
            'score': score,
            'issues': issues,
            'missing_relations': missing_relations,
            'relationship_count': len(relationships),
        })
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'AI 检查失败：{exc}'}, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def add_knowledge_point_relationship_api(request, subject_id):
    """添加知识点关系 (API版本)"""
    try:
        import json
        data = json.loads(request.body)

        subject = get_object_or_404(Subject, id=subject_id)

        source_id = data.get('source_id')
        target_id = data.get('target_id')
        rel_type = data.get('relationship_type', '相似')
        if rel_type not in dict(KnowledgeGraph.RELATION_CHOICES):
            return JsonResponse({'success': False, 'message': '无效的关系类型'}, status=400)
        resource_file_id = data.get('resource_file_id')

        source = get_object_or_404(KnowledgePoint, id=source_id, subject=subject)
        target = get_object_or_404(KnowledgePoint, id=target_id, subject=subject)

        # 不能自己指向自己
        if source_id == target_id:
            return JsonResponse({
                'success': False,
                'message': '知识点不能指向自己'
            })

        # 查找资源文件
        resource_file = None
        rel_source = '教材'
        if resource_file_id:
            try:
                resource_file = ResourceFile.objects.get(id=resource_file_id, subject=subject)
                rel_source = resource_file.resource_type
            except ResourceFile.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': '所选资料文件不存在'
                }, status=400)

        # 检查是否已存在（以 resource_file 为准）
        dup_filter = {'subject': subject, 'source': source, 'target': target}
        if resource_file:
            dup_filter['resource_file'] = resource_file
        else:
            dup_filter['resource_file__isnull'] = True
            dup_filter['relation_source'] = rel_source
        if KnowledgeGraph.objects.filter(**dup_filter).exists():
            return JsonResponse({
                'success': False,
                'message': '该关系已存在'
            })

        # 创建关系
        kg = KnowledgeGraph.objects.create(
            subject=subject,
            source=source,
            target=target,
            relationship_type=rel_type,
            relation_source=rel_source,
            resource_file=resource_file,
        )

        # 关联知识点的 resource_files M2M（删除关系后保留，用于分图谱节点展示）
        if resource_file:
            for kp in (source, target):
                kp.resource_files.add(resource_file)

        # 更新知识点来源记录（向后兼容）
        for kp in (source, target):
            if rel_source not in kp.sources.split(','):
                kp.sources = (kp.sources + ',' + rel_source) if kp.sources else rel_source
                kp.save(update_fields=['sources'])
        
        return JsonResponse({
            'success': True,
            'message': f'已添加关系：{source.name} → {target.name}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def delete_knowledge_point_relationship_api(request, subject_id, relationship_id):
    """删除知识点关系 (API版本)"""
    try:
        subject = get_object_or_404(Subject, id=subject_id)
        relationship = get_object_or_404(KnowledgeGraph, id=relationship_id, subject=subject)
        
        source_name = relationship.source.name
        target_name = relationship.target.name
        relationship.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'已删除关系：{source_name} → {target_name}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@user_passes_test(is_teacher)
@require_POST
def delete_knowledge_point_with_relations_api(request, subject_id, kp_id):
    """删除知识点及其所有关联关系"""
    try:
        subject = get_object_or_404(Subject, id=subject_id)
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id, subject=subject)

        if not TeacherSubject.objects.filter(teacher=request.user, subject=subject).exists():
            return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)

        exercise_count = QMatrix.objects.filter(knowledge_point=knowledge_point).count()
        if exercise_count > 0:
            return JsonResponse({
                'success': False,
                'message': f'该知识点关联了 {exercise_count} 道习题，请先解除习题关联再删除'
            })

        kp_name = knowledge_point.name
        rel_count = KnowledgeGraph.objects.filter(
            Q(source=knowledge_point) | Q(target=knowledge_point)
        ).count()

        # 删除相关关系（只删关系记录，不删另一端的知识点）
        KnowledgeGraph.objects.filter(
            Q(source=knowledge_point) | Q(target=knowledge_point)
        ).delete()
        knowledge_point.delete()

        return JsonResponse({
            'success': True,
            'message': f'已删除知识点"{kp_name}"及其{rel_count}条关联关系'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


    """关联或取消关联习题 (API版本)"""
    try:
        import json
        data = json.loads(request.body)
        
        knowledge_point = get_object_or_404(KnowledgePoint, id=kp_id)
        exercise_id = data.get('exercise_id')
        
        exercise = get_object_or_404(Exercise, id=exercise_id, subject=knowledge_point.subject)
        
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
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== 批量上传知识点 ====================
@login_required
@user_passes_test(is_teacher)
@require_POST
def batch_upload_knowledge_points(request, subject_id):
    """批量上传知识点"""
    try:
        import csv
        import io
        
        teacher = request.user
        subject = get_object_or_404(Subject, id=subject_id)
        
        # 验证教师权限
        if not TeacherSubject.objects.filter(teacher=teacher, subject=subject).exists():
            return JsonResponse({'success': False, 'message': '您没有权限'}, status=403)
        
        # 获取上传的文件
        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'message': '未找到文件'})
        
        file = request.FILES['file']
        
        # 检查文件类型
        if not file.name.endswith('.csv'):
            return JsonResponse({'success': False, 'message': '请上传CSV格式的文件'})
        
        # 读取CSV文件
        try:
            # 处理编码问题
            content = file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                content = file.read().decode('gbk')
            except UnicodeDecodeError:
                content = file.read().decode('latin-1')
        
        # 解析CSV
        csv_reader = csv.reader(io.StringIO(content))
        
        created_count = 0
        skipped_count = 0
        errors = []
        
        # 创建一个字典来缓存已创建的知识点，用于处理父子关系
        kp_cache = {}
        
        for row_num, row in enumerate(csv_reader, 1):
            if not row or not row[0].strip():
                continue
            
            try:
                kp_name = row[0].strip()
                parent_name = row[1].strip() if len(row) > 1 else None
                
                # 检查知识点是否已存在
                existing_kp = KnowledgePoint.objects.filter(
                    subject=subject,
                    name=kp_name
                ).first()
                
                if existing_kp:
                    skipped_count += 1
                    continue
                
                # 处理父知识点
                parent = None
                if parent_name:
                    # 先从缓存中查找
                    if parent_name in kp_cache:
                        parent = kp_cache[parent_name]
                    else:
                        # 从数据库中查找
                        parent = KnowledgePoint.objects.filter(
                            subject=subject,
                            name=parent_name
                        ).first()
                        
                        if not parent:
                            # 如果父知识点不存在，先创建它
                            parent = KnowledgePoint.objects.create(
                                subject=subject,
                                name=parent_name
                            )
                            kp_cache[parent_name] = parent
                
                # 创建知识点
                kp = KnowledgePoint.objects.create(
                    subject=subject,
                    name=kp_name,
                    parent=parent
                )
                
                # 加入缓存
                kp_cache[kp_name] = kp
                created_count += 1
                
            except Exception as e:
                errors.append(f'第 {row_num} 行出错: {str(e)}')
        
        return JsonResponse({
            'success': True,
            'created_count': created_count,
            'skipped_count': skipped_count,
            'errors': errors,
            'message': f'成功上传 {created_count} 个知识点，{skipped_count} 个已存在'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)
