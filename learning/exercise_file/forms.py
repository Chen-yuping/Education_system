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
            }),
            'is_public': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def clean(self):
        cleaned_data = super().clean()
        resource_type = cleaned_data.get('resource_type')
        file_obj = cleaned_data.get('file')

        if resource_type and file_obj:
            ext = '.' + file_obj.name.split('.').pop().lower()
            type_ext_map = {
                '教材': ['.doc', '.docx', '.pdf'],
                '教案': ['.doc', '.docx', '.pdf'],
                '课件': ['.ppt', '.pptx'],
                '习题': ['.doc', '.docx', '.xlsx', '.xls', '.pdf', '.txt'],
            }
            allowed = type_ext_map.get(resource_type)
            if allowed and ext not in allowed:
                allowed_str = '、'.join(allowed)
                raise forms.ValidationError(
                    f'资料类型为"{dict(ResourceFile.RESOURCE_TYPES).get(resource_type, resource_type)}"时，'
                    f'仅支持上传 {allowed_str} 格式的文件'
                )
        return cleaned_data


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