"""Canonical candidate-pair identity."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from vav.modules.recommendations.domain import canonical_pair, pair_direction

FIRST = UUID("11111111-1111-1111-1111-111111111111")
SECOND = UUID("22222222-2222-2222-2222-222222222222")


def test_pair_order_is_independent_of_argument_order() -> None:
    assert canonical_pair(FIRST, SECOND) == canonical_pair(SECOND, FIRST)
    assert canonical_pair(FIRST, SECOND) == (FIRST, SECOND)


def test_a_member_cannot_pair_with_themselves() -> None:
    with pytest.raises(ValueError):
        canonical_pair(FIRST, FIRST)


def test_direction_is_derived_from_the_canonical_order() -> None:
    assert pair_direction(FIRST, SECOND) == "low_to_high"
    assert pair_direction(SECOND, FIRST) == "high_to_low"


def test_normalisation_is_stable_across_random_identifiers() -> None:
    for _ in range(200):
        left, right = uuid4(), uuid4()
        assert canonical_pair(left, right) == canonical_pair(right, left)
        low, high = canonical_pair(left, right)
        assert str(low) < str(high)
