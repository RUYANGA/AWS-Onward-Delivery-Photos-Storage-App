"""Shared test helpers: a mocked S3 bucket and an upload shortcut."""

import io

import boto3
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from moto import mock_aws
from PIL import Image

from apps.photos.models import Photo
from apps.photos.services.storage import get_photo_store


def make_jpeg(width=1200, height=900, color=(200, 120, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


class MockedS3Mixin:
    """Start moto, create a versioned photo bucket and point the PhotoStore at it."""

    def setUp(self):
        super().setUp()
        mock = mock_aws()
        mock.start()
        self.addCleanup(mock.stop)
        get_photo_store.cache_clear()
        self.addCleanup(get_photo_store.cache_clear)
        self.s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        self.s3.create_bucket(Bucket=settings.PHOTO_BUCKET,
                              CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION})
        self.s3.put_bucket_versioning(Bucket=settings.PHOTO_BUCKET,
                                      VersioningConfiguration={"Status": "Enabled"})

    def upload(self, photo_bytes=None, filename="delivery.jpg", **overrides):
        data = {
            "title": "Parcel left with reception",
            "description": "Signed for by the front desk.",
            "merchant_name": "Kivu Crafts",
            "rider_name": "Aline",
            "delivery_city": "Kigali",
            "captured_at": "2026-11-20T14:05",
            "photo": SimpleUploadedFile(filename, make_jpeg() if photo_bytes is None else photo_bytes,
                                        content_type="image/jpeg"),
        }
        data.update(overrides)
        return self.client.post("/upload", data=data)

    def only_photo(self) -> Photo:
        return Photo.objects.get()

    def read_json(self, key):
        import json

        return json.loads(self.s3.get_object(Bucket=settings.PHOTO_BUCKET, Key=key)["Body"].read())
