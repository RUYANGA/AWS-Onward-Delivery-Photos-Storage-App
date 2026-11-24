from functools import wraps
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def permission_required(perm: str):
    """Viewers are sent to sign in; signed-in accounts without ``perm`` get a 403.

    After signing in the user returns to the page they asked for. For a POST (a form on another
    page) there is no page to return to, so they land on the gallery.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                url = reverse("accounts:sign-in")
                if request.method in ("GET", "HEAD"):
                    url += "?" + urlencode({"next": request.get_full_path()})
                return redirect(url)
            if not request.user.has_perm(perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def actor_name(user) -> str:
    """How a user is named in the evidence record (history, sidecars)."""
    return (user.get_full_name() or user.email or user.get_username())[:150]
