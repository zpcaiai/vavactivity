"""Contact-exchange states and the protective default."""

from __future__ import annotations

from vav.core.config import get_settings
from vav.modules.matchmaking_interactions.contact_exchange import EXCHANGE_DISCLOSURES
from vav.modules.matchmaking_interactions.domain import (
    CONTACT_EXCHANGE_TRANSITIONS,
    ContactExchangePolicy,
    ContactExchangeStatus,
    can_transition,
)


def test_the_default_policy_requires_both_members() -> None:
    """The product policy is undecided, so the code holds the safe default."""
    assert (
        get_settings().matchmaking_contact_exchange_policy
        == ContactExchangePolicy.MUTUAL_CONFIRMATION_REQUIRED.value
    )


def test_one_sided_consent_cannot_reach_active() -> None:
    """This is the whole guarantee: one member agreeing opens nothing."""
    assert not can_transition(
        CONTACT_EXCHANGE_TRANSITIONS,
        ContactExchangeStatus.ONE_SIDE_CONSENTED,
        ContactExchangeStatus.ACTIVE,
    )


def test_active_is_reachable_only_through_mutual_consent() -> None:
    sources = [
        status
        for status, targets in CONTACT_EXCHANGE_TRANSITIONS.items()
        if ContactExchangeStatus.ACTIVE in targets
    ]
    assert set(sources) == {
        ContactExchangeStatus.MUTUALLY_CONSENTED,
        ContactExchangeStatus.PARTIALLY_REVOKED,
    }


def test_a_request_cannot_jump_to_active() -> None:
    assert not can_transition(
        CONTACT_EXCHANGE_TRANSITIONS,
        ContactExchangeStatus.REQUESTED,
        ContactExchangeStatus.ACTIVE,
    )


def test_revocation_is_reachable_from_every_live_state() -> None:
    for status in (
        ContactExchangeStatus.REQUESTED,
        ContactExchangeStatus.ONE_SIDE_CONSENTED,
        ContactExchangeStatus.MUTUALLY_CONSENTED,
        ContactExchangeStatus.ACTIVE,
        ContactExchangeStatus.PARTIALLY_REVOKED,
    ):
        assert can_transition(CONTACT_EXCHANGE_TRANSITIONS, status, ContactExchangeStatus.REVOKED)


def test_a_partial_revocation_can_be_restored() -> None:
    """One member re-confirming brings their own channels back."""
    assert can_transition(
        CONTACT_EXCHANGE_TRANSITIONS,
        ContactExchangeStatus.PARTIALLY_REVOKED,
        ContactExchangeStatus.ACTIVE,
    )


def test_the_disclosure_does_not_promise_deletion_elsewhere() -> None:
    """The platform must not imply a guarantee it cannot keep.

    Revocation stops future access. It cannot reach into what the other member
    already wrote down, and the text says so plainly.
    """
    joined = " ".join(EXCHANGE_DISCLOSURES).lower()
    assert "cannot delete" in joined
    assert "both of you confirm" in joined
    for overclaim in ("guarantee", "permanently erase", "remove it everywhere"):
        assert overclaim not in joined


def test_every_status_is_covered() -> None:
    assert set(CONTACT_EXCHANGE_TRANSITIONS) == set(ContactExchangeStatus)
