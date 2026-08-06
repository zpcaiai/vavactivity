"""Skip cooldowns and the things a skip must never become."""

from __future__ import annotations

from datetime import UTC, datetime

from vav.modules.matchmaking_interactions.domain import (
    SKIP_REASON_CODES,
    SKIP_TRANSITIONS,
    SkipStatus,
    SkipType,
    can_transition,
    skip_cooldown_until,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_not_interested_waits_longer_than_not_now() -> None:
    short = skip_cooldown_until(SkipType.NOT_NOW, now=NOW, not_now_days=30, not_interested_days=180)
    long = skip_cooldown_until(
        SkipType.NOT_INTERESTED, now=NOW, not_now_days=30, not_interested_days=180
    )
    assert (short - NOW).days == 30
    assert (long - NOW).days == 180
    assert long > short


def test_a_cooldown_always_ends() -> None:
    """A skip delays a candidate; it never removes them permanently.

    Every skip type produces a finite cooldown, so there is no code path where
    skipping quietly becomes a lifetime block.
    """
    for skip_type in SkipType:
        until = skip_cooldown_until(skip_type, now=NOW, not_now_days=30, not_interested_days=180)
        assert until > NOW
        assert (until - NOW).days <= 180


def test_block_is_not_a_skip_type() -> None:
    """Blocking belongs to Batch 18 and is a different decision entirely."""
    assert "block" not in {member.value for member in SkipType}


def test_an_active_skip_can_be_undone_or_expire_or_be_superseded() -> None:
    for target in (SkipStatus.WITHDRAWN, SkipStatus.EXPIRED, SkipStatus.SUPERSEDED):
        assert can_transition(SKIP_TRANSITIONS, SkipStatus.ACTIVE, target)


def test_an_expired_skip_can_be_superseded_by_a_later_like() -> None:
    assert can_transition(SKIP_TRANSITIONS, SkipStatus.EXPIRED, SkipStatus.SUPERSEDED)


def test_a_withdrawn_skip_is_terminal() -> None:
    assert SKIP_TRANSITIONS[SkipStatus.WITHDRAWN] == frozenset()


def test_prefer_not_to_say_is_an_allowed_reason() -> None:
    """A member never has to explain themselves to keep using the product."""
    assert "prefer_not_to_say" in SKIP_REASON_CODES


def test_reason_codes_carry_no_judgement_about_the_other_member() -> None:
    """Codes describe fit, not the other person's worth.

    Anything resembling an assessment of the other member would end up in the
    recommendation engine as a quality signal, which is not what a skip means.
    """
    forbidden = {"unattractive", "ugly", "poor", "low_status", "bad_person"}
    assert forbidden.isdisjoint(SKIP_REASON_CODES)
