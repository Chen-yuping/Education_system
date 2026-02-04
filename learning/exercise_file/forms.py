from django import forms
from learning.models import ExerciseFile

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