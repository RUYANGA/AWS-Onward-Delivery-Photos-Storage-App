from django import forms
from django.conf import settings

from .services.imaging import InvalidImage, process_image


def _limit(n):
    return {"max_length": f"Keep this under {n} characters."}


class PhotoUploadForm(forms.Form):
    """After is_valid(), ``photo_bytes`` and ``processed`` hold the validated image."""

    photo = forms.FileField(
        error_messages={
            "required": "Choose the delivery photo to upload.",
            "empty": "The file is empty. Choose a JPEG, PNG or WebP photo.",
        }
    )
    title = forms.CharField(
        max_length=120,
        error_messages={"required": "Enter a title, for example “Parcel left with reception”.", **_limit(120)},
    )
    description = forms.CharField(required=False, max_length=2000, error_messages=_limit(2000))
    merchant_name = forms.CharField(required=False, max_length=120, error_messages=_limit(120))
    rider_name = forms.CharField(required=False, max_length=120, error_messages=_limit(120))
    delivery_city = forms.CharField(required=False, max_length=80, error_messages=_limit(80))
    captured_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],  # <input type="datetime-local">, interpreted as UTC
        error_messages={"invalid": "Enter the time the photo was taken."},
    )

    def clean_photo(self):
        upload = self.cleaned_data["photo"]
        data = upload.read()
        try:
            self.processed = process_image(data, settings.THUMBNAIL_PX)
        except InvalidImage as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.photo_bytes = data
        return upload
