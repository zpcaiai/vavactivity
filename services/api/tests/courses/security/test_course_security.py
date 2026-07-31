import time
from uuid import UUID

import pytest

from vav.common.exceptions import VavError
from vav.models.courses import CourseVideoAsset
from vav.modules.courses.crypto import (
    decrypt_sensitive,
    encrypt_sensitive,
    issue_playback_token,
    token_hash,
    verify_playback_token,
)
from vav.modules.courses.providers import FakePrivateVideoProvider


def test_sensitive_answers_and_provider_references_are_encrypted() -> None:
    value = {"answer": ["choice-a"], "provider": "s3://private/original.m3u8"}
    encrypted = encrypt_sensitive(value)
    assert "choice-a" not in encrypted
    assert "s3://" not in encrypted
    assert decrypt_sensitive(encrypted) == value


def test_playback_token_is_short_lived_bound_and_hashed() -> None:
    token = issue_playback_token("session-1", expires_at=int(time.time()) + 60)
    assert token_hash(token) != token
    verify_playback_token(token, session_id="session-1")
    with pytest.raises(VavError):
        verify_playback_token(token, session_id="session-2")
    with pytest.raises(VavError, match="expired"):
        verify_playback_token(token, session_id="session-1", now=int(time.time()) + 61)


@pytest.mark.asyncio
async def test_fake_provider_manifest_never_returns_private_reference() -> None:
    video = CourseVideoAsset(
        provider="fake_private",
        provider_environment="test",
        provider_video_id="provider-id",
        private_reference_encrypted=encrypt_sensitive({"value": "s3://private/original.m3u8"}),
        processing_status="ready",
        duration_seconds=120,
        playback_format="hls",
        created_by=UUID(int=1),
    )
    manifest = await FakePrivateVideoProvider().create_playback_manifest(video)
    assert manifest.asset_reference.startswith("private-asset:")
    assert "s3://" not in manifest.asset_reference
