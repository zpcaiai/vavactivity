import pytest

from vav.common.exceptions import VavError
from vav.modules.content.media import ALLOWED_MEDIA_TYPES, media_service


@pytest.mark.asyncio
async def test_svg_is_not_in_default_media_allowlist() -> None:
    assert "image/svg+xml" not in ALLOWED_MEDIA_TYPES

    with pytest.raises(VavError) as error:
        await media_service.create_upload(
            None,  # type: ignore[arg-type]
            filename="unsafe.svg",
            mime_type="image/svg+xml",
            byte_size=128,
            checksum_sha256="a" * 64,
            visibility="private",
            actor_id=None,  # type: ignore[arg-type]
        )
    assert error.value.code == "MEDIA_TYPE_NOT_ALLOWED"
