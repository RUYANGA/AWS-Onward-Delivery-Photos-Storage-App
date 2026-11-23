import hashlib
from io import StringIO

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase

from apps.photos.models import Photo, PhotoChange

from .helpers import MockedS3Mixin, make_jpeg

BUCKET = settings.PHOTO_BUCKET


class EditTestMixin(MockedS3Mixin):
    def edit(self, record, **overrides):
        """POST the edit form for ``record`` with its current values, changed by ``overrides``."""
        data = {
            "title": record.title,
            "description": record.description,
            "merchant_name": record.merchant_name or "",
            "rider_name": record.rider_name or "",
            "delivery_city": record.delivery_city or "",
            "captured_at": f"{record.captured_at:%Y-%m-%dT%H:%M}" if record.captured_at else "",
            "reason": "Wrong merchant entered at upload",
            "revision": record.revision,
        }
        data.update(overrides)
        return self.client.post(f"/photos/{record.id}/edit", data=data)

    def exists(self, key) -> bool:
        try:
            self.s3.head_object(Bucket=BUCKET, Key=key)
            return True
        except ClientError:
            return False


class EditDetailsTests(EditTestMixin, TestCase):
    def test_edit_page_is_prefilled(self):
        self.upload()
        photo = self.only_photo()
        page = self.client.get(f"/photos/{photo.id}/edit").content.decode()
        self.assertIn('value="Parcel left with reception"', page)
        self.assertIn('value="Kivu Crafts"', page)
        self.assertIn('value="2026-11-20T14:05"', page)
        self.assertIn('name="revision" value="1"', page)
        self.assertIn(photo.delivery_reference, page)
        self.assertNotIn('name="delivery_reference"', page)

    def test_edit_saves_details_and_records_why(self):
        self.upload()
        photo = self.only_photo()
        response = self.edit(photo, merchant_name="Kivu Crafts Ltd", delivery_city="")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], f"/photos/{photo.id}?notice=updated")

        photo.refresh_from_db()
        self.assertEqual(photo.merchant_name, "Kivu Crafts Ltd")
        self.assertIsNone(photo.delivery_city)
        self.assertEqual(photo.revision, 2)
        self.assertIsNotNone(photo.updated_at)

        change = PhotoChange.objects.get()
        self.assertEqual(change.revision, 2)
        self.assertEqual(change.reason, "Wrong merchant entered at upload")
        self.assertEqual(change.changes, [
            {"field": "merchant_name", "label": "Merchant", "from": "Kivu Crafts", "to": "Kivu Crafts Ltd"},
            {"field": "delivery_city", "label": "City", "from": "Kigali", "to": None},
        ])
        self.assertFalse(change.replaced_photo)

        sidecar = self.read_json(photo.metadata_key)
        self.assertEqual(sidecar["merchant_name"], "Kivu Crafts Ltd")
        self.assertEqual(sidecar["revision"], 2)
        self.assertEqual(sidecar["history"][0]["reason"], "Wrong merchant entered at upload")

        page = self.client.get(response["Location"]).content.decode()
        self.assertIn("Changes saved", page)
        self.assertIn("Change history", page)
        self.assertIn("“Wrong merchant entered at upload”", page)
        self.assertIn("<del>Kivu Crafts</del>", page)
        self.assertIn("<ins>Kivu Crafts Ltd</ins>", page)
        self.assertIn("revision 2", page)

    def test_reason_is_required(self):
        self.upload()
        photo = self.only_photo()
        response = self.edit(photo, title="New title", reason="  ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Say why you", response.content.decode())
        photo.refresh_from_db()
        self.assertEqual(photo.title, "Parcel left with reception")
        self.assertFalse(PhotoChange.objects.exists())

    def test_saving_without_changes_is_refused(self):
        self.upload()
        response = self.edit(self.only_photo())
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nothing has changed", response.content.decode())
        self.assertFalse(PhotoChange.objects.exists())

    def test_reference_and_upload_time_cannot_be_changed(self):
        self.upload()
        photo = self.only_photo()
        self.edit(photo, title="New title", delivery_reference="ONW-0000-000000", created_at="2020-01-01T00:00")
        updated = self.only_photo()
        self.assertEqual(updated.delivery_reference, photo.delivery_reference)
        self.assertEqual(updated.created_at, photo.created_at)

    def test_an_edit_based_on_an_old_revision_is_refused(self):
        self.upload()
        photo = self.only_photo()
        self.assertEqual(self.edit(photo, title="First edit").status_code, 303)

        stale = self.edit(photo, title="Second edit from an old page")  # still says revision 1
        self.assertEqual(stale.status_code, 409)
        body = stale.content.decode()
        self.assertIn("Someone else changed this photo", body)
        self.assertIn('value="First edit"', body)  # the latest details are shown
        self.assertEqual(self.only_photo().title, "First edit")
        self.assertEqual(PhotoChange.objects.count(), 1)

    def test_deleted_photos_cannot_be_edited(self):
        self.upload()
        photo = self.only_photo()
        self.client.post(f"/photos/{photo.id}/delete")
        self.assertEqual(self.client.get(f"/photos/{photo.id}/edit").status_code, 404)
        self.assertEqual(self.edit(photo, title="x").status_code, 404)
        self.assertNotIn(f"/photos/{photo.id}/edit", self.client.get(f"/photos/{photo.id}").content.decode())

    def test_live_photo_links_to_edit(self):
        self.upload()
        photo = self.only_photo()
        self.assertIn(f'href="/photos/{photo.id}/edit"', self.client.get(f"/photos/{photo.id}").content.decode())


class ReplacePhotoTests(EditTestMixin, TestCase):
    def replacement(self, content=None):
        return SimpleUploadedFile("better.jpg", content or make_jpeg(color=(10, 200, 90)), content_type="image/jpeg")

    def test_replacing_keeps_the_previous_photo_as_evidence(self):
        self.upload()
        photo = self.only_photo()
        new_bytes = make_jpeg(color=(10, 200, 90))
        response = self.edit(photo, photo=self.replacement(new_bytes), reason="Wrong parcel photographed")
        self.assertEqual(response.status_code, 303)

        updated = self.only_photo()
        self.assertNotEqual(updated.s3_key, photo.s3_key)
        self.assertEqual(updated.sha256, hashlib.sha256(new_bytes).hexdigest())
        self.assertEqual(self.s3.get_object(Bucket=BUCKET, Key=updated.s3_key)["Body"].read(), new_bytes)
        self.assertTrue(updated.s3_version_id)

        # the previous original and thumbnail are untouched and recorded
        self.assertTrue(self.exists(photo.s3_key))
        self.assertTrue(self.exists(photo.thumbnail_key))
        change = PhotoChange.objects.get()
        self.assertTrue(change.replaced_photo)
        self.assertEqual(change.previous_s3_key, photo.s3_key)
        self.assertEqual(change.previous_sha256, photo.sha256)
        self.assertEqual(change.previous_s3_version_id, photo.s3_version_id)
        self.assertEqual(change.changes, [{"field": "photo", "label": "Photo",
                                           "from": photo.sha256, "to": updated.sha256}])

        page = self.client.get(f"/photos/{photo.id}").content.decode()
        self.assertIn("Photo replaced", page)
        self.assertIn(f'href="/{photo.s3_key}"', page)
        self.assertIn(photo.sha256, page)

    def test_an_unreadable_replacement_changes_nothing(self):
        self.upload()
        photo = self.only_photo()
        response = self.edit(photo, photo=self.replacement(b"not an image"), title="New title")
        self.assertEqual(response.status_code, 400)
        self.assertIn("readable photo", response.content.decode())
        self.assertEqual(self.only_photo().s3_key, photo.s3_key)
        self.assertEqual(self.only_photo().title, photo.title)

    def test_a_conflict_removes_the_unused_upload(self):
        self.upload()
        photo = self.only_photo()
        before = {o["Key"] for o in self.s3.list_objects_v2(Bucket=BUCKET)["Contents"]}
        Photo.objects.filter(pk=photo.pk).update(revision=5)  # changed by someone else meanwhile
        response = self.edit(photo, photo=self.replacement())
        self.assertEqual(response.status_code, 409)
        after = {o["Key"] for o in self.s3.list_objects_v2(Bucket=BUCKET)["Contents"]}
        self.assertEqual(after, before)

    def test_deleting_permanently_removes_earlier_photos_too(self):
        self.upload()
        photo = self.only_photo()
        self.edit(photo, photo=self.replacement())
        updated = self.only_photo()
        keys = (photo.s3_key, photo.thumbnail_key, updated.s3_key, updated.thumbnail_key, updated.metadata_key)
        self.client.post(f"/photos/{photo.id}/delete")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/photos/{photo.id}/purge")
        self.assertFalse(PhotoChange.objects.exists())
        for key in keys:
            self.assertFalse(self.exists(key), key)


class RebuildWithHistoryTests(EditTestMixin, TestCase):
    def test_rebuild_restores_the_change_history(self):
        self.upload()
        photo = self.only_photo()
        self.edit(photo, merchant_name="Kivu Crafts Ltd")
        self.edit(self.only_photo(), photo=SimpleUploadedFile("b.jpg", make_jpeg(color=(1, 2, 3))),
                  reason="Clearer photo of the doorstep")
        expected = list(PhotoChange.objects.order_by("revision").values(
            "revision", "reason", "changes", "previous_s3_key", "previous_sha256"))
        Photo.objects.all().delete()  # simulate a lost database (files stay: no on-commit here)

        out = StringIO()
        call_command("rebuild_catalogue", bucket=BUCKET, region=settings.AWS_REGION, stdout=out)
        rebuilt = self.only_photo()
        self.assertEqual(rebuilt.revision, 3)
        self.assertEqual(rebuilt.merchant_name, "Kivu Crafts Ltd")
        self.assertEqual(list(PhotoChange.objects.order_by("revision").values(
            "revision", "reason", "changes", "previous_s3_key", "previous_sha256")), expected)

        orphans = StringIO()
        call_command("rebuild_catalogue", bucket=BUCKET, region=settings.AWS_REGION, report_orphans=True,
                     stdout=orphans)
        self.assertIn("0 original photo(s) without a catalogue row", orphans.getvalue())
