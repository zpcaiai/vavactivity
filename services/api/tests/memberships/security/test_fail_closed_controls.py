from pathlib import Path

import pytest
from pydantic import ValidationError

from vav.core.config import Settings


def test_unsafe_entitlement_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(MEMBERSHIP_REQUIRE_ACTIVE_ENTITLEMENT="false")
    with pytest.raises(ValidationError):
        Settings(MEMBERSHIP_MANUAL_GRANT_APPROVAL_REQUIRED="false")


def test_sensitive_admin_reasons_are_encrypted_and_not_published() -> None:
    admin = (Path(__file__).parents[3] / "src/vav/modules/memberships/admin_router.py").read_text(
        encoding="utf-8"
    )
    projection = (
        Path(__file__).parents[3] / "src/vav/modules/memberships/projection.py"
    ).read_text(encoding="utf-8")
    assert "encrypt_private(payload.reason)" in admin
    assert "reason_encrypted" not in projection
