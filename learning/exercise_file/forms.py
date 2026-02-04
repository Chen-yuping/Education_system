from django import forms
from ..models import ExerciseFile


class ExerciseFileForm(forms.ModelForm):
    class Meta:
        model = ExerciseFile
        fields = ['subject', 'file']
        widgets = {
            'file': forms.FileInput(attrs={'accept': '.txt,.pdf,.doc,.docx,.xls,.xlsx'})
        }