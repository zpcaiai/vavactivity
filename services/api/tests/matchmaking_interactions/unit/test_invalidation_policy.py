"""Which external signals invalidate, and what members are told about it."""

from __future__ import annotations

from vav.modules.matchmaking_interactions.domain import (
    INVALIDATION_REASON_CODES,
    MEMBER_SAFE_UNAVAILABLE_STATE,
)
from vav.modules.matchmaking_interactions.invalidation import FREEZE_REASONS, INBOX_REASONS


def test_every_inbox_event_maps_to_a_known_reason() -> None:
    assert set(INBOX_REASONS.values()) <= INVALIDATION_REASON_CODES


def test_the_specification_events_are_all_routed() -> None:
    expected = {
        "dating_profile.paused",
        "dating_profile.suspended",
        "dating_profile.archived",
        "dating_profile.privacy_updated",
        "user.account.suspended",
        "privacy.erasure.started",
        "moderation.block.created",
        "moderation.restriction.created",
        "moderation.report.high_risk",
        "relationship.journey.started",
    }
    assert expected <= set(INBOX_REASONS)


def test_safety_signals_freeze_rather_than_close() -> None:
    """A frozen pair stays reconstructable for an investigation.

    Closing it would also tell the blocked member that something happened,
    which is exactly what must not leak.
    """
    assert {"block_created", "restriction_created", "high_risk_report"} == FREEZE_REASONS
    assert FREEZE_REASONS <= INVALIDATION_REASON_CODES


def test_a_paused_profile_does_not_freeze_the_pair() -> None:
    """Pausing is a member's own scheduling choice, not a safety event."""
    assert "profile_paused" not in FREEZE_REASONS


def test_the_member_facing_state_carries_no_cause() -> None:
    """One neutral string, whatever actually happened."""
    assert MEMBER_SAFE_UNAVAILABLE_STATE == "no_longer_available"
    for leaky in ("block", "report", "suspend", "erasure", "restrict"):
        assert leaky not in MEMBER_SAFE_UNAVAILABLE_STATE


def test_internal_reasons_are_never_the_member_facing_state() -> None:
    assert MEMBER_SAFE_UNAVAILABLE_STATE not in INVALIDATION_REASON_CODES
