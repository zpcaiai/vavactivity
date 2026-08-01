from __future__ import annotations

import pytest
from pydantic import ValidationError

from vav.common.exceptions import VavError
from vav.modules.privacy.crypto import decrypt_private, encrypt_private, mask_email, searchable_hmac
from vav.modules.privacy.schemas import PrivacySettingsUpdateRequest
from vav.modules.privacy.service import validate_memory_content


def test_private_values_encrypt_and_search_with_keyed_hmac() -> None:
    ciphertext = encrypt_private("secret@example.com")
    assert "secret@example.com" not in ciphertext
    assert decrypt_private(ciphertext) == "secret@example.com"
    assert searchable_hmac(" Secret@Example.com ") == searchable_hmac("secret@example.com")
    assert len(searchable_hmac("13800138000")) == 64


def test_masking_does_not_reveal_full_contact() -> None:
    masked = mask_email("private@example.com")
    assert masked.startswith("p***@")
    assert "private" not in masked


def test_strict_mode_rejects_broad_visibility() -> None:
    with pytest.raises(ValidationError):
        PrivacySettingsUpdateRequest(
            privacy_mode="strict",
            searchable_by_platform_users=True,
            visible_in_activity_directory=False,
            visible_in_matchmaking=False,
            allow_contact_exchange_after_mutual_confirmation=False,
            allow_profile_use_by_ai=False,
            allow_service_history_use_by_ai=False,
            settings_version=1,
        )


@pytest.mark.parametrize("content", ["my password is abc", "银行卡 CVV 123", "安全转介 details"])
def test_sensitive_content_cannot_become_ai_memory(content: str) -> None:
    with pytest.raises(VavError) as error:
        validate_memory_content(content)
    assert error.value.code == "AI_MEMORY_SENSITIVE_CONTENT_FORBIDDEN"
