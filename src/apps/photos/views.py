import logging
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.accounts.activity import Action, photo_subject, record
from apps.accounts.permissions import actor_name, permission_required

from .forms import PhotoEditForm, PhotoUploadForm
from .models import Photo, PhotoChange
from .services.editing import EditConflict, NewImage, apply_edit
from .services.storage import get_photo_store

log = logging.getLogger(__name__)

NOTICES = {
    "uploaded": "Photo uploaded. It is stored and replicated as delivery evidence.",
    "deleted": "Photo moved to Deleted photos. You can restore it from there.",
    "restored": "Photo restored to the gallery.",
    "purged": "Photo deleted permanently, with its files.",
    "updated": "Changes saved. The previous details are kept in the change history.",
    "signed-in": "You're signed in. You can now upload and manage photos.",
    "signed-out": "You're signed out.",
}
ADD, CHANGE, DELETE = "photos.add_photo", "photos.change_photo", "photos.delete_photo"
PURGE = "photos.purge_photo"  # delete permanently: administrators only
CONFLICT_MESSAGE = ("Someone else changed this photo while you were editing. The latest details are shown below; "
                    "make your change again.")
def delivery_reference_for(photo_id: uuid.UUID, when) -> str:
    """The app assigns each photo its reference, e.g. ONW-2026-3F9A1C (year + start of the photo id)."""
    return f"ONW-{when:%Y}-{photo_id.hex[:6].upper()}"


MEDIA_KEY_RE = re.compile(r"^(originals|thumbnails)/\d{4}/\d{2}/[0-9a-f\-]{36}\.(jpg|png|webp)$")


def _see_other(url: str) -> HttpResponse:
    response = HttpResponse(status=303)
    response["Location"] = url
    return response


def _gallery_with_notice(notice: str) -> HttpResponse:
    return _see_other(f"{reverse('photos:gallery')}?notice={notice}")


def _search(photos, query: str):
    if not query:
        return photos
    return photos.filter(
        Q(delivery_reference__icontains=query)
        | Q(title__icontains=query)
        | Q(delivery_city__icontains=query)
        | Q(merchant_name__icontains=query)
    )


def _dashboard_stats(user) -> dict:
    live = Photo.objects.filter(deleted_at__isnull=True)
    week_ago = timezone.now() - timedelta(days=7)
    stats = {
        "live": live.count(),
        "mine": live.filter(uploader=user).count(),
        "mine_this_week": live.filter(uploader=user, created_at__gte=week_ago).count(),
        "my_edits": PhotoChange.objects.filter(changed_by_user=user).count(),
    }
    if user.has_perm(DELETE):
        stats["deleted"] = Photo.objects.filter(deleted_at__isnull=False).count()
    if user.has_perm("auth.view_user"):
        stats.update({
            "edited": live.filter(revision__gt=1).count(),
            "this_week": live.filter(created_at__gte=week_ago).count(),
            "storage_mb": (Photo.objects.aggregate(total=Sum("size_bytes"))["total"] or 0) / 1_048_576,
            "users": get_user_model().objects.filter(is_active=True).count(),
        })
    return stats


def _write_sidecar(photo: Photo) -> None:
    try:
        get_photo_store().put_sidecar(photo.metadata_key, photo.sidecar())
    except Exception:  # the row is committed; a missing sidecar is logged and can be regenerated
        log.exception("sidecar write failed", extra={"photo_id": str(photo.id)})


@require_safe
def gallery(request):
    query = (request.GET.get("q") or "").strip()[:64]
    photos = _search(Photo.objects.filter(deleted_at__isnull=True), query)
    page = Paginator(photos.order_by("-created_at"), settings.PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "photos/gallery.html", {
        "page_obj": page,
        "photos": page.object_list,
        "total": page.paginator.count,
        "query": query,
        "notice": NOTICES.get(request.GET.get("notice", "")),
    })


@require_http_methods(["GET", "HEAD", "POST"])
@permission_required(ADD)
def upload(request):
    form = PhotoUploadForm(request.POST or None, request.FILES or None)
    context = {"form": form, "max_mb": settings.MAX_UPLOAD_MB}
    if request.method != "POST":
        return render(request, "photos/upload.html", context)
    if not form.is_valid():
        return render(request, "photos/upload.html", context, status=400)

    data, processed, details = form.photo_bytes, form.processed, form.cleaned_data
    photo_id = uuid.uuid4()
    now = timezone.now()
    partition = f"{now:%Y/%m}"
    photo = Photo(
        id=photo_id,
        title=details["title"],
        description=details["description"],
        delivery_reference=delivery_reference_for(photo_id, now),
        merchant_name=details["merchant_name"] or None,
        rider_name=details["rider_name"] or None,
        delivery_city=details["delivery_city"] or None,
        captured_at=details["captured_at"],
        s3_key=f"media/originals/{partition}/{photo_id}.{processed.extension}",
        thumbnail_key=f"media/thumbnails/{partition}/{photo_id}.webp",
        metadata_key=f"meta/{partition}/{photo_id}.json",
        sha256=processed.sha256,
        content_type=processed.content_type,
        size_bytes=len(data),
        width=processed.width,
        height=processed.height,
        created_at=now,
        uploaded_by=actor_name(request.user),
        uploader=request.user,
    )

    # Evidence first: a row is only created once the photo is safely in S3.
    store = get_photo_store()
    photo.s3_version_id = store.put_image(photo.s3_key, data, processed.content_type, processed.sha256)
    store.put_image(photo.thumbnail_key, processed.thumbnail, "image/webp")
    photo.save(force_insert=True)
    _write_sidecar(photo)
    record(request, Action.UPLOADED, photo=photo)
    log.info("photo uploaded", extra={"photo_id": str(photo_id), "bytes": len(data)})
    return _gallery_with_notice("uploaded")


@require_safe
def detail(request, photo_id):
    # Deleted photos stay viewable by administrators: they are still evidence. Viewers only see live
    # photos, and the change history (reasons, earlier photos) is for administrators.
    photo = get_object_or_404(Photo, pk=photo_id)
    if photo.deleted_at and not request.user.has_perm(DELETE):
        raise Http404
    return render(request, "photos/detail.html", {
        "photo": photo,
        "changes": photo.changes.all() if request.user.has_perm(CHANGE) else [],
        "notice": NOTICES.get(request.GET.get("notice", "")),
    })


@require_http_methods(["GET", "HEAD", "POST"])
@permission_required(CHANGE)
def edit(request, photo_id):
    # Only live photos can be edited; a deleted photo has to be restored first.
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=True)
    form = PhotoEditForm(request.POST or None, request.FILES or None, photo=photo)
    context = {"photo": photo, "form": form, "max_mb": settings.MAX_UPLOAD_MB}
    if request.method != "POST":
        return render(request, "photos/edit.html", context)
    if not form.is_valid():
        return render(request, "photos/edit.html", context, status=400)

    image = NewImage(form.photo_bytes, form.processed) if form.processed else None
    try:
        apply_edit(photo.id, form.cleaned_data["revision"], form.details(), form.cleaned_data["reason"], image,
                   actor=actor_name(request.user), user=request.user)
    except EditConflict:
        latest = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=True)
        return render(request, "photos/edit.html", {
            "photo": latest,
            "form": PhotoEditForm(photo=latest),
            "max_mb": settings.MAX_UPLOAD_MB,
            "conflict": CONFLICT_MESSAGE,
        }, status=409)
    edited = Photo.objects.get(pk=photo_id)
    _write_sidecar(edited)
    record(request, Action.EDITED, photo=edited,
           detail=("Photo replaced. " if image else "") + form.cleaned_data["reason"].strip())
    return _see_other(f"{reverse('photos:detail', args=[photo_id])}?notice=updated")


@require_POST
@permission_required(DELETE)
def delete(request, photo_id):
    # Soft delete: nothing is removed from S3.
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=True)
    photo.deleted_at = timezone.now()
    photo.deleted_by = actor_name(request.user)
    photo.save(update_fields=["deleted_at", "deleted_by"])
    _write_sidecar(photo)
    record(request, Action.DELETED, photo=photo)
    return _see_other(f"{reverse('photos:dashboard')}?notice=deleted")


@require_POST
@permission_required(DELETE)
def restore(request, photo_id):
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=False)
    photo.deleted_at = None
    photo.deleted_by = ""
    photo.save(update_fields=["deleted_at", "deleted_by"])
    _write_sidecar(photo)
    record(request, Action.RESTORED, photo=photo)
    return _see_other(f"{reverse('photos:deleted')}?notice=restored")


@require_POST
@permission_required(PURGE)
def purge(request, photo_id):
    # Only photos already in Deleted photos. Removing the row also removes the photo, thumbnail
    # and sidecar from S3 (signals.py); the replica in the recovery Region keeps its copy.
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=False)
    subject = photo_subject(photo)
    photo.delete()
    record(request, Action.PURGED, subject=subject)
    log.info("photo deleted permanently", extra={"photo_id": str(photo_id), "user_id": request.user.pk})
    return _see_other(f"{reverse('photos:deleted')}?notice=purged")


@require_safe
@permission_required(CHANGE)
def dashboard(request):
    """Administrators manage photos here; the gallery and photo pages only show them."""
    query = (request.GET.get("q") or "").strip()[:64]
    photos = _search(Photo.objects.filter(deleted_at__isnull=True), query)
    page = Paginator(photos.order_by("-created_at"), 25).get_page(request.GET.get("page"))
    return render(request, "photos/dashboard.html", {
        "tab": "live",
        "stats": _dashboard_stats(request.user),
        "page_obj": page,
        "photos": page.object_list,
        "total": page.paginator.count,
        "query": query,
        "notice": NOTICES.get(request.GET.get("notice", "")),
    })


@require_safe
@permission_required(DELETE)
def deleted(request):
    photos = Photo.objects.filter(deleted_at__isnull=False).order_by("-deleted_at")[:200]
    return render(request, "photos/deleted.html", {
        "tab": "deleted",
        "stats": _dashboard_stats(request.user),
        "photos": photos,
        "notice": NOTICES.get(request.GET.get("notice", "")),
    })


@require_safe
def media(request, subkey):
    """Local development only: in AWS, CloudFront serves /media/* straight from S3 (OAC)."""
    if not MEDIA_KEY_RE.match(subkey):
        raise Http404
    try:
        chunks, content_type, length = get_photo_store().stream(f"media/{subkey}")
    except Exception as exc:
        raise Http404 from exc
    response = StreamingHttpResponse(chunks, content_type=content_type)
    if length is not None:
        response["Content-Length"] = str(length)
    response["Cache-Control"] = "private, max-age=3600"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response
