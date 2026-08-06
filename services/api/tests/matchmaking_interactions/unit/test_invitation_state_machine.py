"""Invitation outcomes are mutually exclusive and final."""

from __future__ import annotations

import itertools

import pytest

from vav.modules.matchmaking_interactions.domain import (
    DECLINE_REASON_CODES,
    INVITATION_TRANSITIONS,
    InvitationStatus,
    can_transition,
)

FINAL = (
    InvitationStatus.ACCEPTED,
    InvitationStatus.DECLINED,
    InvitationStatus.CANCELLED,
    InvitationStatus.EXPIRED,
)


@pytest.mark.parametrize("target", FINAL)
def test_a_pending_invitation_can_reach_each_outcome(target: InvitationStatus) -> None:
    assert can_transition(INVITATION_TRANSITIONS, InvitationStatus.PENDING, target)


@pytest.mark.parametrize("first,second", list(itertools.permutations(FINAL, 2)))
def test_one_outcome_excludes_the_others(first: InvitationStatus, second: InvitationStatus) -> None:
    """Accept/cancel and accept/expire are the races this rules out.

    Once an invitation has landed on an outcome, no other outcome is reachable,
    so a slow worker or a stale client cannot rewrite what happened.
    """
    assert not can_transition(INVITATION_TRANSITIONS, first, second)


def test_a_declined_invitation_can_never_become_accepted() -> None:
    assert not can_transition(
        INVITATION_TRANSITIONS, InvitationStatus.DECLINED, InvitationStatus.ACCEPTED
    )


def test_only_acceptance_survives_into_invalidation() -> None:
    """An accepted introduction can still be invalidated by a later block."""
    assert can_transition(
        INVITATION_TRANSITIONS, InvitationStatus.ACCEPTED, InvitationStatus.INVALIDATED
    )
    assert INVITATION_TRANSITIONS[InvitationStatus.DECLINED] == frozenset()


def test_prefer_not_to_say_is_an_allowed_decline_reason() -> None:
    assert "prefer_not_to_say" in DECLINE_REASON_CODES


def test_every_status_is_covered() -> None:
    assert set(INVITATION_TRANSITIONS) == set(InvitationStatus)
