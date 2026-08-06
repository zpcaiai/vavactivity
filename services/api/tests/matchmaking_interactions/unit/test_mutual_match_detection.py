"""Match state rules that hold before any database is involved."""

from __future__ import annotations

import pytest

from vav.modules.matchmaking_interactions.domain import (
    MATCH_TRANSITIONS,
    MutualMatchStatus,
    can_transition,
)


def test_an_active_match_can_receive_an_invitation() -> None:
    assert can_transition(
        MATCH_TRANSITIONS, MutualMatchStatus.ACTIVE, MutualMatchStatus.INVITATION_PENDING
    )


def test_an_expired_invitation_can_return_the_match_to_active() -> None:
    assert can_transition(
        MATCH_TRANSITIONS, MutualMatchStatus.INVITATION_PENDING, MutualMatchStatus.ACTIVE
    )


def test_a_closed_match_is_final() -> None:
    assert MATCH_TRANSITIONS[MutualMatchStatus.CLOSED] == frozenset()


def test_a_match_cannot_skip_straight_to_accepted() -> None:
    """Acceptance requires an invitation that somebody actually sent."""
    assert not can_transition(
        MATCH_TRANSITIONS,
        MutualMatchStatus.ACTIVE,
        MutualMatchStatus.INTRODUCTION_ACCEPTED,
    )


def test_a_frozen_match_can_be_restored_after_review() -> None:
    """A freeze is a hold, not a verdict.

    An investigation that clears the pair must be able to put it back, which
    is why safety_frozen is not terminal.
    """
    assert can_transition(
        MATCH_TRANSITIONS, MutualMatchStatus.SAFETY_FROZEN, MutualMatchStatus.ACTIVE
    )


@pytest.mark.parametrize(
    "source",
    [
        MutualMatchStatus.ACTIVE,
        MutualMatchStatus.INVITATION_PENDING,
        MutualMatchStatus.INTRODUCTION_ACCEPTED,
    ],
)
def test_safety_can_freeze_from_any_live_state(source: MutualMatchStatus) -> None:
    assert can_transition(MATCH_TRANSITIONS, source, MutualMatchStatus.SAFETY_FROZEN)


def test_an_invalidated_match_is_final() -> None:
    assert MATCH_TRANSITIONS[MutualMatchStatus.INVALIDATED] == frozenset()


def test_every_status_is_covered() -> None:
    assert set(MATCH_TRANSITIONS) == set(MutualMatchStatus)
