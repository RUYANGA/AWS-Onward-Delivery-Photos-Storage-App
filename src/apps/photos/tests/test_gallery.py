from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.photos.models import Photo
from apps.photos.views import _page_numbers

from .helpers import MockedS3Mixin


class GalleryBrowsingTests(MockedS3Mixin, TestCase):
    sign_in_as_admin = True

    def setUp(self):
        super().setUp()
        for title, city in (("Kigali one", "Kigali"), ("Kigali two", "Kigali"), ("Huye one", "Huye")):
            self.upload(title=title, delivery_city=city)
        # spread the upload times so the order is unambiguous
        for n, photo in enumerate(Photo.objects.order_by("title")):
            Photo.objects.filter(pk=photo.pk).update(created_at=timezone.now() - timedelta(hours=n + 1))
        self.client.post("/sign-out")

    def test_filters_by_city_with_counts(self):
        body = self.client.get("/").content.decode()
        self.assertIn('city=Kigali" >Kigali <span class="chip-count">2</span>', body)
        filtered = self.client.get("/?city=kigali").content.decode()
        self.assertIn("Kigali one", filtered)
        self.assertNotIn("Huye one", filtered)
        self.assertIn("Clear filters", filtered)

    def test_sorts_newest_or_oldest(self):
        newest = self.client.get("/").context["photos"]
        oldest = self.client.get("/?sort=oldest").context["photos"]
        self.assertEqual([p.title for p in newest], [p.title for p in reversed(list(oldest))])

    def test_shows_relative_times_and_the_result_range(self):
        body = self.client.get("/").content.decode()
        self.assertIn("hours ago", body)
        self.assertIn("Showing <strong>1–3</strong> of <strong>3</strong> photos", body)

    @override_settings(PAGE_SIZE=1)
    def test_numbered_pages_keep_the_filters(self):
        body = self.client.get("/?city=Kigali&page=2").content.decode()
        self.assertIn('aria-current="page">2<', body)
        self.assertIn('href="?city=Kigali&amp;page=1"', body)

    def test_photo_page_steps_to_newer_and_older(self):
        middle = Photo.objects.order_by("-created_at")[1]
        response = self.client.get(f"/photos/{middle.id}")
        self.assertEqual(response.context["newer"], Photo.objects.order_by("-created_at")[0])
        self.assertEqual(response.context["older"], Photo.objects.order_by("-created_at")[2])
        body = response.content.decode()
        self.assertIn("Verify this photo", body)
        self.assertIn('data-copy="@url"', body)
        self.assertIn(" download=", body)


class PageNumberTests(TestCase):
    def numbers(self, current, last):
        page = type("P", (), {"number": current, "paginator": type("Q", (), {"num_pages": last})()})()
        return _page_numbers(page)

    def test_gaps(self):
        self.assertEqual(self.numbers(1, 3), [1, 2, 3])
        self.assertEqual(self.numbers(6, 12), [1, None, 5, 6, 7, None, 12])
        self.assertEqual(self.numbers(12, 12), [1, None, 11, 12])


class SearchTests(MockedS3Mixin, TestCase):
    def setUp(self):
        super().setUp()
        self.upload(title="Parcel left with reception", description="Signed for by the front desk.",
                    rider_name="Aline", delivery_city="Kigali")
        self.upload(title="Box at the gate", description="", rider_name="Eric", delivery_city="Huye",
                    merchant_name="Inzozi Books")

    def titles(self, query, url="/"):
        return sorted(p.title for p in self.client.get(url, {"q": query}).context["photos"])

    def test_title_words_in_any_order_and_case(self):
        self.assertEqual(self.titles("reception"), ["Parcel left with reception"])
        self.assertEqual(self.titles("RECEPTION parcel"), ["Parcel left with reception"])
        self.assertEqual(self.titles("recep"), ["Parcel left with reception"])  # part of a word

    def test_every_word_must_match_somewhere(self):
        self.assertEqual(self.titles("parcel kigali"), ["Parcel left with reception"])  # title + city
        self.assertEqual(self.titles("parcel huye"), [])

    def test_searches_description_rider_merchant_and_reference(self):
        self.assertEqual(self.titles("front desk"), ["Parcel left with reception"])
        self.assertEqual(self.titles("eric"), ["Box at the gate"])
        self.assertEqual(self.titles("inzozi"), ["Box at the gate"])
        reference = Photo.objects.get(title="Box at the gate").delivery_reference
        self.assertEqual(self.titles(reference.lower()), ["Box at the gate"])

    def test_dashboard_search_works_the_same(self):
        self.assertEqual(self.titles("gate eric", url="/manage"), ["Box at the gate"])
