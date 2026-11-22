from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from apps.photos.management.commands.rebuild_catalogue import COPY_FIELDS, photo_from_sidecar
from apps.photos.models import Photo

from .helpers import MockedS3Mixin


class RebuildCatalogueTests(MockedS3Mixin, TestCase):
    def test_sidecar_round_trips_to_an_identical_row(self):
        self.upload()
        original = self.only_photo()
        rebuilt = photo_from_sidecar(self.read_json(original.metadata_key), original.metadata_key)
        for field in (*COPY_FIELDS, "id", "metadata_key", "captured_at", "created_at"):
            self.assertEqual(getattr(rebuilt, field), getattr(original, field), field)

    def test_command_restores_a_lost_row(self):
        self.upload()
        photo_id = self.only_photo().id
        Photo.objects.all().delete()  # simulate a lost database

        out = StringIO()
        call_command("rebuild_catalogue", bucket=settings.PHOTO_BUCKET, region=settings.AWS_REGION, stdout=out)
        self.assertIn("Restored 1 row(s)", out.getvalue())
        self.assertEqual(Photo.objects.get().id, photo_id)
