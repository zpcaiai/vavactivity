from io import BytesIO

from PIL import Image

from vav.modules.content.media import (
    DERIVATIVE_WIDTHS,
    detected_media_type,
    image_derivatives,
)


def test_real_media_signature_is_detected_independently_of_filename() -> None:
    assert detected_media_type(b"%PDF-1.7\n") == "application/pdf"
    assert detected_media_type(b"<script>alert(1)</script>") is None


def test_image_processing_validates_and_generates_all_sizes() -> None:
    source = BytesIO()
    Image.new("RGB", (800, 400), color=(35, 72, 93)).save(source, format="PNG")
    payload = source.getvalue()

    width, height, derivatives = image_derivatives(payload, "image/png")

    assert (width, height) == (800, 400)
    assert set(derivatives) == set(DERIVATIVE_WIDTHS)
    for derivative in derivatives.values():
        assert detected_media_type(derivative) == "image/webp"
