"""Local development."""

import warnings

from .base import *

warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")  # no collectstatic locally

DEBUG = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
