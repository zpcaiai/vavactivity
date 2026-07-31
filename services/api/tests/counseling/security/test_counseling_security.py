import time

import pytest

from vav.common.exceptions import VavError
from vav.modules.courses.crypto import (
    decrypt_sensitive,
    encrypt_sensitive,
    issue_playback_token,
    verify_playback_token,
)


def test_counseling_intake_and_private_records_are_encrypted() -> None:
    source = {"relationship_context": "private", "risk_note": "sensitive"}
    encrypted = encrypt_sensitive(source)
    assert "private" not in encrypted
    assert "sensitive" not in encrypted
    assert decrypt_sensitive(encrypted) == source


def test_join_token_is_short_lived_and_bound_to_user_and_session() -> None:
    bound = "counseling:session-a:user-a"
    token = issue_playback_token(bound, expires_at=int(time.time()) + 30)
    verify_playback_token(token, session_id=bound)
    with pytest.raises(VavError):
        verify_playback_token(token, session_id="counseling:session-a:user-b")
    with pytest.raises(VavError, match="expired"):
        verify_playback_token(token, session_id=bound, now=int(time.time()) + 31)


def test_public_contract_never_exposes_private_fields(client) -> None:
    response = client.get("/api/v1/public/counseling/services?locale=zh-CN")
    assert response.status_code == 200
    for forbidden in (
        "intake_response_encrypted",
        "meeting_reference_encrypted",
        "private_location_encrypted",
        "details_encrypted",
        "mentor_note",
    ):
        assert forbidden not in response.text
