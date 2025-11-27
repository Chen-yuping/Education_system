from django.db import models
from accounts.models import User


class Subject(models.Model):
    name = models.CharField(max_length=100, verbose_name="科目名称")
    description = models.TextField(blank=True, verbose_name="科目描述")

    class Meta:
        verbose_name = "科目"
        verbose_name_plural = "科目"

    def __str__(self):
        return self.name


class KnowledgePoint(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    name = models.CharField(max_length=200, verbose_name="知识点名称")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='children', verbose_name="父知识点")

    class Meta:
        verbose_name = "知识点"
        verbose_name_plural = "知识点"

    def __str__(self):
        return f"{self.subject.name} - {self.name}"


class Exercise(models.Model):

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="所属科目")
    problemsets = models.CharField(max_length=200,default="", verbose_name="习题集ID")
    title = models.CharField(max_length=200, verbose_name="习题标题")
    content = models.TextField(verbose_name="习题内容")
    question_type = models.CharField(max_length=10, default='single', verbose_name="题型")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="创建者",default=1)


    class Meta:
        verbose_name = "习题"
        verbose_name_plural = "习题"

    def __str__(self):
        return self.title


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


class AnswerLog(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, verbose_name="习题")
    selected_choices = models.ManyToManyField(Choice, blank=True, verbose_name="选择的选项")
    text_answer = models.TextField(blank=True, verbose_name="文本答案")
    is_correct = models.BooleanField(null=True, verbose_name="是否正确")
    time_spent = models.IntegerField(default=0, verbose_name="答题耗时(秒)")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")

    class Meta:
        verbose_name = "答题记录"
        verbose_name_plural = "答题记录"

    def __str__(self):
        return f"{self.student.username} - {self.exercise.title}"


class StudentDiagnosis(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生")
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, verbose_name="知识点")
    mastery_level = models.FloatField(default=0.0, verbose_name="掌握程度")
    last_practiced = models.DateTimeField(auto_now=True, verbose_name="最后练习时间")
    practice_count = models.IntegerField(default=0, verbose_name="练习次数")
    correct_count = models.IntegerField(default=0, verbose_name="正确次数")

    class Meta:
        verbose_name = "学生诊断"
        verbose_name_plural = "学生诊断"
        unique_together = ['student', 'knowledge_point']

    def __str__(self):
        return f"{self.student.username} - {self.knowledge_point.name}"