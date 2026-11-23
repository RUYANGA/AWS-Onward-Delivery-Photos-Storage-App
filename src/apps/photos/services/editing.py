"""Editing a photo's details or replacing the photo, without losing any evidence.

- Nothing is overwritten. A replacement photo is stored under new keys; the previous original and
  thumbnail stay in S3 and are recorded in the photo's change history with their checksum.
- Every edit is recorded (PhotoChange): when, why, and each detail's old and new value.
- Two people editing at once can't silently overwrite each other: the edit applies only if the photo
  is still at the revision the editor started from.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import Photo, PhotoChange
from .imaging import ProcessedImage
from .storage import get_photo_store

log = logging.getLogger(__name__)

LABELS = {
    "title": "Title",
    "description": "Description",
    "merchant_name": "Merchant",
    "rider_name": "Rider",
    "delivery_city": "City",
    "captured_at": "Time taken",
}


class EditConflict(Exception):
    """The photo changed (or was deleted) after the editor opened it."""


@dataclass(frozen=True)
class NewImage:
    data: bytes
    processed: ProcessedImage


def _display(field: str, value):
    if value in (None, ""):
        return None
    if field == "captured_at":
        return f"{value:%d %b %Y %H:%M} UTC"
    return value


def detail_changes(photo: Photo, details: dict) -> list[dict]:
    return [
        {"field": field, "label": LABELS[field],
         "from": _display(field, getattr(photo, field)), "to": _display(field, value)}
        for field, value in details.items()
        if getattr(photo, field) != value
    ]


def _store_replacement(photo: Photo, image: NewImage) -> dict:
    """Upload the new photo and thumbnail under new keys. Returns the new file fields."""
    file_id = uuid.uuid4()
    partition = f"{timezone.now():%Y/%m}"
    processed = image.processed
    fields = {
        "s3_key": f"media/originals/{partition}/{file_id}.{processed.extension}",
        "thumbnail_key": f"media/thumbnails/{partition}/{file_id}.webp",
        "sha256": processed.sha256,
        "content_type": processed.content_type,
        "size_bytes": len(image.data),
        "width": processed.width,
        "height": processed.height,
    }
    store = get_photo_store()
    fields["s3_version_id"] = store.put_image(fields["s3_key"], image.data, processed.content_type, processed.sha256)
    store.put_image(fields["thumbnail_key"], processed.thumbnail, "image/webp")
    return fields


def apply_edit(photo_id: uuid.UUID, expected_revision: int, details: dict, reason: str,
               image: NewImage | None = None) -> Photo:
    """Apply an edit and record it. Raises EditConflict if the photo moved on since the form was opened."""
    current = Photo.objects.filter(pk=photo_id, deleted_at__isnull=True).values_list("revision", flat=True).first()
    if current != expected_revision:
        raise EditConflict

    # Evidence first: the replacement is safely in S3 before any row points at it.
    new_files = _store_replacement(Photo.objects.get(pk=photo_id), image) if image else {}

    try:
        with transaction.atomic():
            photo = Photo.objects.select_for_update().get(pk=photo_id)
            if photo.deleted_at is not None or photo.revision != expected_revision:
                raise EditConflict

            change = PhotoChange(photo=photo, revision=photo.revision + 1, reason=reason.strip(),
                                 changes=detail_changes(photo, details))
            if new_files:
                change.previous_s3_key = photo.s3_key
                change.previous_s3_version_id = photo.s3_version_id
                change.previous_thumbnail_key = photo.thumbnail_key
                change.previous_sha256 = photo.sha256
                change.previous_content_type = photo.content_type
                change.previous_size_bytes = photo.size_bytes
                change.changes.append({"field": "photo", "label": "Photo",
                                       "from": photo.sha256, "to": new_files["sha256"]})

            for field, value in {**details, **new_files}.items():
                setattr(photo, field, value)
            photo.revision = change.revision
            photo.updated_at = change.changed_at
            photo.save()
            change.save()
    except BaseException:
        if new_files:  # nothing refers to the upload; remove it rather than leave an orphan
            try:
                get_photo_store().delete(new_files["s3_key"], new_files["thumbnail_key"])
            except Exception:
                log.exception("removing an unused replacement failed", extra={"photo_id": str(photo_id)})
        raise

    log.info("photo edited", extra={"photo_id": str(photo_id), "revision": photo.revision,
                                    "replaced_photo": bool(new_files)})
    return photo
