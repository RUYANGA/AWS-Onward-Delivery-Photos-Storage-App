import logging

from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from . import throttle
from .activity import Action, record
from .forms import ChangePasswordForm, ProfileForm, SignInForm, UserForm, normalise_email
from .models import Activity
from .permissions import permission_required
from .roles import editors_group, split_name

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
            known = get_user_model().objects.filter(username=email).first()
            if known is not None:  # failed attempts on a real account appear in its activity
                record(request, Action.SIGN_IN_FAILED, user=known)
        log.warning("sign-in failed", extra={"email": email, "ip": ip})
        return render(request, "accounts/sign_in.html", context, status=400)

    user = form.get_user()
    login(request, user)  # a new session key, so a planted session can't be reused
    throttle.clear(email)
    record(request, Action.SIGNED_IN, user=user)
    log.info("signed in", extra={"user_id": user.pk, "ip": ip})
    return redirect(next_url or f"{reverse('photos:dashboard')}?notice=signed-in")


@require_POST
def sign_out(request):
    if request.user.is_authenticated:
        log.info("signed out", extra={"user_id": request.user.pk})
        record(request, Action.SIGNED_OUT)
    logout(request)
    return redirect(f"{reverse('photos:gallery')}?notice=signed-out")


# ---------------------------------------------------------------------------------------------
# Users (administrators only). Administrators are managed in AWS (ensure_admin), so only editors
# are added, changed or deleted here.
# ---------------------------------------------------------------------------------------------
USER_NOTICES = {
    "user-added": "User added. They can sign in with their email address and the password you set.",
    "user-updated": "User updated.",
    "user-deleted": "User deleted. Photos they uploaded or edited keep their name in the record.",
}


def _describe_update(before, account, password_reset: bool) -> str:
    name, email, active = before
    parts = []
    if name != account.get_full_name():
        parts.append(f"name “{name}” → “{account.get_full_name()}”")
    if email != account.email:
        parts.append(f"email {email} → {account.email}")
    if active != account.is_active:
        parts.append("account enabled" if account.is_active else "account disabled")
    if password_reset:
        parts.append("password reset")
    return ("Changed " + ", ".join(parts)) if parts else "No changes"


def _editor_or_404(pk):
    return get_object_or_404(get_user_model(), pk=pk, is_superuser=False)


@require_http_methods(["GET", "HEAD"])
@permission_required("auth.view_user")
def users(request):
    query = (request.GET.get("q") or "").strip()[:64]
    accounts = get_user_model().objects.annotate(uploads=Count("uploaded_photos", distinct=True),
                                                 edits=Count("photo_changes", distinct=True))
    if query:
        accounts = accounts.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query)
                                   | Q(email__icontains=query))
    page = Paginator(accounts.order_by("-is_superuser", "first_name", "last_name", "email"), 25) \
        .get_page(request.GET.get("page"))
    return render(request, "accounts/users.html", {
        "page_obj": page, "accounts": page.object_list, "total": page.paginator.count, "query": query,
        "notice": USER_NOTICES.get(request.GET.get("notice", "")),
    })


ACTIVITY_FILTERS = (("all", "All activity"), ("photos", "Photos"), ("sign-ins", "Sign-ins"), ("account", "Account"))


@require_http_methods(["GET", "HEAD"])
@permission_required("auth.view_user")
def user_detail(request, pk):
    """A user's profile and everything they did, newest first (administrators only)."""
    account = get_object_or_404(get_user_model(), pk=pk)
    shown = request.GET.get("type", "all")
    shown = shown if shown in Activity.GROUPS else "all"
    events = Activity.objects.filter(Q(user=account) | Q(account=account)).select_related("photo")
    mine = Activity.objects.filter(user=account)
    stats = {
        "uploads": account.uploaded_photos.count(),
        "edits": account.photo_changes.count(),
        "deleted": mine.filter(action=Activity.Action.DELETED).count(),
        "restored": mine.filter(action=Activity.Action.RESTORED).count(),
        "sign_ins": mine.filter(action=Activity.Action.SIGNED_IN).count(),
        "failed": mine.filter(action=Activity.Action.SIGN_IN_FAILED).count(),
    }
    page = Paginator(events.filter(action__in=Activity.GROUPS[shown]) if shown != "all" else events, 20) \
        .get_page(request.GET.get("page"))
    return render(request, "accounts/user_detail.html", {
        "account": account,
        "stats": stats,
        "page_obj": page,
        "events": page.object_list,
        "filters": ACTIVITY_FILTERS,
        "shown": shown,
        "recent_uploads": account.uploaded_photos.filter(deleted_at__isnull=True).order_by("-created_at")[:6],
    })


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "HEAD", "POST"])
@permission_required("auth.add_user")
def user_add(request):
    form = UserForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            user.groups.add(editors_group())
            record(request, Action.USER_ADDED, account=user, subject=user.email)
            log.info("user added", extra={"user_id": request.user.pk, "account_id": user.pk})
            return redirect(f"{reverse('accounts:users')}?notice=user-added")
        return render(request, "accounts/user_form.html", {"form": form}, status=400)
    return render(request, "accounts/user_form.html", {"form": form})


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "HEAD", "POST"])
@permission_required("auth.change_user")
def user_edit(request, pk):
    account = _editor_or_404(pk)
    form = UserForm(request.POST or None, instance=account)
    context = {"form": form, "account": account}
    if request.method == "POST":
        if form.is_valid():
            before = (account.get_full_name(), account.email, account.is_active)
            form.save()
            editors_group().user_set.add(account)
            record(request, Action.USER_UPDATED, account=account, subject=account.email,
                   detail=_describe_update(before, account, bool(form.cleaned_data.get("password1"))))
            log.info("user updated", extra={"user_id": request.user.pk, "account_id": account.pk})
            return redirect(f"{reverse('accounts:users')}?notice=user-updated")
        return render(request, "accounts/user_form.html", context, status=400)
    return render(request, "accounts/user_form.html", context)


@require_POST
@permission_required("auth.delete_user")
def user_delete(request, pk):
    account = _editor_or_404(pk)
    if account.pk == request.user.pk:
        raise Http404
    log.info("user deleted", extra={"user_id": request.user.pk, "account_id": account.pk})
    record(request, Action.USER_DELETED, subject=f"{account.get_full_name()} · {account.email}".strip(" ·"))
    account.delete()  # their photos stay; uploader/changed_by_user become empty, the names remain
    return redirect(f"{reverse('accounts:users')}?notice=user-deleted")


# ---------------------------------------------------------------------------------------------
# My account: everyone may change their name and password, nothing else. The administrator's
# name and password come from AWS (ensure_admin), so they are shown read-only.
# ---------------------------------------------------------------------------------------------
ACCOUNT_NOTICES = {"name": "Your name is updated.", "password": "Your password is changed."}


@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def account(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:sign-in')}?next={reverse('accounts:account')}")
    user = request.user
    managed = user.is_superuser
    action = request.POST.get("action") if request.method == "POST" else None
    profile_form = ProfileForm(request.POST if action == "name" else None,
                               initial={"name": user.get_full_name()})
    password_form = ChangePasswordForm(user, request.POST if action == "password" else None)
    context = {"profile_form": profile_form, "password_form": password_form, "managed": managed,
               "notice": ACCOUNT_NOTICES.get(request.GET.get("notice", ""))}

    if action and managed:
        return render(request, "accounts/account.html", context, status=403)
    if action == "name":
        if profile_form.is_valid():
            old_name = user.get_full_name()
            user.first_name, user.last_name = split_name(profile_form.cleaned_data["name"])
            user.save(update_fields=["first_name", "last_name"])
            record(request, Action.NAME_CHANGED, detail=f"From “{old_name}” to “{user.get_full_name()}”")
            return redirect(f"{reverse('accounts:account')}?notice=name")
        return render(request, "accounts/account.html", context, status=400)
    if action == "password":
        if password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, password_form.user)  # stay signed in here only
            record(request, Action.PASSWORD_CHANGED)
            log.info("password changed", extra={"user_id": user.pk})
            return redirect(f"{reverse('accounts:account')}?notice=password")
        return render(request, "accounts/account.html", context, status=400)
    if action:
        return render(request, "accounts/account.html", context, status=400)
    return render(request, "accounts/account.html", context)
