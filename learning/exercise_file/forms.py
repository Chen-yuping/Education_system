from django import forms
from learning.models import ExerciseFile, ResourceFile, TextbookCourseBuilder

class ExerciseFileForm(forms.ModelForm):
    class Meta:
        model = ExerciseFile
        fields = ['file']
        widgets = {
            'file': forms.FileInput(attrs={
                'class': 'd-none',
                'id': 'fileInput',
                # 👇 这里加了 .txt
                'accept': '.docx,.doc,.xlsx,.xls,.pdf,.txt'
            })
        }


class ResourceFileForm(forms.ModelForm):
    class Meta:
        model = ResourceFile
        fields = ['title', 'description', 'resource_type', 'file', 'is_public']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '请输入资料标题'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '请输入资料简要描述'
            }),
            'resource_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'file': forms.FileInput(attrs={
                'class': 'd-none',
                'id': 'fileInput',
                'accept': '.docx,.xlsx,.pptx,.pdf,.txt,.jpg,.jpeg,.png,.gif,.mp4,.mp3,.wav'
            }),
            'is_public': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }


class TextbookCourseBuilderForm(forms.ModelForm):
    class Meta:
        model = TextbookCourseBuilder
        fields = ['subject_name', 'subject_description', 'textbook_file']
        widgets = {
            'subject_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '请输入课程名称，如：高等数学'
            }),
            'subject_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '请输入课程简要描述（可选）'
            }),
            'textbook_file': forms.FileInput(attrs={
                'class': 'd-none',
                'id': 'textbookFileInput',
                'accept': '.pdf'
            })
        }