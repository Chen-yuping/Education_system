import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-your-secret-key-here'

DEBUG = True

# ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '101.201.178.241',  # 添加这一行
    'aikgedu.com.cn',   # 添加这一行
    '10.13.91.164'  # 你的内网IP
]

# CSRF 设置
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'https://1128czrv84069.vicp.fun',
    'http://1128czrv84069.vicp.fun',
    'https://11496bmpu5109.vicp.fun',
    'http://11496bmpu5109.vicp.fun',
]

CSRF_FAILURE_VIEW = 'edu_system.views.csrf_failure'
CSRF_COOKIE_SECURE = False  # 开发环境下设为 False
CSRF_COOKIE_HTTPONLY = False  # 允许 JavaScript 访问

# 会话设置
SESSION_COOKIE_SECURE = False  # 开发环境下设为 False
SESSION_COOKIE_HTTPONLY = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'learning',
    'learning.diagnosis',

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'edu_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # 添加项目级模板目录
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
WSGI_APPLICATION = 'edu_system.wsgi.application'

# MySQL 数据库配置
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'edu_diagnosis',      # 数据库名称
        'USER': 'edu_diagnosis',    # MySQL 用户名
        'PASSWORD': 'zbKfBnHZTzdP4CbH',  # MySQL 密码
        'HOST': '101.201.178.241',          # 数据库主机，如果是本地就是 localhost
        'PORT': '3306',               # MySQL 端口，默认是 3306
        'OPTIONS': {
            'charset': 'utf8mb4',     # 支持 emoji 等特殊字符
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

# 认证后端
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_REDIRECT_URL = '/learning/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
# 如果你使用 pymysql 而不是 mysqlclient，需要添加以下代码
# try:
#     import pymysql
#     pymysql.install_as_MySQLdb()
# except ImportError:
#     pass
