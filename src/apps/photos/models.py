import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Photo(models.Model):
    """A delivery photo's details. The image lives in S3, linked by key, version ID and checksum."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    delivery_reference = models.CharField(max_length=64, db_index=True)
    merchant_name = models.CharField(max_length=120, null=True, blank=True)
    rider_name = models.CharField(max_length=120, null=True, blank=True)
    delivery_city = models.CharField(max_length=80, null=True, blank=True, db_index=True)
    captured_at = models.DateTimeField(null=True, blank=True)

    s3_key = models.CharField(max_length=255, unique=True)
    s3_version_id = models.CharField(max_length=1024, null=True, blank=True)
    thumbnail_key = models.CharField(max_length=255)
    metadata_key = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    content_type = models.CharField(max_length=50)
    size_bytes = models.BigIntegerField()
    width = models.IntegerField()
    height = models.IntegerField()

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)  # soft delete
    updated_at = models.DateTimeField(null=True, blank=True)  # last edit; null if never edited
    revision = models.PositiveIntegerField(default=1)  # +1 per edit; stops two edits overwriting each other
    uploaded_by = models.CharField(max_length=150, blank=True, default="")  # name at the time (evidence)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="uploaded_photos")  # the account, for "my uploads"
    deleted_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        db_table = "photos"
        ordering = ["-created_at"]
        permissions = [("purge_photo", "Can delete photos permanently")]  # administrators only

    def __str__(self):
        return f"{self.delivery_reference}: {self.title}"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1_048_576

    def sidecar(self) -> dict:
        """Replicated to the DR Region with the photo, so the catalogue can be rebuilt from S3."""

        def iso(value):
            return value.isoformat() if value else None

        return {
            "schema": 3,
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "delivery_reference": self.delivery_reference,
            "merchant_name": self.merchant_name,
            "rider_name": self.rider_name,
            "delivery_city": self.delivery_city,
            "captured_at": iso(self.captured_at),
            "s3_key": self.s3_key,
            "s3_version_id": self.s3_version_id,
            "thumbnail_key": self.thumbnail_key,
            "sha256": self.sha256,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "created_at": iso(self.created_at),
            "uploaded_by": self.uploaded_by,
            "deleted_at": iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "updated_at": iso(self.updated_at),
            "revision": self.revision,
            "history": [change.sidecar() for change in self.changes.order_by("revision")],
        }


class PhotoChange(models.Model):
    """One edit of a photo: who, what, when and why, recorded kept as part of the evidence.

    ``changes`` lists each changed detail as {"field", "label", "from", "to"}. When the photo itself
    was replaced, the previous file stays in S3 and is recorded here, so it can still be shown and
    verified against its checksum.
    """

    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="changes")
    revision = models.PositiveIntegerField()  # the photo's revision after this change
    changed_at = models.DateTimeField(default=timezone.now)
    changed_by = models.CharField(max_length=150, blank=True, default="")  # name at the time (evidence)
    changed_by_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="photo_changes")
    reason = models.CharField(max_length=500)
    changes = models.JSONField(default=list)

    previous_s3_key = models.CharField(max_length=255, null=True, blank=True)
    previous_s3_version_id = models.CharField(max_length=1024, null=True, blank=True)
    previous_thumbnail_key = models.CharField(max_length=255, null=True, blank=True)
    previous_sha256 = models.CharField(max_length=64, null=True, blank=True)
    previous_content_type = models.CharField(max_length=50, null=True, blank=True)
    previous_size_bytes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "photo_changes"
        ordering = ["-revision"]
        constraints = [models.UniqueConstraint(fields=["photo", "revision"], name="photo_change_revision_unique")]

    def __str__(self):
        return f"{self.photo_id} r{self.revision}: {self.reason}"

    @property
    def replaced_photo(self) -> bool:
        return bool(self.previous_s3_key)

    @property
    def previous_size_mb(self) -> float:
        return (self.previous_size_bytes or 0) / 1_048_576

    def sidecar(self) -> dict:
        return {
            "revision": self.revision,
            "changed_at": self.changed_at.isoformat(),
            "changed_by": self.changed_by,
            "reason": self.reason,
            "changes": self.changes,
            "previous_s3_key": self.previous_s3_key,
            "previous_s3_version_id": self.previous_s3_version_id,
            "previous_thumbnail_key": self.previous_thumbnail_key,
            "previous_sha256": self.previous_sha256,
            "previous_content_type": self.previous_content_type,
            "previous_size_bytes": self.previous_size_bytes,
        }
