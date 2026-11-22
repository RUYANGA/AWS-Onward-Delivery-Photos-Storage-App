import hashlib

from botocore.exceptions import ClientError
from django.conf import settings
from django.test import Client, TestCase

from apps.photos.models import Photo

from .helpers import MockedS3Mixin, make_jpeg

BUCKET = settings.PHOTO_BUCKET


class UploadAndGalleryTests(MockedS3Mixin, TestCase):
    def test_upload_appears_in_gallery_with_details(self):
        response = self.upload()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], "/?notice=uploaded")

        gallery = self.client.get("/").content.decode()
        self.assertIn("Parcel left with reception", gallery)
        self.assertIn(self.only_photo().delivery_reference, gallery)
        self.assertIn("Kigali", gallery)

        detail = self.client.get(f"/photos/{self.only_photo().id}").content.decode()
        self.assertIn("Kivu Crafts", detail)
        self.assertIn("Signed for by the front desk.", detail)
        self.assertIn("20 Nov 2026 14:05 UTC", detail)

    def test_photo_bytes_live_in_s3_not_in_database(self):
        original = make_jpeg()
        self.upload(photo_bytes=original)
        photo = self.only_photo()

        stored = self.s3.get_object(Bucket=BUCKET, Key=photo.s3_key)
        self.assertEqual(stored["Body"].read(), original)
        self.assertTrue(stored["CacheControl"].endswith("immutable"))
        self.assertEqual(photo.sha256, hashlib.sha256(original).hexdigest())
        self.assertTrue(photo.s3_version_id)
        thumb = self.s3.get_object(Bucket=BUCKET, Key=photo.thumbnail_key)
        self.assertEqual(thumb["ContentType"], "image/webp")

        # No column can hold file contents.
        field_types = {f.get_internal_type() for f in Photo._meta.get_fields()}
        self.assertNotIn("BinaryField", field_types)
        self.assertNotIn("FileField", field_types)
        self.assertNotIn("ImageField", field_types)

    def test_sidecar_written_for_disaster_recovery(self):
        self.upload()
        photo = self.only_photo()
        sidecar = self.read_json(photo.metadata_key)
        self.assertEqual(sidecar["delivery_reference"], photo.delivery_reference)
        self.assertEqual(sidecar["s3_key"], photo.s3_key)
        self.assertIsNone(sidecar["deleted_at"])

    def test_app_assigns_the_delivery_reference(self):
        page = self.client.get("/upload").content.decode()
        self.assertNotIn('name="delivery_reference"', page)

        self.upload(delivery_reference="IGNORED-123")
        photo = self.only_photo()
        self.assertRegex(photo.delivery_reference, r"^ONW-\d{4}-[0-9A-F]{6}$")
        self.assertEqual(photo.delivery_reference, f"ONW-{photo.created_at:%Y}-{photo.id.hex[:6].upper()}")

    def test_search_filters_by_reference(self):
        self.upload()
        self.upload(title="Second drop")
        reference = Photo.objects.get(title="Second drop").delivery_reference
        body = self.client.get(f"/?q={reference[-6:].lower()}").content.decode()
        self.assertIn("Second drop", body)
        self.assertNotIn("Parcel left with reception", body)


class SoftDeleteTests(MockedS3Mixin, TestCase):
    def test_soft_delete_and_restore(self):
        self.upload()
        photo = self.only_photo()

        self.assertEqual(self.client.post(f"/photos/{photo.id}/delete").status_code, 303)
        self.assertNotIn("Parcel left with reception", self.client.get("/").content.decode())
        self.assertIn("Parcel left with reception", self.client.get("/deleted").content.decode())
        self.assertIsNotNone(self.read_json(photo.metadata_key)["deleted_at"])

        self.assertEqual(self.client.post(f"/photos/{photo.id}/restore").status_code, 303)
        self.assertIn("Parcel left with reception", self.client.get("/").content.decode())
        # the S3 object was never touched
        self.assertGreater(self.s3.head_object(Bucket=BUCKET, Key=photo.s3_key)["ContentLength"], 0)

    def test_delete_and_restore_ask_for_confirmation(self):
        self.upload()
        photo = self.only_photo()
        detail = self.client.get(f"/photos/{photo.id}").content.decode()
        self.assertIn('data-confirm-title="Delete this photo?"', detail)

        self.client.post(f"/photos/{photo.id}/delete")
        for page in ("/deleted", f"/photos/{photo.id}"):
            body = self.client.get(page).content.decode()
            self.assertIn('data-confirm-title="Restore this photo?"', body)
            self.assertIn('data-confirm-tone="restore"', body)

    def test_delete_permanently_removes_row_and_files(self):
        self.upload()
        photo = self.only_photo()
        keys = (photo.s3_key, photo.thumbnail_key, photo.metadata_key)
        self.client.post(f"/photos/{photo.id}/delete")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/photos/{photo.id}/purge")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], "/deleted?notice=purged")
        self.assertFalse(Photo.objects.exists())
        for key in keys:
            self.assertFalse(self.exists(key), key)
        self.assertIn("deleted permanently", self.client.get(response["Location"]).content.decode())

    def test_only_deleted_photos_can_be_deleted_permanently(self):
        self.upload()
        photo = self.only_photo()
        self.assertEqual(self.client.post(f"/photos/{photo.id}/purge").status_code, 404)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/purge").status_code, 405)
        self.assertTrue(Photo.objects.exists())
        self.assertTrue(self.exists(photo.s3_key))

    def test_deleting_rows_from_the_database_removes_their_files(self):
        self.upload()
        self.upload(title="Second drop")
        keys = [k for p in Photo.objects.all() for k in (p.s3_key, p.thumbnail_key, p.metadata_key)]
        with self.captureOnCommitCallbacks(execute=True):
            Photo.objects.all().delete()
        self.assertEqual(len(keys), 6)
        for key in keys:
            self.assertFalse(self.exists(key), key)

    def test_delete_permanently_asks_for_confirmation(self):
        self.upload()
        photo = self.only_photo()
        self.assertNotIn("/purge", self.client.get(f"/photos/{photo.id}").content.decode())
        self.client.post(f"/photos/{photo.id}/delete")
        for page in ("/deleted", f"/photos/{photo.id}"):
            body = self.client.get(page).content.decode()
            self.assertIn(f'action="/photos/{photo.id}/purge"', body)
            self.assertIn('data-confirm-title="Delete this photo permanently?"', body)

    def exists(self, key) -> bool:
        try:
            self.s3.head_object(Bucket=BUCKET, Key=key)
            return True
        except ClientError:
            return False

    def test_delete_requires_post(self):
        self.upload()
        self.assertEqual(self.client.get(f"/photos/{self.only_photo().id}/delete").status_code, 405)


class ValidationTests(MockedS3Mixin, TestCase):
    def test_rejects_non_image(self):
        response = self.upload(photo_bytes=b"not an image", filename="evil.jpg")
        self.assertEqual(response.status_code, 400)
        self.assertIn("readable photo", response.content.decode())
        self.assertEqual(Photo.objects.count(), 0)

    def test_requires_title(self):
        response = self.upload(title="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Enter a title", response.content.decode())

    def test_rejects_oversized_upload(self):
        big = b"\xff\xd8" + b"0" * (6 * 1024 * 1024)
        response = self.upload(photo_bytes=big, filename="huge.jpg")
        self.assertEqual(response.status_code, 413)
        self.assertIn("larger than 5 MB", response.content.decode())

    def test_forms_are_protected_against_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/upload", data={"title": "x"})
        self.assertEqual(response.status_code, 403)
        page = client.get("/upload").content.decode()
        self.assertIn("csrfmiddlewaretoken", page)


class MediaFallbackTests(MockedS3Mixin, TestCase):
    def test_media_fallback_only_serves_known_keys(self):
        self.upload()
        photo = self.only_photo()
        ok = self.client.get("/" + photo.thumbnail_key)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(b"".join(ok.streaming_content)[:4], b"RIFF")  # WebP
        self.assertEqual(self.client.get("/media/../meta/secret.json").status_code, 404)
        self.assertEqual(self.client.get("/media/anything.jpg").status_code, 404)
