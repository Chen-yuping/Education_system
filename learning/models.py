from django.db import models
from accounts.models import User
import os
import uuid
from django.core.validators import FileExtensionValidator

#对应数据库learning_subject
class Subject(models.Model):
    name = models.CharField(max_length=100, verbose_name="科目名称")
    description = models.TextField(blank=True, verbose_name="科目描述")
    image = models.ImageField(upload_to='subjects/', blank=True, null=True, verbose_name="科目图片")

    class Meta:
        verbose_name = "科目"
        verbose_name_plural = "科目"

    def __str__(self):
        return self.name

# """教师授课关系（关联Subject=课程）"""
class TeacherSubject(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="teaching_subjects", verbose_name="教师")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="teachers", verbose_name="课程")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="添加时间")

    class Meta:
        verbose_name = "教师授课"
        verbose_name_plural = "教师授课"
        unique_together = ("teacher", "subject")  # 防止重复关联

    def __str__(self):
        return f"{self.teacher.username} - {self.subject.name}"

#"""学生选课关系（关联Subject=课程）"""
class StudentSubject(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrolled_subjects", verbose_name="学生")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="students", verbose_name="课程")
    enrolled_at = models.DateTimeField(auto_now_add=True, verbose_name="选课时间")

    class Meta:
        verbose_name = "学生选课"
        verbose_name_plural = "学生选课"
        unique_together = ("student", "subject")  # 防止重复选课

    def __str__(self):
        return f"{self.student.username} - {self.subject.name}"

#知识点
class KnowledgePoint(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    name = models.CharField(max_length=200, verbose_name="知识点名称")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='children', verbose_name="父知识点")
    similar_points = models.ManyToManyField('self', blank=True, symmetrical=True,
                                            verbose_name="相似知识点")
    class Meta:
        verbose_name = "知识点"
        verbose_name_plural = "知识点"

    def __str__(self):
        return f"{self.subject.name} - {self.name}"

#知识点关系图
class KnowledgeGraph(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    source = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, related_name='outgoing')
    target = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, related_name='incoming')

    class Meta:
        verbose_name = "知识点关系"
        verbose_name_plural = "知识点关系"
        unique_together = ('subject', 'source', 'target')

    def __str__(self):
        return f"{self.source.name} → {self.target.name}"

    def is_bidirectional(self):
        """检查是否是双向关系"""
        return KnowledgeGraph.objects.filter(
            subject=self.subject,
            source=self.target,
            target=self.source
        ).exists()

#习题
class Exercise(models.Model):

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    problemsets = models.CharField(max_length=200,default="", verbose_name="习题集ID")
    title = models.CharField(max_length=200, verbose_name="习题标题")
    content = models.TextField(verbose_name="习题内容")
    question_type = models.CharField(max_length=10, default='single', verbose_name="题型")
    creator = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="创建者",default=1)
    option_text = models.CharField(max_length=1000,verbose_name="选项内容",default=None)
    answer = models.CharField(max_length=500, verbose_name="答案",default=None)
    solution = models.TextField(blank=True, null=True, verbose_name="答案解析")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", null=True)
    
    class Meta:
        verbose_name = "习题"
        verbose_name_plural = "习题"

    def __str__(self):
        return self.title

#选项
class Choice(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='choices', verbose_name="所属习题")
    content = models.CharField(max_length=500, verbose_name="选项内容")
    is_correct = models.BooleanField(default=False, verbose_name="是否正确")
    order = models.IntegerField(default=0, verbose_name="选项顺序")

    class Meta:
        verbose_name = "选项"
        verbose_name_plural = "选项"
        ordering = ['order']

    def __str__(self):
        return f"{self.exercise.title} - 选项 {self.order}"

#Q矩阵
class QMatrix(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, verbose_name="习题")
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, verbose_name="知识点")
    weight = models.FloatField(default=1.0, verbose_name="权重")

    class Meta:
        verbose_name = "Q矩阵"
        verbose_name_plural = "Q矩阵"
        unique_together = ['exercise', 'knowledge_point']

    def __str__(self):
        return f"{self.exercise.title} - {self.knowledge_point.name}"

#回答记录
class AnswerLog(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, verbose_name="习题")
    selected_choices = models.ManyToManyField(Choice, blank=True, verbose_name="选择的选项")
    text_answer = models.TextField(blank=True, verbose_name="文本答案",default=None)
    is_correct = models.BooleanField(null=True, verbose_name="是否正确")
    time_spent = models.IntegerField(default=0, verbose_name="答题耗时(秒)")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目", null=True, blank=True)

    class Meta:
        verbose_name = "答题记录"
        verbose_name_plural = "答题记录"

    def save(self, *args, **kwargs):
        # 自动从关联的 exercise 获取 subject
        if self.exercise_id and not self.subject_id:
            self.subject = self.exercise.subject
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.username} - {self.exercise.title}"


# 添加算法models
class DiagnosisModel(models.Model):
    MODEL_CATEGORY_CHOICES = [
        ('probability', 'Probability'),
        ('nn', 'NN'),
        ('gnn', 'GNN'),
        ('llm', 'LLM'),
    ]
    
    name = models.CharField('模型名称', max_length=100)
    description = models.TextField('模型描述', blank=True)
    category = models.CharField('模型分类', max_length=20, choices=MODEL_CATEGORY_CHOICES, default='probability')
    is_active = models.BooleanField('是否启用', default=True)
    paper_link = models.URLField('论文链接', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        verbose_name = "诊断模型"
        verbose_name_plural = "诊断模型"
        ordering = ['id']

    def __str__(self):
        return self.name



#对应数据库learning_studentdiagnosis
class StudentDiagnosis(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生")
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, verbose_name="知识点")
    mastery_level = models.FloatField(default=0.0, verbose_name="掌握程度")
    diagnosis_model = models.ForeignKey(DiagnosisModel,default=1, on_delete=models.CASCADE, verbose_name="使用模型")
    last_practiced = models.DateTimeField(auto_now=True, verbose_name="最后练习时间")
    practice_count = models.IntegerField(default=0, verbose_name="练习次数")
    correct_count = models.IntegerField(default=0, verbose_name="正确次数")

    class Meta:
        verbose_name = "学生诊断"
        verbose_name_plural = "学生诊断"

    def __str__(self):
        return f"{self.student.username} - {self.knowledge_point.name}"

# 习题收藏模型
class ExerciseFavorite(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生", related_name='favorite_exercises')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, verbose_name="习题", related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="收藏时间")
    note = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "习题收藏"
        verbose_name_plural = "习题收藏"
        unique_together = ('student', 'exercise')  # 防止重复收藏
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.username} - {self.exercise.title}"

#对应数据库learning_exercisefile
def exercise_file_upload_path(instance, filename):
    """生成文件上传路径"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    return f'exercise_files/{instance.teacher.id}/{filename}'
class ExerciseFile(models.Model):
    FILE_STATUS = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('error', '处理失败'),
    ]

    FILE_TYPES = [
        ('txt', '文本文件'),
        ('pdf', 'PDF文件'),
        ('doc', 'Word文档'),
        ('docx', 'Word文档'),
        ('xls', 'Excel文件'),
        ('xlsx', 'Excel文件'),
    ]

    teacher = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="上传教师")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    file = models.FileField(
        upload_to=exercise_file_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx'])],
        verbose_name="习题文件"
    )
    original_filename = models.CharField(max_length=255, verbose_name="原始文件名")
    file_type = models.CharField(max_length=10, choices=FILE_TYPES, verbose_name="文件类型")
    status = models.CharField(max_length=20, choices=FILE_STATUS, default='pending', verbose_name="处理状态")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="处理完成时间")
    exercise_count = models.IntegerField(default=0, verbose_name="生成的习题数量")
    error_message = models.TextField(blank=True, verbose_name="错误信息")

    class Meta:
        verbose_name = "习题文件"
        verbose_name_plural = "习题文件"
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.teacher.username} - {self.original_filename}"

    def delete(self, *args, **kwargs):
        """删除模型实例时同时删除文件"""
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
        super().delete(*args, **kwargs)


# 数据集模型
class Dataset(models.Model):
    """公开数据集信息"""
    name = models.CharField(max_length=100, verbose_name="数据集名称", unique=True)
    description = models.TextField(blank=True, verbose_name="数据集描述")
    
    # 数据集特征
    student_info = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name="学生端信息",
        help_text="是否包含学生特征信息。可选值：True/False/文本描述"
    )
    exercise_info = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name="习题端信息",
        help_text="是否包含习题的文本信息。可选值：True/False/文本描述"
    )
    knowledge_relation = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name="知识点关系",
        help_text="是否包含知识点之间的关系。可选值：True/False/文本描述"
    )
    
    # 链接信息
    doc_link = models.URLField(blank=True, verbose_name="文档链接")
    download_link = models.URLField(blank=True, verbose_name="下载链接")
    paper_link = models.URLField(blank=True, verbose_name="论文链接")
    
    # 元数据
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    order = models.IntegerField(default=0, verbose_name="排序")
    
    class Meta:
        verbose_name = "数据集"
        verbose_name_plural = "数据集"
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.name
    
    def get_links(self):
        """获取所有链接"""
        links = []
        if self.doc_link:
            links.append({'type': 'doc', 'url': self.doc_link})
        if self.download_link:
            links.append({'type': 'download', 'url': self.download_link})
        if self.paper_link:
            links.append({'type': 'paper', 'url': self.paper_link})
        return links
    
    def get_student_info_display(self):
        """获取学生信息的显示值"""
        if self.student_info.lower() == 'true':
            return True
        elif self.student_info.lower() == 'false':
            return False
        else:
            return self.student_info
    
    def get_exercise_info_display(self):
        """获取习题信息的显示值"""
        if self.exercise_info.lower() == 'true':
            return True
        elif self.exercise_info.lower() == 'false':
            return False
        else:
            return self.exercise_info
    
    def get_knowledge_relation_display(self):
        """获取知识点关系的显示值"""
        if self.knowledge_relation.lower() == 'true':
            return True
        elif self.knowledge_relation.lower() == 'false':
            return False
        else:
            return self.knowledge_relation
