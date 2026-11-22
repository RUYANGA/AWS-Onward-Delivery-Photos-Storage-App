from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from functools import lru_cache

import boto3
from botocore.config import Config
from django.conf import settings

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"  # keys are random UUIDs, never reused


class PhotoStore:
    """All S3 access. The task role can read and write but has no delete permission."""

    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None,
                 storage_class: str = "INTELLIGENT_TIERING", client=None) -> None:
        self.bucket = bucket
        self.storage_class = storage_class
        self.s3 = client or boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(retries={"mode": "standard", "max_attempts": 5}, signature_version="s3v4"),
        )

    def put_image(self, key: str, body: bytes, content_type: str, sha256_hex: str | None = None) -> str | None:
        extra = {}
        if sha256_hex:
            # S3 verifies the upload against this checksum and keeps it for later integrity checks.
            extra["ChecksumSHA256"] = base64.b64encode(bytes.fromhex(sha256_hex)).decode()
        response = self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=IMMUTABLE_CACHE,
            StorageClass=self.storage_class,
            **extra,
        )
        return response.get("VersionId")

    def put_sidecar(self, key: str, document: dict) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(document, indent=2, sort_keys=True).encode(),
            ContentType="application/json",
            StorageClass=self.storage_class,
        )

    def stream(self, key: str) -> tuple[Iterator[bytes], str, int | None]:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        content_type = obj.get("ContentType", "application/octet-stream")
        return obj["Body"].iter_chunks(chunk_size=64 * 1024), content_type, obj.get("ContentLength")


@lru_cache(maxsize=1)
def get_photo_store() -> PhotoStore:
    return PhotoStore(settings.PHOTO_BUCKET, settings.AWS_REGION, settings.S3_ENDPOINT_URL,
                      settings.S3_STORAGE_CLASS)
