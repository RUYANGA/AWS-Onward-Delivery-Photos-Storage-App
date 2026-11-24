from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.roles import EDITORS
from apps.photos.models import Photo, PhotoChange
from apps.photos.tests.helpers import MockedS3Mixin

User = get_user_model()
STRONG = "Delivery-photos-2026"


def add_user_data(**overrides):
    data = {"name": "Aline  Uwase", "email": "Aline@Example.com", "password1": STRONG, "password2": STRONG}
    data.update(overrides)
    return data


class ManageUsersTests(MockedS3Mixin, TestCase):
    """The administrator (signed in by MockedS3Mixin) adds, changes and deletes editors."""

    def add(self, **overrides):
        return self.client.post("/manage/users/new", add_user_data(**overrides))

    def test_users_page_lists_accounts(self):
        body = self.client.get("/manage/users").content.decode()
        self.assertIn("Test Admin", body)
        self.assertIn("Managed in AWS", body)  # the administrator can't be edited here
        self.assertIn('href="/manage/users/new"', body)

    def test_add_an_editor(self):
        response = self.add()
        self.assertEqual(response["Location"], "/manage/users?notice=user-added")
        user = User.objects.get(email="aline@example.com")
        self.assertEqual((user.username, user.first_name, user.last_name), ("aline@example.com", "Aline", "Uwase"))
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertTrue(user.groups.filter(name=EDITORS).exists())
        self.assertTrue(user.has_perm("photos.add_photo") and user.has_perm("photos.change_photo"))
        self.assertTrue(user.has_perm("photos.delete_photo"))  # delete and restore
        self.assertFalse(user.has_perm("photos.purge_photo"))  # but never delete permanently
        self.assertIn("User added", self.client.get(response["Location"]).content.decode())

    def test_add_validates_the_details(self):
        cases = (
            ({"name": ""}, "Enter the full name."),
            ({"email": "admin@example.com"}, "An account with this email address already exists."),
            ({"password1": "short", "password2": "short"}, "too short"),
            ({"password2": "Something-else-2026"}, "The two passwords don&#x27;t match."),
            ({"password1": "", "password2": ""}, "Set a password for the new account."),
        )
        for overrides, message in cases:
            response = self.add(**overrides)
            self.assertEqual(response.status_code, 400, overrides)
            self.assertIn(message, response.content.decode(), overrides)
        self.assertEqual(User.objects.count(), 1)

    def test_edit_an_editor(self):
        self.add()
        user = User.objects.get(email="aline@example.com")
        page = self.client.get(f"/manage/users/{user.pk}/edit").content.decode()
        self.assertIn('value="Aline Uwase"', page)
        response = self.client.post(f"/manage/users/{user.pk}/edit", {
            "name": "Aline Mukamana", "email": "aline.m@example.com", "password1": "", "password2": ""})
        self.assertEqual(response["Location"], "/manage/users?notice=user-updated")
        user.refresh_from_db()
        self.assertEqual((user.get_full_name(), user.email, user.username, user.is_active),
                         ("Aline Mukamana", "aline.m@example.com", "aline.m@example.com", False))  # unticked box
        self.assertTrue(user.check_password(STRONG))  # empty password keeps the current one

    def test_reset_password_and_disable(self):
        self.add()
        user = User.objects.get(email="aline@example.com")
        self.client.post(f"/manage/users/{user.pk}/edit", {
            "name": "Aline Uwase", "email": "aline@example.com", "is_active": "on",
            "password1": "A-brand-new-pass-77", "password2": "A-brand-new-pass-77"})
        user.refresh_from_db()
        self.assertTrue(user.check_password("A-brand-new-pass-77") and user.is_active)

    def test_delete_an_editor_keeps_their_photos(self):
        self.add()
        user = User.objects.get(email="aline@example.com")
        self.client.force_login(user)
        self.upload()
        self.client.force_login(self.admin)
        response = self.client.post(f"/manage/users/{user.pk}/delete")
        self.assertEqual(response["Location"], "/manage/users?notice=user-deleted")
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        photo = self.only_photo()
        self.assertIsNone(photo.uploader)
        self.assertEqual(photo.uploaded_by, "Aline Uwase")

    def test_administrators_cannot_be_changed_or_deleted_here(self):
        self.assertEqual(self.client.get(f"/manage/users/{self.admin.pk}/edit").status_code, 404)
        self.assertEqual(self.client.post(f"/manage/users/{self.admin.pk}/delete").status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.admin.pk, is_superuser=True).exists())


class EditorTests(MockedS3Mixin, TestCase):
    """An editor signs in on the same page, uploads and edits, and can't delete or manage users."""

    sign_in_as_admin = False

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.client.post("/manage/users/new", add_user_data())
        self.client.post("/sign-out")
        self.editor = User.objects.get(email="aline@example.com")

    def sign_in(self):
        return self.client.post("/sign-in", {"username": "aline@example.com", "password": STRONG})

    def test_signs_in_on_the_same_page_and_sees_their_dashboard(self):
        self.assertEqual(self.sign_in()["Location"], "/manage?notice=signed-in")
        body = self.client.get("/manage").content.decode()
        self.assertIn("Welcome back, Aline", body)
        self.assertIn("My uploads", body)
        self.assertIn("Editor", body)
        self.assertNotIn('href="/manage/users"', body)
        self.assertIn('href="/deleted"', body)

    def test_can_upload_edit_delete_and_restore_but_not_delete_permanently(self):
        self.sign_in()
        self.assertEqual(self.upload().status_code, 303)
        photo = self.only_photo()
        self.assertEqual((photo.uploader, photo.uploaded_by), (self.editor, "Aline Uwase"))
        response = self.client.post(f"/photos/{photo.id}/edit", {
            "title": "Better title", "description": "", "merchant_name": "", "rider_name": "",
            "delivery_city": "Kigali", "captured_at": "", "reason": "Clearer title", "revision": 1})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(PhotoChange.objects.get().changed_by_user, self.editor)

        dashboard = self.client.get("/manage")
        self.assertEqual((dashboard.context["stats"]["mine"], dashboard.context["stats"]["my_edits"]), (1, 1))
        self.assertIn(f'action="/photos/{photo.id}/delete"', dashboard.content.decode())

        self.assertEqual(self.client.post(f"/photos/{photo.id}/delete")["Location"], "/manage?notice=deleted")
        deleted_page = self.client.get("/deleted")
        self.assertEqual(deleted_page.status_code, 200)
        body = deleted_page.content.decode()
        self.assertIn(f'action="/photos/{photo.id}/restore"', body)
        self.assertNotIn("/purge", body)
        self.assertIn("only an administrator can delete them permanently", body)
        self.assertEqual(self.client.post(f"/photos/{photo.id}/purge").status_code, 403)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

        self.assertEqual(self.client.post(f"/photos/{photo.id}/restore")["Location"], "/deleted?notice=restored")
        self.assertIsNone(Photo.objects.get().deleted_at)

    def test_cannot_manage_users(self):
        self.sign_in()
        for url in ("/manage/users", "/manage/users/new", f"/manage/users/{self.editor.pk}/edit"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(f"/manage/users/{self.editor.pk}/delete").status_code, 403)

    def test_disabled_editors_cannot_sign_in_and_are_signed_out(self):
        self.sign_in()
        User.objects.filter(pk=self.editor.pk).update(is_active=False)
        self.assertTrue(self.client.get("/manage")["Location"].startswith("/sign-in"))
        self.assertEqual(self.sign_in().status_code, 400)


class MyAccountTests(MockedS3Mixin, TestCase):
    sign_in_as_admin = False

    def setUp(self):
        super().setUp()
        self.editor = User.objects.create_user(username="aline@example.com", email="aline@example.com",
                                               password=STRONG, first_name="Aline", last_name="Uwase")
        self.client.force_login(self.editor)

    def test_shows_the_account(self):
        body = self.client.get("/account").content.decode()
        self.assertIn('value="Aline Uwase"', body)
        self.assertIn('value="aline@example.com" disabled', body)
        self.assertIn("Change password", body)

    def test_change_name_only(self):
        response = self.client.post("/account", {"action": "name", "name": "Aline  M. Uwase",
                                                  "email": "hacker@example.com"})
        self.assertEqual(response["Location"], "/account?notice=name")
        self.editor.refresh_from_db()
        self.assertEqual((self.editor.get_full_name(), self.editor.email), ("Aline M. Uwase", "aline@example.com"))
        self.assertIn("Your name is updated", self.client.get(response["Location"]).content.decode())

    def test_change_password(self):
        wrong = self.client.post("/account", {"action": "password", "old_password": "nope",
                                              "new_password1": "Another-good-pass-9",
                                              "new_password2": "Another-good-pass-9"})
        self.assertEqual(wrong.status_code, 400)
        self.assertIn("Your current password is incorrect.", wrong.content.decode())

        response = self.client.post("/account", {"action": "password", "old_password": STRONG,
                                                 "new_password1": "Another-good-pass-9",
                                                 "new_password2": "Another-good-pass-9"})
        self.assertEqual(response["Location"], "/account?notice=password")
        self.editor.refresh_from_db()
        self.assertTrue(self.editor.check_password("Another-good-pass-9"))
        self.assertEqual(self.client.get("/account").status_code, 200)  # still signed in here

    def test_administrator_account_is_read_only(self):
        self.client.force_login(self.admin)
        body = self.client.get("/account").content.decode()
        self.assertIn("set in AWS", body)
        self.assertNotIn('name="old_password"', body)
        self.assertEqual(self.client.post("/account", {"action": "name", "name": "Someone Else"}).status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.get_full_name(), "Test Admin")

    def test_viewers_are_sent_to_sign_in(self):
        self.client.post("/sign-out")
        self.assertEqual(self.client.get("/account")["Location"], "/sign-in?next=/account")
