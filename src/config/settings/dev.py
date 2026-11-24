"""Local development."""

import warnings

from .base import *
from .base import env

warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")  # no collectstatic locally

DEBUG = True

# A fixed key so the dev server's reloads don't sign you out. Local only.
SECRET_KEY = env("SECRET_KEY", default="django-insecure-local-development-only")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
