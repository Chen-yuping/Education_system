from django import forms
from .models import Exercise, KnowledgePoint, QMatrix, Subject

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