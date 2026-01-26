from django.contrib import admin
from .models import ExerciseFile, Subject

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'description_preview', 'has_image']
    search_fields = ['name', 'description']
    fields = ['name', 'description', 'image', 'image_preview']
    readonly_fields = ['image_preview']
    
    def description_preview(self, obj):
        """显示描述的预览"""
        return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
    description_preview.short_description = '描述'
    
    def has_image(self, obj):
        """显示是否有图片"""
        return '✓' if obj.image else '✗'
    has_image.short_description = '有图片'
    
    def image_preview(self, obj):
        """显示图片预览"""
        if obj.image:
            return f'<img src="{obj.image.url}" width="200" height="150" />'
        return '暂无图片'
    image_preview.allow_tags = True
    image_preview.short_description = '图片预览'

@admin.register(ExerciseFile)
class ExerciseFileAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'teacher', 'subject', 'status', 'uploaded_at', 'exercise_count']
    list_filter = ['status', 'subject', 'uploaded_at']
    search_fields = ['original_filename', 'teacher__username']

