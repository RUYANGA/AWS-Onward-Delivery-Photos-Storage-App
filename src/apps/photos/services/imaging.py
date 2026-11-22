from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 60_000_000  # guards against decompression bombs

ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


class InvalidImage(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    content_type: str
    extension: str
    width: int
    height: int
    sha256: str
    thumbnail: bytes


def process_image(data: bytes, thumbnail_px: int = 480) -> ProcessedImage:
    """Validate the photo and make a WebP thumbnail. The original bytes are never modified (evidence)."""
    if not data:
        raise InvalidImage("The file is empty. Choose a JPEG, PNG or WebP photo.")
    try:
        with Image.open(BytesIO(data)) as probe:
            image_format = probe.format
            probe.verify()
        if image_format not in ALLOWED_FORMATS:
            raise InvalidImage("Only JPEG, PNG and WebP photos can be uploaded.")
        with Image.open(BytesIO(data)) as img:
            oriented = ImageOps.exif_transpose(img)
            width, height = oriented.size
            thumb = oriented.convert("RGB")
            thumb.thumbnail((thumbnail_px, thumbnail_px))
            buffer = BytesIO()
            thumb.save(buffer, "WEBP", quality=80, method=4)
    except InvalidImage:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImage("This file isn't a readable photo. Choose a JPEG, PNG or WebP file.") from exc

    content_type, extension = ALLOWED_FORMATS[image_format]
    return ProcessedImage(
        content_type=content_type,
        extension=extension,
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
        thumbnail=buffer.getvalue(),
    )
