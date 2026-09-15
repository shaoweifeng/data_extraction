"""自动化测试配置：使用临时 SQLite，不依赖本地 MySQL / Redis。"""

import tempfile

from .settings import *  # noqa: F401,F403


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
PUBLIC_BASE_URL = 'http://testserver'
ACCOUNT_REGISTRATION_V2_ENABLED = False
ACCOUNT_RATE_LIMIT_ENABLED = False
REQUIRE_EMAIL_VERIFICATION = False
LOGGING = {}
FEEDBACK_UPLOAD_ROOT = tempfile.mkdtemp(prefix='data-extraction-feedback-tests-')
