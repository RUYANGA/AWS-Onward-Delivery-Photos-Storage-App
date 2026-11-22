"""Tests: in-memory SQLite and a moto-mocked S3 bucket."""

import warnings

from .base import *

warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")  # no collectstatic in tests

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

STUDENT_NAME = "Test Student"
APP_ENV = "test"
PHOTO_BUCKET = "onward-test-photos"
AWS_REGION = "eu-west-1"
MAX_UPLOAD_MB = 5
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
LOGGING = {"version": 1, "disable_existing_loggers": False}
