from django import forms
from django.conf import settings

from .services.imaging import InvalidImage, process_image

DETAIL_FIELDS = ("title", "description", "merchant_name", "rider_name", "delivery_city", "captured_at")
CAPTURED_AT_FORMAT = "%Y-%m-%dT%H:%M"  # <input type="datetime-local">, interpreted as UTC


def _limit(n):
    return {"max_length": f"Keep this under {n} characters."}


class PhotoDetailsForm(forms.Form):
    """The delivery details shared by upload and edit."""

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
        input_formats=[CAPTURED_AT_FORMAT],
        error_messages={"invalid": "Enter the time the photo was taken."},
    )

    photo_required = True

    def clean_photo(self):
        """After is_valid(), ``photo_bytes`` and ``processed`` hold the validated image (or None)."""
        upload = self.cleaned_data.get("photo")
        self.photo_bytes = self.processed = None
        if not upload:
            return upload
        data = upload.read()
        try:
            self.processed = process_image(data, settings.THUMBNAIL_PX)
        except InvalidImage as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.photo_bytes = data
        return upload

    def details(self) -> dict:
        """Cleaned details as stored on the model (empty optional text is NULL, as in the table)."""
        values = {name: self.cleaned_data[name] for name in DETAIL_FIELDS}
        for name in ("merchant_name", "rider_name", "delivery_city"):
            values[name] = values[name] or None
        values["description"] = values["description"] or ""
        return values


class PhotoUploadForm(PhotoDetailsForm):
    photo = forms.FileField(
        error_messages={
            "required": "Choose the delivery photo to upload.",
            "empty": "The file is empty. Choose a JPEG, PNG or WebP photo.",
        }
    )


class PhotoEditForm(PhotoDetailsForm):
    """Edit a live photo. Every edit needs a reason; replacing the photo is optional."""

    photo = forms.FileField(
        required=False,
        error_messages={"empty": "The file is empty. Choose a JPEG, PNG or WebP photo."},
    )
    reason = forms.CharField(
        max_length=500,
        error_messages={
            "required": "Say why you're making this change, for example “Wrong merchant entered at upload”.",
            **_limit(500),
        },
    )
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)

    def __init__(self, *args, photo=None, **kwargs):
        self.photo_record = photo
        if photo is not None and "initial" not in kwargs:  # ignored for submitted data, used to prefill
            kwargs["initial"] = {
                **{name: getattr(photo, name) or "" for name in DETAIL_FIELDS},
                "captured_at": photo.captured_at.strftime(CAPTURED_AT_FORMAT) if photo.captured_at else "",
                "revision": photo.revision,
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if self.errors or self.photo_record is None:
            return cleaned
        unchanged = all(getattr(self.photo_record, k) == v for k, v in self.details().items())
        if unchanged and not cleaned.get("photo"):
            raise forms.ValidationError(
                "Nothing has changed. Edit a detail or choose a replacement photo.", code="unchanged"
            )
        return cleaned
