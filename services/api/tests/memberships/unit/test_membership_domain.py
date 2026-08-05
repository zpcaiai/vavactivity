from datetime import UTC, datetime

import pytest

from vav.modules.memberships.domain import (
    effective_policy,
    quota_remaining,
    validate_account_transition,
    validate_benefit,
)
from vav.modules.memberships.projection import _quota_window


def test_account_state_machine_rejects_terminal_reactivation() -> None:
    validate_account_transition("pending", "active")
    with pytest.raises(ValueError):
        validate_account_transition("revoked", "active")


def test_quota_remaining_never_allows_negative_state() -> None:
    assert quota_remaining(allocated=100, rollover=20, consumed=70, reserved=10) == 40
    with pytest.raises(ValueError):
        quota_remaining(allocated=10, rollover=0, consumed=8, reserved=3)


def test_governed_benefits_reject_safety_bypass_and_invalid_quota() -> None:
    with pytest.raises(ValueError):
        validate_benefit("safety.bypass", "capability", {"enabled": True})
    with pytest.raises(ValueError):
        validate_benefit("ai.message_quota", "quota", {"limit": -1, "period": "lifetime"})
    validate_benefit("ai.message_quota", "quota", {"limit": 10, "period": "membership_cycle"})


def test_change_policy_preserves_paid_period_on_downgrade() -> None:
    assert effective_policy("upgrade") == "immediate"
    assert effective_policy("downgrade") == "next_cycle"
    assert effective_policy("cancel") == "next_cycle"


def test_calendar_quota_windows_reset_at_authoritative_boundaries() -> None:
    start, end = _quota_window("calendar_month", datetime(2026, 12, 20, tzinfo=UTC), None)
    assert start == datetime(2026, 12, 1, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, tzinfo=UTC)
