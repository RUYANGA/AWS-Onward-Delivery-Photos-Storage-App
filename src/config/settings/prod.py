"""Production: ECS Fargate behind CloudFront, AWS WAF and the ALB."""

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import env

DEBUG = False

# Every task must sign sessions with the same key (Secrets Manager, injected by ECS).
SECRET_KEY = env("SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY is not set. In AWS it is injected from Secrets Manager.")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)

# CloudFront sends the ALB's hostname as Host, so the browser's Origin
# (https://<id>.cloudfront.net) must be trusted explicitly. The CSRF token still applies.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["https://*.cloudfront.net"])
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"

# CloudFront redirects to HTTPS and sends HSTS (infra: templates/edge.yaml). Doing either
# here would loop, because CloudFront reaches the ALB over HTTP.
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]
