from __future__ import annotations

import pytest
from pydantic import ValidationError

from vav.core.config import Settings


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SKILL_REGISTRY_REQUIRE_SIGNATURE", "false"),
        ("SKILL_REGISTRY_ALLOW_UNVERIFIED", "true"),
        ("SKILL_DYNAMIC_PERMISSION_ESCALATION_DISABLED", "false"),
        ("SKILL_HIGH_RISK_PERMISSION_APPROVAL_REQUIRED", "false"),
        ("SKILL_SBOM_REQUIRED", "false"),
        ("SKILL_VULNERABILITY_SCAN_REQUIRED", "false"),
        ("SKILL_CRITICAL_VULNERABILITY_BLOCK", "false"),
        ("SKILL_SECRET_SCAN_REQUIRED", "false"),
        ("SKILL_MARKETPLACE_HUMAN_REVIEW_REQUIRED", "false"),
        ("SKILL_MARKETPLACE_PUBLIC_INSTALLS_ENABLED", "true"),
        ("SKILL_MARKETPLACE_AUTOMATED_PRICING_ENABLED", "true"),
    ],
)
def test_skill_security_controls_cannot_be_disabled(name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{name: value})  # type: ignore[arg-type]
