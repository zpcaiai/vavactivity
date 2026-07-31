import time

import pytest

from vav.common.exceptions import VavError
from vav.modules.activities.crypto import (
    decrypt_private,
    encrypt_private,
    issue_checkin_token,
    verify_checkin_token,
)
from vav.modules.activities.domain import validate_form_response, validate_form_schema


def test_private_form_payload_is_encrypted_and_round_trips() -> None:
    value = {"expectations": "真实交流", "accepted_consents": ["rules-v1"]}
    encrypted = encrypt_private(value)
    assert "真实交流" not in encrypted
    assert decrypt_private(encrypted) == value


def test_checkin_token_is_signed_short_lived_and_contains_no_pii() -> None:
    token = issue_checkin_token("public-reference", expires_at=int(time.time()) + 60)
    assert "@" not in token
    assert verify_checkin_token(token) == "public-reference"
    with pytest.raises(VavError, match="expired"):
        verify_checkin_token(token, now=int(time.time()) + 61)
    with pytest.raises(VavError):
        verify_checkin_token(f"{token}tampered")


def test_form_schema_rejects_secret_and_script_collection() -> None:
    with pytest.raises(VavError) as forbidden:
        validate_form_schema(
            {"fields": [{"key": "passport_number", "type": "text"}]}, max_fields=10
        )
    assert forbidden.value.code == "ACTIVITY_FORM_FIELD_FORBIDDEN"
    with pytest.raises(VavError) as unsafe:
        validate_form_response(
            {"fields": [{"key": "intro", "type": "textarea"}]},
            {"intro": "<script>alert(1)</script>"},
            max_response_chars=1000,
        )
    assert unsafe.value.code == "ACTIVITY_FORM_VALUE_UNSAFE"


def test_form_response_enforces_types_and_declared_options() -> None:
    schema = {
        "fields": [
            {
                "key": "language",
                "type": "select",
                "options": [{"label": "中文", "value": "zh"}],
            },
            {"key": "directory_consent", "type": "checkbox"},
        ]
    }
    with pytest.raises(VavError) as option_error:
        validate_form_response(
            schema,
            {"language": "hidden-option", "directory_consent": True},
            max_response_chars=1000,
        )
    assert option_error.value.code == "ACTIVITY_FORM_OPTION_INVALID"
    with pytest.raises(VavError) as type_error:
        validate_form_response(
            schema,
            {"language": "zh", "directory_consent": "yes"},
            max_response_chars=1000,
        )
    assert type_error.value.code == "ACTIVITY_FORM_FIELD_TYPE_INVALID"
