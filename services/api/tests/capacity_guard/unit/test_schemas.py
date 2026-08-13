"""Capacity API payload tests for the explicit inventory mode."""

import pytest
from pydantic import ValidationError

from vav.modules.capacity_guard.schemas import CapacityAdjustRequest


def test_finite_zero_capacity_is_a_valid_sold_out_payload() -> None:
    payload = CapacityAdjustRequest(
        capacity=0,
        is_unlimited=False,
        reason="close bounded sales",
    )

    assert payload.capacity == 0
    assert payload.is_unlimited is False


def test_unlimited_mode_requires_zero_numeric_placeholder() -> None:
    with pytest.raises(ValidationError):
        CapacityAdjustRequest(
            capacity=10,
            is_unlimited=True,
            reason="invalid unlimited value",
        )


def test_mode_assertion_remains_optional_for_existing_clients() -> None:
    payload = CapacityAdjustRequest(capacity=5, reason="increase bounded capacity")

    assert payload.is_unlimited is None
