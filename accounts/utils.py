from django.contrib.auth import authenticate
from .models import User


def validate_user_login(username, password, user_type):
    """
    验证用户登录信息
    返回: (is_valid, error_message, user_object)
    """
    # 基础验证
    if not username or not password or not user_type:
        return False, "请填写所有必填字段", None

    # 验证用户是否存在
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return False, "用户不存在，请检查用户名或注册新账号", None

    # 验证密码
    if not user.check_password(password):
        return False, "密码错误，请重试", None

    # 验证身份类型
    if user.user_type != user_type:
        user_type_display = dict(User.USER_TYPE_CHOICES).get(user_type, user_type)
        return False, f"该账号不是{user_type_display}身份", None

    # 验证用户是否激活
    if not user.is_active:
        return False, "该账号已被禁用，请联系管理员", None

    # 使用 Django 的 authenticate 进行最终验证
    auth_user = authenticate(username=username, password=password)
    if not auth_user:
        return False, "认证失败，请重试", None

    return True, "验证成功", user


def get_user_statistics():
    """获取用户统计信息"""
    total_users = User.objects.count()
    student_count = User.objects.filter(user_type='student').count()
    teacher_count = User.objects.filter(user_type='teacher').count()
    active_users = User.objects.filter(is_active=True).count()

    return {
        'total_users': total_users,
        'student_count': student_count,
        'teacher_count': teacher_count,
        'active_users': active_users,
    }