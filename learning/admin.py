from django.contrib import admin
from .models import ExerciseFile, Subject, Dataset, DiagnosisModel

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



@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ['name', 'student_info', 'exercise_info', 'knowledge_relation', 'order', 'created_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['name', 'description']
    ordering = ['order', 'name']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'order')
        }),
        ('数据集特征', {
            'fields': ('student_info', 'exercise_info', 'knowledge_relation'),
            'description': '填写 True/False 或文本描述（如 "masked text", "tree", "prerequisite" 等）'
        }),
        ('链接信息', {
            'fields': ('doc_link', 'download_link', 'paper_link')
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(DiagnosisModel)
class DiagnosisModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'created_by']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('链接信息', {
            'fields': ('paper_link',)
        }),
        ('元数据', {
            'fields': ('created_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )
