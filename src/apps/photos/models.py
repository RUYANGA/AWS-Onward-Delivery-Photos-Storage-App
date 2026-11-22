import uuid

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

    class Meta:
        db_table = "photos"
        ordering = ["-created_at"]

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
            "schema": 1,
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
            "deleted_at": iso(self.deleted_at),
        }
