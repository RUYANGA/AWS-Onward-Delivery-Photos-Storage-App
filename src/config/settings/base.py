"""Settings shared by every environment.

All values come from environment variables. On ECS they are injected at task start from
SSM Parameter Store (/onward/<env>/app/*) and, for DB_USERNAME / DB_PASSWORD, from the
RDS-managed secret. The root filesystem is read-only; scratch files go to TMPDIR (/dev/shm).
"""

from pathlib import Path

import environ
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # src/
ROOT_DIR = BASE_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
    # Tasks are only reachable through CloudFront -> WAF -> ALB, and ALB health checks
    # use the task's private IP, so the Host header is not restricted.
    ALLOWED_HOSTS=(list, ["*"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(ROOT_DIR / ".env")

# Nothing is signed (no sessions, no login), so a per-process key is safe.
SECRET_KEY = env("SECRET_KEY", default=None) or get_random_secret_key()
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

STUDENT_NAME = env("STUDENT_NAME", default="Student name not set")
LAB_NAME = env("LAB_NAME", default="Storing and Serving Delivery Photos for Onward Logistics")
APP_ENV = env("APP_ENV", default="local")
APP_VERSION = env("APP_VERSION", default="dev")  # git SHA, baked into the image at build time

PHOTO_BUCKET = env("PHOTO_BUCKET", default="")
AWS_REGION = env("AWS_REGION", default=env("AWS_DEFAULT_REGION", default="eu-west-1"))
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default=None) or None  # LocalStack only
S3_STORAGE_CLASS = env("S3_STORAGE_CLASS", default="INTELLIGENT_TIERING")
MAX_UPLOAD_MB = env.int("MAX_UPLOAD_MB", default=15)
PAGE_SIZE = 24
THUMBNAIL_PX = 480

# Keep uploads in memory so nothing is spooled to disk (read-only root filesystem).
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "apps.core",
    "apps.photos",
]

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",  # first: answers the ALB before host checks
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.UploadSizeLimitMiddleware",  # before CSRF, which reads the body
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
                "apps.core.context_processors.lab",
            ],
        },
    },
]

# DATABASE_URL for local runs; discrete DB_* variables on ECS.
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("DB_HOST", default=""),
            "PORT": env("DB_PORT", default="5432"),
            "NAME": env("DB_NAME", default="photos"),
            "USER": env("DB_USERNAME", default=""),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "OPTIONS": {"sslmode": env("DB_SSLMODE", default="require")},
        }
    }
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # reconnect cleanly after a Multi-AZ failover
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# Collected at build time (read-only filesystem); CloudFront caches /static/*.
STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_KEEP_ONLY_HASHED_FILES = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
