from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.photos.models import Photo
from apps.photos.tests.helpers import MockedS3Mixin

User = get_user_model()
STRONG = "Delivery-photos-2026"
EDIT = {"description": "", "merchant_name": "", "rider_name": "", "delivery_city": "Kigali", "captured_at": "",
        "reason": "Correction"}


class OwnPhotosOnlyTests(MockedS3Mixin, TestCase):
    """Editors manage only the photos they uploaded; administrators manage every photo."""

    def setUp(self):
        super().setUp()
        self.upload(title="Administrator's photo")
        self.theirs = Photo.objects.get()
        for email, name in (("aline@example.com", "Aline Uwase"), ("eric@example.com", "Eric Mugisha")):
            self.client.post("/manage/users/new", {"name": name, "email": email, "password1": STRONG,
                                                   "password2": STRONG})
        self.aline, self.eric = User.objects.get(email="aline@example.com"), User.objects.get(email="eric@example.com")
        self.client.force_login(self.aline)
        self.upload(title="Aline's photo")
        self.mine = Photo.objects.get(title="Aline's photo")

    def test_cannot_change_someone_elses_photo(self):
        url = f"/photos/{self.theirs.id}"
        self.assertEqual(self.client.get(f"{url}/edit").status_code, 403)
        self.assertEqual(self.client.post(f"{url}/edit", {**EDIT, "title": "Hijacked", "revision": 1}).status_code, 403)
        self.assertEqual(self.client.post(f"{url}/delete").status_code, 403)
        self.theirs.refresh_from_db()
        self.assertEqual((self.theirs.title, self.theirs.deleted_at), ("Administrator's photo", None))

    def test_cannot_restore_or_see_someone_elses_deleted_photo(self):
        self.client.force_login(self.admin)
        self.client.post(f"/photos/{self.theirs.id}/delete")
        self.client.force_login(self.aline)
        self.assertEqual(self.client.post(f"/photos/{self.theirs.id}/restore").status_code, 403)
        self.assertEqual(self.client.get(f"/photos/{self.theirs.id}").status_code, 404)
        self.assertNotIn("Administrator's photo", self.client.get("/deleted").content.decode())
        self.assertIsNotNone(Photo.objects.get(pk=self.theirs.pk).deleted_at)

    def test_manages_own_photos(self):
        url = f"/photos/{self.mine.id}"
        self.assertEqual(self.client.post(f"{url}/edit", {**EDIT, "title": "Aline's better photo",
                                                          "revision": 1}).status_code, 303)
        self.assertEqual(self.client.post(f"{url}/delete").status_code, 303)
        self.assertIn("Aline&#x27;s better photo", self.client.get("/deleted").content.decode())
        self.assertEqual(self.client.post(f"{url}/restore").status_code, 303)

    def test_dashboard_and_buttons_show_only_own_photos(self):
        body = self.client.get("/manage").content.decode()
        self.assertIn("Aline&#x27;s photo", body)
        self.assertNotIn("Administrator&#x27;s photo", body)
        self.assertIn("You have 1 live photo<", body)
        theirs_page = self.client.get(f"/photos/{self.theirs.id}").content.decode()
        self.assertNotIn(f"/photos/{self.theirs.id}/edit", theirs_page)
        self.assertIn(f"/photos/{self.mine.id}/edit", self.client.get(f"/photos/{self.mine.id}").content.decode())

    def test_other_editors_cannot_touch_it_either(self):
        self.client.force_login(self.eric)
        self.assertEqual(self.client.post(f"/photos/{self.mine.id}/delete").status_code, 403)
        self.assertNotIn("Aline&#x27;s photo", self.client.get("/manage").content.decode())

    def test_administrators_manage_every_photo(self):
        self.client.force_login(self.admin)
        body = self.client.get("/manage").content.decode()
        self.assertIn("Aline&#x27;s photo", body)
        self.assertIn("2 live photos", body)
        self.assertEqual(self.client.post(f"/photos/{self.mine.id}/edit", {**EDIT, "title": "Fixed by admin",
                                                                          "revision": 1}).status_code, 303)
        self.assertEqual(self.client.post(f"/photos/{self.mine.id}/delete").status_code, 303)
        self.assertEqual(self.client.post(f"/photos/{self.mine.id}/restore").status_code, 303)
