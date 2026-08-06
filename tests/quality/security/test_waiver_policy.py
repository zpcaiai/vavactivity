"""Waiver separation of duties, expiry and non-waivable protection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vav.modules.quality.domain import (
    NON_WAIVABLE_GATE_CODES,
    QualityPolicyError,
    validate_waiver,
)

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
REQUESTER = "11111111-1111-1111-1111-111111111111"
APPROVER = "22222222-2222-2222-2222-222222222222"
MITIGATION = {"monitoring": "quality_gate_failures_total", "rollback": "documented"}


def _validate(**overrides: object) -> None:
    payload: dict[str, object] = {
        "gate_code": "GATE-TEST-CRITICAL",
        "requested_by": REQUESTER,
        "approved_by": APPROVER,
        "valid_from": NOW,
        "expires_at": NOW + timedelta(days=14),
        "mitigation_conditions": MITIGATION,
        "now": NOW,
        "max_days": 30,
    }
    payload.update(overrides)
    validate_waiver(**payload)  # type: ignore[arg-type]


def test_ordinary_gate_can_be_waived() -> None:
    _validate()


@pytest.mark.parametrize("gate_code", sorted(NON_WAIVABLE_GATE_CODES))
def test_non_waivable_gates_cannot_be_waived(gate_code: str) -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(gate_code=gate_code)
    assert error.value.code == "QUALITY_WAIVER_FORBIDDEN"


def test_requester_cannot_approve_their_own_waiver() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(approved_by=REQUESTER)
    assert error.value.code == "QUALITY_WAIVER_SEPARATION_REQUIRED"


def test_unapproved_waiver_is_invalid() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(approved_by=None)
    assert error.value.code == "QUALITY_WAIVER_SEPARATION_REQUIRED"


def test_waiver_must_expire_in_the_future() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(expires_at=NOW - timedelta(hours=1))
    assert error.value.code == "QUALITY_WAIVER_EXPIRY_INVALID"


def test_already_expired_waiver_is_rejected_at_evaluation_time() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(
            valid_from=NOW - timedelta(days=20),
            expires_at=NOW - timedelta(days=1),
        )
    assert error.value.code == "QUALITY_WAIVER_EXPIRY_INVALID"


def test_waiver_cannot_exceed_the_maximum_duration() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(expires_at=NOW + timedelta(days=45))
    assert error.value.code == "QUALITY_WAIVER_EXPIRY_INVALID"


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(valid_from=datetime(2026, 8, 6, 12, 0))
    assert error.value.code == "QUALITY_WAIVER_TIME_INVALID"


def test_waiver_without_mitigation_is_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        _validate(mitigation_conditions={})
    assert error.value.code == "QUALITY_WAIVER_MITIGATION_REQUIRED"
