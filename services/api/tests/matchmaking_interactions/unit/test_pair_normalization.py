"""A pair is one unordered pair, whichever way round it is written."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from vav.modules.matchmaking_interactions.domain import canonical_pair, pair_direction

LOW = UUID("00000000-0000-0000-0000-00000000000a")
HIGH = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


def test_reversing_the_arguments_produces_the_same_pair() -> None:
    assert canonical_pair(LOW, HIGH) == canonical_pair(HIGH, LOW)


def test_the_low_identifier_comes_first() -> None:
    low, high = canonical_pair(HIGH, LOW)
    assert low == LOW
    assert high == HIGH


def test_ordering_matches_the_database_text_comparison() -> None:
    """Python and Postgres must agree, or a valid row would be refused.

    The database CHECK compares ``user_low_id::text < user_high_id::text``, so
    the ordering here is string ordering, not integer ordering of the UUID.
    """
    for _ in range(200):
        a, b = uuid4(), uuid4()
        low, high = canonical_pair(a, b)
        assert str(low) < str(high)


def test_a_member_cannot_pair_with_themselves() -> None:
    same = uuid4()
    with pytest.raises(ValueError):
        canonical_pair(same, same)


def test_direction_is_reported_from_the_actor() -> None:
    assert pair_direction(LOW, HIGH) == "low_to_high"
    assert pair_direction(HIGH, LOW) == "high_to_low"
