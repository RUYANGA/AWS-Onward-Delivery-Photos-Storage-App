"""Slow down password guessing without a shared cache: failed sign-ins are counted in the database.

An account is locked for LOCKOUT after MAX_PER_EMAIL failures within LOCKOUT, and an address after
MAX_PER_IP failures (guessing across many accounts). A successful sign-in clears the account's count.
"""

from datetime import timedelta
from ipaddress import ip_address

from django.utils import timezone

from .models import FailedSignIn

LOCKOUT = timedelta(minutes=15)
MAX_PER_EMAIL = 5
MAX_PER_IP = 20
KEEP_FOR = timedelta(days=1)


def client_ip(request) -> str | None:
    """The browser's address.

    In AWS the request passes CloudFront, which appends the viewer's address to X-Forwarded-For,
    then the ALB, which appends CloudFront's. So the viewer is the second-to-last entry; anything
    before it was sent by the client and can't be trusted. The ALB only accepts CloudFront
    (security group + WAF), so this holds. Locally there is no proxy: use REMOTE_ADDR.
    """
    forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
    candidate = forwarded[-2:][0] if forwarded else request.META.get("REMOTE_ADDR")
    try:
        return str(ip_address(candidate)) if candidate else None
    except ValueError:
        return None


def is_locked(email: str, ip: str | None) -> bool:
    since = timezone.now() - LOCKOUT
    recent = FailedSignIn.objects.filter(attempted_at__gte=since)
    if email and recent.filter(email=email).count() >= MAX_PER_EMAIL:
        return True
    return bool(ip) and recent.filter(ip_address=ip).count() >= MAX_PER_IP


def record_failure(email: str, ip: str | None) -> None:
    FailedSignIn.objects.create(email=email[:254], ip_address=ip)
    FailedSignIn.objects.filter(attempted_at__lt=timezone.now() - KEEP_FOR).delete()


def clear(email: str) -> None:
    FailedSignIn.objects.filter(email=email).delete()
