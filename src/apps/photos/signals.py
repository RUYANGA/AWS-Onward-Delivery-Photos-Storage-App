"""When a photo's row is deleted from the database, its files are removed from S3 too."""

import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Photo
from .services.storage import get_photo_store

log = logging.getLogger(__name__)


@receiver(post_delete, sender=Photo, dispatch_uid="photos.delete_files_from_s3")
def delete_files_from_s3(sender, instance: Photo, **kwargs) -> None:
    keys = (instance.s3_key, instance.thumbnail_key, instance.metadata_key)
    photo_id = str(instance.id)

    def remove() -> None:
        try:
            get_photo_store().delete(*keys)
            log.info("photo files deleted from S3", extra={"photo_id": photo_id})
        except Exception:  # the row is already gone; leftover files are logged for cleanup
            log.exception("deleting photo files from S3 failed", extra={"photo_id": photo_id, "keys": keys})

    # Only once the delete is committed: a rolled-back delete keeps its files.
    transaction.on_commit(remove)
