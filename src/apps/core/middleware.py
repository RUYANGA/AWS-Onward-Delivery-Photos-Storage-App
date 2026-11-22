from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from .health import LIVENESS_PATH, liveness

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)


class HealthCheckMiddleware:
    """Answer the ALB health check before host validation, the database or any other middleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == LIVENESS_PATH and request.method in ("GET", "HEAD"):
            payload, status = liveness()
            return JsonResponse(payload, status=status)
        return self.get_response(request)


class UploadSizeLimitMiddleware:
    """Refuse oversized uploads from Content-Length, before the body is read into memory."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = settings.MAX_UPLOAD_MB * 1024 * 1024 + 64 * 1024  # allow for multipart overhead
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > limit:
            message = f"That file is larger than {settings.MAX_UPLOAD_MB} MB. Choose a smaller photo."
            return render(request, "core/error.html", {"code": 413, "message": message}, status=413)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response
