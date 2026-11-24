from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.photos.models import Photo

from .helpers import MockedS3Mixin


class DashboardTests(MockedS3Mixin, TestCase):
    def test_lists_live_photos_with_their_actions(self):
        self.upload()
        self.upload(title="Second drop", delivery_city="Huye")
        photo = Photo.objects.get(title="Second drop")
        body = self.client.get("/manage").content.decode()
        self.assertIn("Welcome back, Test", body)
        self.assertIn("Second drop", body)
        self.assertIn(f'href="/photos/{photo.id}/edit"', body)
        self.assertIn(f'action="/photos/{photo.id}/delete"', body)
        self.assertIn("by Test Admin", body)

    def test_summary_counts(self):
        self.upload()
        self.upload(title="Second drop")
        self.client.post(f"/photos/{Photo.objects.get(title='Second drop').id}/delete")
        response = self.client.get("/manage")
        stats = response.context["stats"]
        self.assertEqual((stats["live"], stats["deleted"], stats["this_week"], stats["edited"]), (1, 1, 1, 0))
        self.assertGreater(stats["storage_mb"], 0)
        self.assertNotIn("Second drop", response.content.decode().split("<tbody>", 1)[1])

    def test_search(self):
        self.upload()
        self.upload(title="Second drop", delivery_city="Huye")
        body = self.client.get("/manage?q=huye").content.decode()
        self.assertIn("Second drop", body)
        self.assertNotIn("Parcel left with reception", body)
        self.assertIn("No live photos match", self.client.get("/manage?q=nothing").content.decode())

    def test_deleting_returns_to_the_dashboard_and_restoring_to_deleted_photos(self):
        self.upload()
        photo = self.only_photo()
        self.assertEqual(self.client.post(f"/photos/{photo.id}/delete")["Location"], "/manage?notice=deleted")
        self.assertEqual(self.client.post(f"/photos/{photo.id}/restore")["Location"], "/deleted?notice=restored")

    def test_photo_pages_have_no_delete_buttons_even_for_administrators(self):
        self.upload()
        photo = self.only_photo()
        for url in ("/", f"/photos/{photo.id}"):
            body = self.client.get(url).content.decode()
            self.assertNotIn("/delete", body, url)
            self.assertNotIn("data-confirm-action=", body, url)
        self.client.post(f"/photos/{photo.id}/delete")
        body = self.client.get(f"/photos/{photo.id}").content.decode()
        for action in ("/restore", "/purge", "data-confirm-action="):
            self.assertNotIn(action, body)
        self.assertIn('href="/deleted"', body)  # points to the dashboard instead

    def test_dashboard_is_for_administrators_only(self):
        self.client.post("/sign-out")
        self.assertTrue(self.client.get("/manage")["Location"].startswith("/sign-in?next="))
        user = get_user_model().objects.create_user(username="v@example.com", email="v@example.com", password="x")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/manage").status_code, 403)
