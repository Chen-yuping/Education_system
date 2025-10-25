#!/usr/bin/env python
# 我想你帮我生成一个完整的Django项目。首先是一个登录页面，学生和老师可以实现登录。学生登录后可以做不同科目的习题，并记录下答题日志。学生可以查看答题诊断，并进行相关方面的学习。老师可以上传习题，构造习题知识点关系的Q矩阵，老师可以上传知识点。
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
