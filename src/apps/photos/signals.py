"""When a photo's row is deleted from the database, its files are removed from S3 too,
including the earlier photos kept in its change history."""

import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Photo, PhotoChange
from .services.storage import get_photo_store

log = logging.getLogger(__name__)


def _delete_on_commit(keys: tuple, photo_id: str) -> None:
    def remove() -> None:
        try:
            get_photo_store().delete(*keys)
            log.info("photo files deleted from S3", extra={"photo_id": photo_id})
        except Exception:  # the row is already gone; leftover files are logged for cleanup
            log.exception("deleting photo files from S3 failed", extra={"photo_id": photo_id, "keys": keys})

    # Only once the delete is committed: a rolled-back delete keeps its files.
    transaction.on_commit(remove)


@receiver(post_delete, sender=Photo, dispatch_uid="photos.delete_files_from_s3")
def delete_files_from_s3(sender, instance: Photo, **kwargs) -> None:
    _delete_on_commit((instance.s3_key, instance.thumbnail_key, instance.metadata_key), str(instance.id))


@receiver(post_delete, sender=PhotoChange, dispatch_uid="photos.delete_replaced_files_from_s3")
def delete_replaced_files_from_s3(sender, instance: PhotoChange, **kwargs) -> None:
    # Runs when the photo is deleted permanently (its history is deleted with it).
    if instance.replaced_photo:
        _delete_on_commit((instance.previous_s3_key, instance.previous_thumbnail_key), str(instance.photo_id))
