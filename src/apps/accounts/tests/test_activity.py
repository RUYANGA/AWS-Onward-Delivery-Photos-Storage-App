from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Activity
from apps.photos.tests.helpers import MockedS3Mixin

User = get_user_model()
A = Activity.Action
STRONG = "Delivery-photos-2026"


class ActivityTests(MockedS3Mixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.post("/manage/users/new", {"name": "Aline Uwase", "email": "aline@example.com",
                                               "password1": STRONG, "password2": STRONG})
        self.editor = User.objects.get(email="aline@example.com")

    def as_editor(self):
        self.client.post("/sign-out")
        self.client.post("/sign-in", {"username": "aline@example.com", "password": STRONG})

    def actions(self, user):
        return list(Activity.objects.filter(user=user).order_by("at", "id").values_list("action", flat=True))

    def test_records_what_an_editor_does(self):
        self.client.post("/sign-out")
        self.client.post("/sign-in", {"username": "aline@example.com", "password": "wrong-password"})
        self.as_editor()
        self.upload()
        photo = self.only_photo()
        self.client.post(f"/photos/{photo.id}/edit", {
            "title": "Better title", "description": "", "merchant_name": "", "rider_name": "",
            "delivery_city": "Kigali", "captured_at": "", "reason": "Clearer title", "revision": 1})
        self.client.post(f"/photos/{photo.id}/delete")
        self.client.post(f"/photos/{photo.id}/restore")
        self.client.post("/account", {"action": "name", "name": "Aline M. Uwase"})
        self.client.post("/sign-out")
        self.assertEqual(self.actions(self.editor), [
            A.SIGN_IN_FAILED, A.SIGNED_IN, A.UPLOADED, A.EDITED, A.DELETED, A.RESTORED, A.NAME_CHANGED, A.SIGNED_OUT])
        edit = Activity.objects.get(action=A.EDITED)
        self.assertEqual((edit.photo, edit.detail, edit.actor_name), (photo, "Clearer title", "Aline Uwase"))
        self.assertTrue(edit.subject.startswith(photo.delivery_reference))

    def test_records_what_an_administrator_does(self):
        self.upload()
        photo = self.only_photo()
        reference = photo.delivery_reference
        self.client.post(f"/photos/{photo.id}/delete")
        self.client.post(f"/photos/{photo.id}/purge")
        purge = Activity.objects.get(action=A.PURGED)
        self.assertIsNone(purge.photo)
        self.assertIn(reference, purge.subject)  # still readable after the photo is gone

        self.client.post(f"/manage/users/{self.editor.pk}/edit", {"name": "Aline Uwase", "email": "aline@example.com",
                                                                  "password1": "Fresh-password-2026",
                                                                  "password2": "Fresh-password-2026"})
        update = Activity.objects.get(action=A.USER_UPDATED)
        self.assertEqual((update.user, update.account), (self.admin, self.editor))
        self.assertEqual(update.detail, "Changed account disabled, password reset")
        added = Activity.objects.get(action=A.USER_ADDED)
        self.assertEqual((added.user, added.account), (self.admin, self.editor))

    def test_user_page_shows_profile_figures_and_timeline(self):
        self.as_editor()
        self.upload()
        self.client.force_login(self.admin)
        response = self.client.get(f"/manage/users/{self.editor.pk}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("aline@example.com", body)
        self.assertIn("Uploaded a photo", body)
        self.assertIn("Account added by", body)
        self.assertIn("Recent uploads", body)
        self.assertEqual((response.context["stats"]["uploads"], response.context["stats"]["sign_ins"]), (1, 1))

        photos_only = self.client.get(f"/manage/users/{self.editor.pk}?type=photos").content.decode()
        self.assertIn("Uploaded a photo", photos_only)
        self.assertNotIn("Signed in", photos_only)
        self.assertIn('href="?type=photos" aria-current="true"', photos_only)

    def test_users_list_links_to_each_profile(self):
        body = self.client.get("/manage/users").content.decode()
        self.assertIn(f'href="/manage/users/{self.editor.pk}"', body)
        self.assertIn(f'href="/manage/users/{self.admin.pk}"', body)  # administrators can be viewed too
        self.assertEqual(self.client.get(f"/manage/users/{self.admin.pk}").status_code, 200)

    def test_only_administrators_see_user_pages(self):
        self.as_editor()
        self.assertEqual(self.client.get(f"/manage/users/{self.editor.pk}").status_code, 403)
        self.client.post("/sign-out")
        self.assertTrue(self.client.get(f"/manage/users/{self.editor.pk}")["Location"].startswith("/sign-in"))

    def test_deleting_a_user_keeps_their_activity(self):
        self.as_editor()
        self.upload()
        self.client.force_login(self.admin)
        self.client.post(f"/manage/users/{self.editor.pk}/delete")
        upload = Activity.objects.get(action=A.UPLOADED)
        self.assertIsNone(upload.user)
        self.assertEqual(upload.actor_name, "Aline Uwase")
        self.assertIn("aline@example.com", Activity.objects.get(action=A.USER_DELETED).subject)
