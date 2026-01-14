from django import forms
from .models import *
import json
from django.http import JsonResponse

class ExerciseForm(forms.ModelForm):
    class Meta:
        model = Exercise
        fields = ['subject', 'title', 'content', 'question_type']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4}),
        }

class KnowledgePointForm(forms.ModelForm):
    class Meta:
        model = KnowledgePoint
        fields = ['subject', 'name', 'parent']

class QMatrixForm(forms.ModelForm):
    class Meta:
        model = QMatrix
        fields = ['exercise', 'knowledge_point', 'weight']

#老师的习题编辑表单
class ExerciseEditForm(forms.ModelForm):
    """习题编辑表单"""

    # 知识点选择（多选）
    knowledge_points = forms.ModelMultipleChoiceField(
        queryset=KnowledgePoint.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="关联知识点"
    )

    # 知识点权重（与知识点一一对应）
    knowledge_weights = forms.CharField(
        widget=forms.HiddenInput,
        required=False
    )

    class Meta:
        model = Exercise
        fields = ['title', 'content', 'question_type', 'subject', 'option_text', 'answer']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'question_type': forms.Select(attrs={'class': 'form-control'}),
            'subject': forms.Select(attrs={'class': 'form-control'}),
            'option_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4,
                                                 'placeholder': '每行一个选项，例如：\nA. 选项一\nB. 选项二\nC. 选项三\nD. 选项四'}),
            'answer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '例如：A 或 AB 或 答案文本'}),
        }
        labels = {
            'title': '习题标题',
            'content': '习题内容',
            'question_type': '题型',
            'subject': '所属科目',
            'option_text': '选项内容',
            'answer': '参考答案',
        }

    def __init__(self, *args, **kwargs):
        # 获取当前用户（老师）的授课科目
        self.teacher = kwargs.pop('teacher', None)
        super().__init__(*args, **kwargs)

        # 限制科目只能选择老师授课的科目
        if self.teacher:
            teacher_subjects = TeacherSubject.objects.filter(
                teacher=self.teacher
            ).values_list('subject_id', flat=True)
            self.fields['subject'].queryset = Subject.objects.filter(id__in=teacher_subjects)

        # 如果习题已存在，设置知识点的初始值
        if self.instance and self.instance.pk:
            # 获取当前习题关联的知识点和权重
            qmatrices = self.instance.qmatrix_set.all()
            initial_knowledge_points = [qp.knowledge_point_id for qp in qmatrices]
            self.fields['knowledge_points'].initial = initial_knowledge_points

            # 设置知识点的权重数据
            weight_data = {str(qp.knowledge_point_id): qp.weight for qp in qmatrices}
            self.fields['knowledge_weights'].initial = json.dumps(weight_data)

            # 限制知识点只能选择当前科目下的知识点
            if self.instance.subject:
                self.fields['knowledge_points'].queryset = KnowledgePoint.objects.filter(
                    subject=self.instance.subject
                )