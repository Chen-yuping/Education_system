# 创建一个脚本 create_models.py 在项目根目录
import os
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
django.setup()

from django.contrib.auth import get_user_model
from learning.models import DiagnosisModel

User = get_user_model()
user = User.objects.first()

if user:
    DiagnosisModel.objects.create(
        name="NCD",
        description="基于题目正确率的统计诊断",
        is_active=True,
        created_by=user
    )
    print("模型创建成功")
else:
    print("没有找到用户，请先创建用户")