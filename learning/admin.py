from django.contrib import admin
from .models import ExerciseFile

@admin.register(ExerciseFile)
class ExerciseFileAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'teacher', 'subject', 'status', 'uploaded_at', 'exercise_count']
    list_filter = ['status', 'subject', 'uploaded_at']
    search_fields = ['original_filename', 'teacher__username']

