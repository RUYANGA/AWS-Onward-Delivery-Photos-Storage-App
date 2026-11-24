import logging

from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from . import throttle
from .forms import SignInForm, normalise_email

log = logging.getLogger(__name__)

LOCKED_MESSAGE = "Too many failed sign-in attempts. Wait 15 minutes, then try again."


def _safe_next(request) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts=None, require_https=False) \
            and target.startswith("/") and not target.startswith(reverse("accounts:sign-in")):
        return target
    return ""


@sensitive_post_parameters("password")
@csrf_protect
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def sign_in(request):
    next_url = _safe_next(request)
    if request.user.is_authenticated and request.method != "POST":
        return redirect(next_url or reverse("photos:gallery"))

    form = SignInForm(request, data=request.POST or None)
    context = {"form": form, "next": next_url}
    if request.method != "POST":
        return render(request, "accounts/sign_in.html", context)

    email = normalise_email(request.POST.get("username"))
    ip = throttle.client_ip(request)
    if throttle.is_locked(email, ip):
        log.warning("sign-in refused: too many failures", extra={"email": email, "ip": ip})
        return render(request, "accounts/sign_in.html", {**context, "locked": LOCKED_MESSAGE}, status=429)

    if not form.is_valid():
        if email:
            throttle.record_failure(email, ip)
        log.warning("sign-in failed", extra={"email": email, "ip": ip})
        return render(request, "accounts/sign_in.html", context, status=400)

    user = form.get_user()
    login(request, user)  # a new session key, so a planted session can't be reused
    throttle.clear(email)
    log.info("signed in", extra={"user_id": user.pk, "ip": ip})
    return redirect(next_url or f"{reverse('photos:gallery')}?notice=signed-in")


@require_POST
def sign_out(request):
    if request.user.is_authenticated:
        log.info("signed out", extra={"user_id": request.user.pk})
    logout(request)
    return redirect(f"{reverse('photos:gallery')}?notice=signed-out")
