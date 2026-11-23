"""Disaster recovery: rebuild the photo catalogue (with each photo's change history) from the
meta/*.json sidecars in S3.

  python manage.py rebuild_catalogue --bucket <replica or primary bucket> [--dry-run]
  python manage.py rebuild_catalogue --bucket <bucket> --report-orphans

Uses the app's database settings (DATABASE_URL or DB_*).
"""

import json
import os
import uuid
from datetime import datetime

import boto3
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.photos.models import Photo, PhotoChange

DATE_FIELDS = ("captured_at", "created_at", "deleted_at", "updated_at")
COPY_FIELDS = ("title", "description", "delivery_reference", "merchant_name", "rider_name",
               "delivery_city", "s3_key", "s3_version_id", "thumbnail_key", "sha256",
               "content_type", "size_bytes", "width", "height")


def iter_keys(s3, bucket: str, prefix: str):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]


def photo_from_sidecar(doc: dict, metadata_key: str) -> Photo:
    values = {field: doc.get(field) for field in COPY_FIELDS}
    for field in DATE_FIELDS:
        values[field] = datetime.fromisoformat(doc[field]) if doc.get(field) else None
    return Photo(id=uuid.UUID(doc["id"]), metadata_key=metadata_key, revision=doc.get("revision") or 1, **values)


def changes_from_sidecar(doc: dict, photo: Photo) -> list[PhotoChange]:
    """The photo's change history (schema 2 sidecars; schema 1 has none)."""
    changes = []
    for entry in doc.get("history") or []:
        fields = {k: v for k, v in entry.items() if k != "changed_at"}
        changes.append(PhotoChange(photo=photo, changed_at=datetime.fromisoformat(entry["changed_at"]), **fields))
    return changes


class Command(BaseCommand):
    help = "Rebuild missing photo rows and their change history from the meta/*.json sidecars in S3."

    def add_arguments(self, parser):
        parser.add_argument("--bucket", required=True)
        parser.add_argument("--region", default=os.environ.get("AWS_REGION", "eu-central-1"))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--report-orphans", action="store_true")

    def handle(self, *args, **options):
        bucket = options["bucket"]
        s3 = boto3.client("s3", region_name=options["region"])

        if options["report_orphans"]:
            known_keys = set(Photo.objects.values_list("s3_key", flat=True))
            known_keys |= set(PhotoChange.objects.exclude(previous_s3_key=None)
                              .values_list("previous_s3_key", flat=True))  # earlier photos of edited rows
            orphans = [k for k in iter_keys(s3, bucket, "media/originals/") if k not in known_keys]
            self.stdout.write(f"{len(orphans)} original photo(s) without a catalogue row")
            for key in orphans:
                self.stdout.write(f"  {key}")
            return

        known_ids = set(Photo.objects.values_list("id", flat=True))
        restored = skipped = failed = 0
        with transaction.atomic():
            for key in iter_keys(s3, bucket, "meta/"):
                try:
                    doc = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
                    if uuid.UUID(doc["id"]) in known_ids:
                        skipped += 1
                        continue
                    if not options["dry_run"]:
                        photo = photo_from_sidecar(doc, key)
                        photo.save(force_insert=True)
                        PhotoChange.objects.bulk_create(changes_from_sidecar(doc, photo))
                    restored += 1
                except Exception as exc:  # keep going; report at the end
                    failed += 1
                    self.stderr.write(f"FAILED {key}: {exc}")

        verb = "Would restore" if options["dry_run"] else "Restored"
        self.stdout.write(f"{verb} {restored} row(s); {skipped} already present; {failed} failed.")
        if failed:
            raise CommandError(f"{failed} sidecar(s) could not be restored")
