"""Record what people do (accounts.models.Activity). Never lets a logging problem break the action."""

import logging

from .models import Activity
from .permissions import actor_name
from .throttle import client_ip

log = logging.getLogger(__name__)
Action = Activity.Action


def photo_subject(photo) -> str:
    return f"{photo.delivery_reference} · {photo.title}"[:255]


def record(request, action: str, *, user=None, photo=None, account=None, subject: str = "", detail: str = ""):
    user = user if user is not None else getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None
    try:
        Activity.objects.create(
            user=user, actor_name=actor_name(user) if user else "", action=action,
            photo=photo, account=account, subject=(subject or (photo_subject(photo) if photo else ""))[:255],
            detail=detail[:500], ip_address=client_ip(request) if request is not None else None,
        )
    except Exception:
        log.exception("activity not recorded", extra={"photo_id": str(photo.id) if photo else None})
