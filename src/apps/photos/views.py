import logging
import re
import uuid

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .forms import PhotoUploadForm
from .models import Photo
from .services.storage import get_photo_store

log = logging.getLogger(__name__)

NOTICES = {
    "uploaded": "Photo uploaded. It is stored and replicated as delivery evidence.",
    "deleted": "Photo moved to Deleted photos. You can restore it from there.",
    "restored": "Photo restored to the gallery.",
    "purged": "Photo deleted permanently, with its files.",
}
MEDIA_KEY_RE = re.compile(r"^(originals|thumbnails)/\d{4}/\d{2}/[0-9a-f\-]{36}\.(jpg|png|webp)$")


def _see_other(url: str) -> HttpResponse:
    response = HttpResponse(status=303)
    response["Location"] = url
    return response


def _gallery_with_notice(notice: str) -> HttpResponse:
    return _see_other(f"{reverse('photos:gallery')}?notice={notice}")


def _write_sidecar(photo: Photo) -> None:
    try:
        get_photo_store().put_sidecar(photo.metadata_key, photo.sidecar())
    except Exception:  # the row is committed; a missing sidecar is logged and can be regenerated
        log.exception("sidecar write failed", extra={"photo_id": str(photo.id)})


@require_safe
def gallery(request):
    query = (request.GET.get("q") or "").strip()[:64]
    photos = Photo.objects.filter(deleted_at__isnull=True)
    if query:
        photos = photos.filter(
            Q(delivery_reference__icontains=query)
            | Q(title__icontains=query)
            | Q(delivery_city__icontains=query)
            | Q(merchant_name__icontains=query)
        )
    page = Paginator(photos.order_by("-created_at"), settings.PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "photos/gallery.html", {
        "page_obj": page,
        "photos": page.object_list,
        "total": page.paginator.count,
        "query": query,
        "notice": NOTICES.get(request.GET.get("notice", "")),
    })


@require_http_methods(["GET", "HEAD", "POST"])
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
        delivery_reference=details["delivery_reference"],
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
    )

    # Evidence first: a row is only created once the photo is safely in S3.
    store = get_photo_store()
    photo.s3_version_id = store.put_image(photo.s3_key, data, processed.content_type, processed.sha256)
    store.put_image(photo.thumbnail_key, processed.thumbnail, "image/webp")
    photo.save(force_insert=True)
    _write_sidecar(photo)
    log.info("photo uploaded", extra={"photo_id": str(photo_id), "bytes": len(data)})
    return _gallery_with_notice("uploaded")


@require_safe
def detail(request, photo_id):
    # Deleted photos stay viewable here: they are still evidence.
    return render(request, "photos/detail.html", {"photo": get_object_or_404(Photo, pk=photo_id)})


@require_POST
def delete(request, photo_id):
    # Soft delete: nothing is removed from S3.
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=True)
    photo.deleted_at = timezone.now()
    photo.save(update_fields=["deleted_at"])
    _write_sidecar(photo)
    return _gallery_with_notice("deleted")


@require_POST
def restore(request, photo_id):
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=False)
    photo.deleted_at = None
    photo.save(update_fields=["deleted_at"])
    _write_sidecar(photo)
    return _gallery_with_notice("restored")


@require_POST
def purge(request, photo_id):
    # Only photos already in Deleted photos. Removing the row also removes the photo, thumbnail
    # and sidecar from S3 (signals.py); the replica in the recovery Region keeps its copy.
    photo = get_object_or_404(Photo, pk=photo_id, deleted_at__isnull=False)
    photo.delete()
    log.info("photo deleted permanently", extra={"photo_id": str(photo_id)})
    return _see_other(f"{reverse('photos:deleted')}?notice=purged")


@require_safe
def deleted(request):
    photos = Photo.objects.filter(deleted_at__isnull=False).order_by("-deleted_at")[:200]
    return render(request, "photos/deleted.html", {
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
