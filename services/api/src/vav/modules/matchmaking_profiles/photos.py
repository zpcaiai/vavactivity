"""Private dating-photo processing.

Every uploaded image is decoded, stripped of metadata and re-encoded before
it can be reviewed. No biometric template is ever derived: quality checks are
non-identifying and advisory only.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import io
from typing import Any

from PIL import Image, UnidentifiedImageError

from vav.common.exceptions import VavError
from vav.core.config import get_settings

THUMBNAIL_SIZES: tuple[tuple[int, int], ...] = ((320, 320), (640, 640), (1280, 1280))
MIN_DIMENSION = 320

_MIME_TO_PIL = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def _reject(code: str, message: str) -> VavError:
    return VavError(code, message, status_code=422)


def validate_upload_request(mime_type: str, byte_size: int) -> None:
    settings = get_settings()
    if mime_type.casefold() not in settings.dating_photo_allowed_type_set:
        raise _reject(
            "DATING_PHOTO_TYPE_NOT_ALLOWED",
            "This image type is not accepted for profile photos.",
        )
    if byte_size <= 0 or byte_size > settings.dating_photo_max_size_mb * 1024 * 1024:
        raise _reject(
            "DATING_PHOTO_TOO_LARGE",
            f"Profile photos must be smaller than {settings.dating_photo_max_size_mb} MB.",
        )


def process_image(content: bytes, declared_mime_type: str) -> dict[str, Any]:
    """Decode, strip metadata and re-encode an uploaded profile photo.

    Returns the sanitised bytes plus a non-identifying processing report. A
    declared MIME type that does not match the decoded image is rejected, so
    a renamed executable or spoofed content type cannot pass.
    """
    settings = get_settings()
    validate_upload_request(declared_mime_type, len(content))

    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        source = Image.open(io.BytesIO(content))
    except (UnidentifiedImageError, OSError) as exc:
        raise _reject(
            "DATING_PHOTO_NOT_DECODABLE", "The uploaded file is not a readable image."
        ) from exc

    detected_format = (source.format or "").upper()
    expected_format = _MIME_TO_PIL.get(declared_mime_type.casefold())
    if expected_format is None or detected_format != expected_format:
        raise _reject(
            "DATING_PHOTO_TYPE_MISMATCH",
            "The image content does not match the declared image type.",
        )

    had_exif = bool(source.getexif()) or "exif" in source.info
    width, height = source.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise _reject(
            "DATING_PHOTO_RESOLUTION_TOO_LOW",
            f"Profile photos must be at least {MIN_DIMENSION}x{MIN_DIMENSION} pixels.",
        )

    converted = source.convert("RGB")
    # A fresh image built from raw pixel data carries no EXIF, GPS, ICC or
    # XMP metadata from the original file.
    sanitised = Image.new("RGB", converted.size)
    sanitised.putdata(list(converted.getdata()))

    buffer = io.BytesIO()
    sanitised.save(buffer, format="JPEG", quality=88, optimize=True)
    sanitised_bytes = buffer.getvalue()

    derivatives = []
    for target in THUMBNAIL_SIZES:
        if target[0] > max(width, height):
            continue
        thumbnail = sanitised.copy()
        thumbnail.thumbnail(target)
        thumbnail_buffer = io.BytesIO()
        thumbnail.save(thumbnail_buffer, format="JPEG", quality=82, optimize=True)
        derivatives.append(
            {
                "label": f"{target[0]}x{target[1]}",
                "width": thumbnail.width,
                "height": thumbnail.height,
                "byte_size": len(thumbnail_buffer.getvalue()),
            }
        )

    greyscale = sanitised.convert("L")
    raw_extrema = greyscale.getextrema()
    # A single-band image always yields a (min, max) pair.
    extrema: tuple[int, int] = (int(raw_extrema[0]), int(raw_extrema[1]))  # type: ignore[arg-type]
    mean_luminance = sum(greyscale.getdata()) / (width * height)

    report: dict[str, Any] = {
        "decoded": True,
        "source_format": detected_format,
        "output_format": "JPEG",
        "width": width,
        "height": height,
        "exif_present_before_processing": had_exif,
        "exif_removed": settings.dating_photo_strip_exif,
        "metadata_stripped": True,
        "derivatives": derivatives,
        "quality_flags": _quality_flags(extrema, mean_luminance, width, height),
        "biometric_template_created": False,
        "biometric_identification_enabled": (
            settings.dating_photo_biometric_identification_enabled
        ),
        "automated_findings_are_advisory": True,
    }

    source.close()
    return {
        "content": sanitised_bytes,
        "checksum_sha256": hashlib.sha256(sanitised_bytes).hexdigest(),
        "byte_size": len(sanitised_bytes),
        "width": width,
        "height": height,
        "report": report,
    }


def _quality_flags(
    extrema: tuple[int, int], mean_luminance: float, width: int, height: int
) -> list[str]:
    flags: list[str] = []
    if mean_luminance < 40:
        flags.append("image_too_dark")
    if mean_luminance > 225:
        flags.append("image_overexposed")
    if extrema[1] - extrema[0] < 25:
        flags.append("low_contrast")
    if width < 640 or height < 640:
        flags.append("low_resolution")
    return flags


def has_exif(content: bytes) -> bool:
    """Test helper: report whether raw image bytes still carry EXIF."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            return bool(image.getexif()) or "exif" in image.info
    except (UnidentifiedImageError, OSError):
        return False
