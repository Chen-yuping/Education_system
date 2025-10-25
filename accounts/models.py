from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('student', '学生'),
        ('teacher', '教师'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    grade = models.CharField(max_length=50, verbose_name="年级")
    school = models.CharField(max_length=100, verbose_name="学校", blank=True)

    class Meta:
        verbose_name = '学生档案'
        verbose_name_plural = '学生档案'


class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=50, verbose_name="教学科目")
    school = models.CharField(max_length=100, verbose_name="学校", blank=True)

    class Meta:
        verbose_name = '教师档案'
        verbose_name_plural = '教师档案'