from django.test import TestCase, override_settings


class AboutPageTests(TestCase):
    def test_shows_student_and_lab(self):
        body = self.client.get("/about").content.decode()
        self.assertIn("Test Student", body)
        self.assertIn("Storing and Serving Delivery Photos for Onward Logistics", body)


class HealthTests(TestCase):
    def test_liveness_and_security_headers(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        page = self.client.get("/about")
        self.assertIn("frame-ancestors 'none'", page["Content-Security-Policy"])
        self.assertEqual(page["X-Frame-Options"], "DENY")
        self.assertEqual(page["X-Content-Type-Options"], "nosniff")

    def test_readiness_checks_database(self):
        self.assertEqual(self.client.get("/readyz").json()["database"], "ok")

    @override_settings(ALLOWED_HOSTS=["photos.example.com"])
    def test_liveness_answers_load_balancer_on_private_ip(self):
        self.assertEqual(self.client.get("/healthz", headers={"host": "10.20.10.5"}).status_code, 200)
        self.assertEqual(self.client.get("/about", headers={"host": "10.20.10.5"}).status_code, 400)


class ErrorPageTests(TestCase):
    def test_unknown_photo_shows_friendly_404(self):
        response = self.client.get("/photos/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertIn("may have been deleted", response.content.decode())
