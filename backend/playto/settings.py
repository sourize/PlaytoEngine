import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY — always set these via environment variables in production
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# Comma-separated list: "localhost,yourdomain.com"
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'corsheaders',
    'merchants',
    'payouts',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
]

# In production set CORS_ALLOW_ALL_ORIGINS=False and list specific origins
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'True') == 'True'
CORS_ALLOWED_ORIGINS = [
    o for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o
]

ROOT_URLCONF = 'playto.urls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'playto'),
        'USER': os.environ.get('DB_USER', 'playto'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'playto'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Celery
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULE = {
    'retry-stuck-payouts': {
        'task': 'payouts.tasks.retry_stuck_payouts',
        'schedule': 15.0,
    },
}

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Static files (needed for production / collectstatic)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
