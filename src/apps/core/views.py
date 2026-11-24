from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .health import liveness, readiness


@require_safe
def healthz(request):
    # Normally answered by HealthCheckMiddleware; kept so the route also exists in the URLconf.
    payload, status = liveness()
    return JsonResponse(payload, status=status)


@require_safe
def readyz(request):
    payload, status = readiness()
    return JsonResponse(payload, status=status)


@require_safe
def about(request):
    return render(request, "core/about.html")


def _error(request, code, message):
    return render(request, "core/error.html", {"code": code, "message": message}, status=code)


def permission_denied(request, exception=None):
    return _error(request, 403, "Only administrators can do this. Viewing photos is open to everyone.")


def page_not_found(request, exception=None):
    return _error(request, 404, "There's no photo at this address. It may have been deleted.")


def server_error(request):
    return _error(request, 500, "Something went wrong on our side. Try again in a moment.")


def csrf_failure(request, reason=""):
    return _error(request, 403, "This form expired. Go back, reload the page and try again.")
