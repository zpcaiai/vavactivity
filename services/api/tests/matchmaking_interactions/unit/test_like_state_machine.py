"""Like transitions, including the ones that must not exist."""

from __future__ import annotations

import pytest

from vav.modules.matchmaking_interactions.domain import (
    LIKE_TRANSITIONS,
    LikeStatus,
    can_transition,
)


@pytest.mark.parametrize(
    "target",
    [LikeStatus.WITHDRAWN, LikeStatus.MATCHED, LikeStatus.INVALIDATED, LikeStatus.EXPIRED],
)
def test_an_active_like_can_reach_every_declared_outcome(target: LikeStatus) -> None:
    assert can_transition(LIKE_TRANSITIONS, LikeStatus.ACTIVE, target)


def test_a_matched_like_cannot_be_withdrawn() -> None:
    """Withdrawing a matched like would unwind a match by deleting its cause.

    The other member consented to the match, not to the like, so ending it is
    a match-lifecycle operation rather than a private deletion.
    """
    assert not can_transition(LIKE_TRANSITIONS, LikeStatus.MATCHED, LikeStatus.WITHDRAWN)


def test_a_matched_like_can_only_be_invalidated() -> None:
    assert LIKE_TRANSITIONS[LikeStatus.MATCHED] == frozenset({LikeStatus.INVALIDATED})


@pytest.mark.parametrize(
    "terminal", [LikeStatus.WITHDRAWN, LikeStatus.INVALIDATED, LikeStatus.EXPIRED]
)
def test_terminal_states_go_nowhere(terminal: LikeStatus) -> None:
    assert LIKE_TRANSITIONS[terminal] == frozenset()


def test_a_withdrawn_like_cannot_be_revived() -> None:
    """Re-liking creates a new row; it does not resurrect the old one.

    That keeps the history of what was expressed and when, which a safety
    review depends on.
    """
    assert not can_transition(LIKE_TRANSITIONS, LikeStatus.WITHDRAWN, LikeStatus.ACTIVE)


def test_every_status_is_covered() -> None:
    assert set(LIKE_TRANSITIONS) == set(LikeStatus)
