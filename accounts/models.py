from django.contrib.auth.models import AbstractUser
from django.db import models

#用户表
class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('student', '学生'),
        ('teacher', '教师'),
        ('researcher', '科研者'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

#学生表
class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    grade = models.CharField(max_length=50, verbose_name="年级")
    school = models.CharField(max_length=100, verbose_name="学校", blank=True)

    class Meta:
        verbose_name = '学生档案'
        verbose_name_plural = '学生档案'

#老师表
class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=50, verbose_name="教学科目")
    school = models.CharField(max_length=100, verbose_name="学校", blank=True)

    class Meta:
        verbose_name = '教师档案'
        verbose_name_plural = '教师档案'

#研究员表
class ResearcherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=50, verbose_name="教学科目")


    class Meta:
        verbose_name = '研究员档案'
        verbose_name_plural = '研究员档案'