import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import RequestFactory, TestCase

from apps.accounts import throttle
from apps.accounts.models import FailedSignIn
from apps.photos.models import Photo, PhotoChange
from apps.photos.tests.helpers import MockedS3Mixin

PASSWORD = "Correct-horse-42"
User = get_user_model()


class SignInTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="merci@example.com", email="merci@example.com",
                                                   password=PASSWORD, first_name="Merci", last_name="RUYANGA")

    def sign_in(self, email="merci@example.com", password=PASSWORD, **extra):
        return self.client.post("/sign-in", {"username": email, "password": password, **extra})

    def test_viewers_see_a_sign_in_link_and_no_management_links(self):
        page = self.client.get("/").content.decode()
        self.assertIn('href="/sign-in"', page)
        self.assertNotIn('href="/upload"', page)
        self.assertNotIn('href="/manage"', page)

    def test_sign_in_page(self):
        response = self.client.get("/sign-in")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('autocomplete="current-password"', body)
        self.assertIn("csrfmiddlewaretoken", body)
        self.assertIn("no-cache", response["Cache-Control"])

    def test_signing_in_shows_the_administrator_and_management_links(self):
        response = self.sign_in(email="  Merci@Example.com ")  # case and spaces don't matter
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/manage?notice=signed-in")
        page = self.client.get(response["Location"]).content.decode()
        self.assertIn("signed in. You can now upload and manage photos.", page)
        self.assertIn("Merci RUYANGA", page)
        self.assertIn(">MR<", page)
        self.assertIn("Administrator", page)
        self.assertIn('href="/manage"', page)
        header = page.split("</header>", 1)[0]
        self.assertNotIn('href="/upload"', header)  # upload lives in the dashboard
        self.assertIn('href="/upload"', page)
        self.assertIn('action="/sign-out"', page)

    def test_wrong_password_and_unknown_email_get_the_same_answer(self):
        for email, password in (("merci@example.com", "wrong-password"), ("nobody@example.com", PASSWORD)):
            response = self.sign_in(email=email, password=password)
            self.assertEqual(response.status_code, 400)
            self.assertIn("The email address or password is incorrect.", response.content.decode())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_disabled_accounts_cannot_sign_in(self):
        self.admin.is_active = False
        self.admin.save()
        self.assertEqual(self.sign_in().status_code, 400)

    def test_returns_to_the_requested_page_but_never_to_another_site(self):
        self.assertEqual(self.sign_in(next="/upload")["Location"], "/upload")
        self.client.post("/sign-out")
        for target in ("https://evil.example/", "//evil.example/", "/sign-in"):
            self.assertEqual(self.sign_in(next=target)["Location"], "/manage?notice=signed-in", target)
            self.client.post("/sign-out")

    def test_account_is_paused_after_repeated_failures(self):
        for _ in range(throttle.MAX_PER_EMAIL):
            self.sign_in(password="wrong-password")
        response = self.sign_in()  # even the right password is refused while paused
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many failed sign-in attempts", response.content.decode())
        FailedSignIn.objects.update(attempted_at="2000-01-01T00:00:00Z")  # the pause has passed
        self.assertEqual(self.sign_in().status_code, 302)

    def test_success_clears_the_failure_count(self):
        for _ in range(throttle.MAX_PER_EMAIL - 1):
            self.sign_in(password="wrong-password")
        self.sign_in()
        self.assertFalse(FailedSignIn.objects.filter(email="merci@example.com").exists())

    def test_one_address_guessing_many_accounts_is_paused(self):
        headers = {"HTTP_X_FORWARDED_FOR": "203.0.113.7, 130.176.0.1"}  # viewer, CloudFront
        for n in range(throttle.MAX_PER_IP):
            self.client.post("/sign-in", {"username": f"guess{n}@example.com", "password": "x"}, **headers)
        response = self.client.post("/sign-in", {"username": "merci@example.com", "password": PASSWORD}, **headers)
        self.assertEqual(response.status_code, 429)
        other = self.client.post("/sign-in", {"username": "merci@example.com", "password": PASSWORD},
                                 HTTP_X_FORWARDED_FOR="198.51.100.9, 130.176.0.1")
        self.assertEqual(other.status_code, 302)

    def test_sign_out_needs_a_post(self):
        self.sign_in()
        self.assertEqual(self.client.get("/sign-out").status_code, 405)
        response = self.client.post("/sign-out")
        self.assertEqual(response["Location"], "/?notice=signed-out")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn('href="/sign-in"', self.client.get("/").content.decode())

    def test_session_key_changes_at_sign_in(self):
        self.client.get("/sign-in")
        self.client.session.save()
        before = self.client.session.session_key
        self.sign_in()
        self.assertNotEqual(self.client.session.session_key, before)


class ClientIpTests(TestCase):
    def ip(self, **meta):
        return throttle.client_ip(RequestFactory().get("/", **meta))

    def test_uses_the_address_cloudfront_saw(self):
        # A viewer can send its own X-Forwarded-For; CloudFront appends the real address, the ALB CloudFront's.
        self.assertEqual(self.ip(HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.7, 130.176.0.1"), "203.0.113.7")
        self.assertEqual(self.ip(HTTP_X_FORWARDED_FOR="203.0.113.7"), "203.0.113.7")
        self.assertEqual(self.ip(REMOTE_ADDR="10.0.0.5"), "10.0.0.5")
        self.assertIsNone(self.ip(HTTP_X_FORWARDED_FOR="not-an-ip, 130.176.0.1"))


class ViewerTests(MockedS3Mixin, TestCase):
    """Without signing in, photos can be viewed but not changed."""

    sign_in_as_admin = False

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.upload()
        self.client.post("/sign-out")
        self.photo = self.only_photo()

    def test_viewers_can_browse_live_photos(self):
        self.assertIn(self.photo.title, self.client.get("/").content.decode())
        page = self.client.get(f"/photos/{self.photo.id}")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertNotIn("/edit", body)
        self.assertNotIn("/delete", body)
        self.assertNotIn("Test Admin", body)  # who uploaded is for administrators

    def test_management_pages_ask_viewers_to_sign_in(self):
        for url in ("/upload", f"/photos/{self.photo.id}/edit", "/manage", "/deleted"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/sign-in?next="), url)
        for action in ("delete", "restore", "purge", "edit"):
            response = self.client.post(f"/photos/{self.photo.id}/{action}")
            self.assertEqual(response["Location"], "/sign-in", action)
        self.assertEqual(self.client.post("/upload", {"title": "x"})["Location"], "/sign-in")
        self.assertIsNone(Photo.objects.get().deleted_at)

    def test_viewers_cannot_see_deleted_photos(self):
        Photo.objects.update(deleted_at="2026-11-24T10:00:00Z")
        self.assertEqual(self.client.get(f"/photos/{self.photo.id}").status_code, 404)

    def test_signed_in_accounts_without_permission_get_403(self):
        user = User.objects.create_user(username="viewer@example.com", email="viewer@example.com", password=PASSWORD)
        self.client.force_login(user)
        response = self.client.get("/upload")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Only administrators can do this", response.content.decode())
        self.assertEqual(self.client.post(f"/photos/{self.photo.id}/delete").status_code, 403)


class RecordsWhoTests(MockedS3Mixin, TestCase):
    def test_upload_edit_and_delete_record_the_administrator(self):
        self.upload()
        photo = self.only_photo()
        self.assertEqual(photo.uploaded_by, "Test Admin")
        self.client.post(f"/photos/{photo.id}/edit", {
            "title": "New title", "description": photo.description, "merchant_name": photo.merchant_name,
            "rider_name": photo.rider_name, "delivery_city": photo.delivery_city,
            "captured_at": f"{photo.captured_at:%Y-%m-%dT%H:%M}", "reason": "Typo", "revision": 1})
        self.assertEqual(PhotoChange.objects.get().changed_by, "Test Admin")
        self.assertIn("Test Admin", self.client.get(f"/photos/{photo.id}").content.decode())

        self.client.post(f"/photos/{photo.id}/delete")
        photo.refresh_from_db()
        self.assertEqual(photo.deleted_by, "Test Admin")
        sidecar = self.read_json(photo.metadata_key)
        self.assertEqual((sidecar["schema"], sidecar["uploaded_by"], sidecar["deleted_by"]),
                         (3, "Test Admin", "Test Admin"))
        self.assertEqual(sidecar["history"][0]["changed_by"], "Test Admin")
        self.assertIn("by Test Admin", self.client.get("/deleted").content.decode())

        self.client.post(f"/photos/{photo.id}/restore")
        photo.refresh_from_db()
        self.assertEqual(photo.deleted_by, "")


class EnsureAdminTests(TestCase):
    ENV = {"ADMIN_EMAIL": " Merci.Ruyanga@Example.com ", "ADMIN_NAME": "Merci  RUYANGA", "ADMIN_PASSWORD": PASSWORD}

    def run_command(self, env=None, *args):
        out = StringIO()
        with mock.patch.dict(os.environ, env if env is not None else self.ENV, clear=False):
            call_command("ensure_admin", *args, stdout=out)
        return out.getvalue()

    def test_creates_the_administrator(self):
        with self.assertLogs("apps.accounts.management.commands.ensure_admin", "INFO") as logs:  # fields are loggable
            self.assertIn("created", self.run_command())
        self.assertIs(logs.records[0].account_created, True)
        user = User.objects.get()
        self.assertEqual((user.username, user.email), ("merci.ruyanga@example.com",) * 2)
        self.assertEqual((user.first_name, user.last_name), ("Merci", "RUYANGA"))
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(self.client.login(username="merci.ruyanga@example.com", password=PASSWORD))

    def test_running_again_changes_nothing_or_applies_a_new_password(self):
        self.run_command()
        self.assertIn("up to date", self.run_command())
        self.assertIn("password changed", self.run_command({**self.ENV, "ADMIN_PASSWORD": "Another-strong-pass-7"}))
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.get().check_password("Another-strong-pass-7"))

    def test_restores_a_disabled_or_demoted_administrator(self):
        self.run_command()
        User.objects.update(is_active=False, is_superuser=False)
        self.run_command()
        self.assertTrue(User.objects.get().is_superuser)

    def test_refuses_weak_passwords_and_bad_emails(self):
        with self.assertRaisesMessage(CommandError, "too weak"):
            self.run_command({**self.ENV, "ADMIN_PASSWORD": "short"})
        with self.assertRaisesMessage(CommandError, "not a valid email"):
            self.run_command({**self.ENV, "ADMIN_EMAIL": "not-an-email"})
        self.assertFalse(User.objects.exists())

    def test_skips_when_not_configured(self):
        empty = {"ADMIN_EMAIL": "", "ADMIN_PASSWORD": ""}
        self.assertIn("skipped", self.run_command(empty, "--if-configured"))
        with self.assertRaises(CommandError):
            self.run_command(empty)
        self.assertFalse(User.objects.exists())

