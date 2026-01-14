from django.contrib.auth.forms import AuthenticationForm
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import User

#用户登录
class UserLoginForm(AuthenticationForm):
    USER_TYPE_CHOICES = [
        ('', '选择身份类型'),
        ('student', '学生'),
        ('teacher', '教师'),
        ('researcher', '研究员'),
    ]

    user_type = forms.ChoiceField(
        choices=USER_TYPE_CHOICES,
        required=True,
        label="身份类型",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_user_type'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'password', 'user_type']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '请输入用户名',
            'id': 'id_username'
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '请输入密码',
            'id': 'id_password'
        })

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        user_type = cleaned_data.get('user_type')

        if username and password and user_type:
            # 验证用户是否存在
            try:
                user = User.objects.get(username=username)

                # 验证密码
                if not user.check_password(password):
                    raise forms.ValidationError("密码错误，请重试")

                # 验证身份类型
                if user.user_type != user_type:
                    raise forms.ValidationError(f"该账号不是{self.get_user_type_display(user_type)}身份")

                # 验证用户是否激活
                if not user.is_active:
                    raise forms.ValidationError("该账号已被禁用，请联系管理员")

                # 将用户对象添加到cleaned_data中供视图使用
                cleaned_data['user'] = user

            except User.DoesNotExist:
                raise forms.ValidationError("用户不存在，请检查用户名或注册新账号")

        return cleaned_data

    def get_user_type_display(self, user_type):
        """获取身份类型的显示名称"""
        for choice in self.USER_TYPE_CHOICES:
            if choice[0] == user_type:
                return choice[1]
        return user_type


#用户注册
class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': '请输入您的邮箱地址',
            'autocomplete': 'email'
        })
    )
    user_type = forms.ChoiceField(
        choices=User.USER_TYPE_CHOICES,
        label="身份类型",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_user_type'
        })
    )
    grade = forms.CharField(
        max_length=50,
        required=False,
        label="年级",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '例如：高一、高三',
            'id': 'id_grade'
        })
    )
    subject = forms.CharField(
        max_length=50,
        required=False,
        label="教学科目",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '例如：数学、英语',
            'id': 'id_subject'
        })
    )
    school = forms.CharField(
        max_length=100,
        required=False,
        label="学校",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '请输入您的学校名称'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'user_type', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '请输入用户名（用于登录）',
                'autocomplete': 'username'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 为密码字段添加样式
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '请输入密码（至少8个字符）',
            'autocomplete': 'new-password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '请再次输入密码',
            'autocomplete': 'new-password'
        })

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise ValidationError('该用户名已被使用，请选择其他用户名。')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('该邮箱已被注册，请使用其他邮箱。')
        return email

    def clean(self):
        cleaned_data = super().clean()
        user_type = cleaned_data.get('user_type')

        if user_type == 'student' and not cleaned_data.get('grade'):
            self.add_error('grade', '学生必须填写年级')
        elif user_type == 'teacher' and not cleaned_data.get('subject'):
            self.add_error('subject', '教师必须填写教学科目')

        return cleaned_data