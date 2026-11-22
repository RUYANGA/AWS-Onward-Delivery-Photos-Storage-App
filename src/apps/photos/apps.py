from django.apps import AppConfig


class PhotosConfig(AppConfig):
    name = "apps.photos"
    label = "photos"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registers the S3 clean-up on delete)
