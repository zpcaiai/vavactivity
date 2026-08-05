from datetime import UTC, datetime
from uuid import UUID

import pytest

from vav.modules.matchmaking_interactions.domain import (
    INVITATION_TRANSITIONS,
    LIKE_TRANSITIONS,
    InvitationStatus,
    LikeStatus,
    SkipType,
    can_transition,
    canonical_pair,
    pair_direction,
    screen_invitation_message,
    skip_cooldown_until,
)


def test_pair_identity_is_canonical_and_directional() -> None:
    low = UUID("00000000-0000-0000-0000-000000000001")
    high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    assert canonical_pair(high, low) == (low, high)
    assert pair_direction(low, high) == "low_to_high"
    assert pair_direction(high, low) == "high_to_low"
    with pytest.raises(ValueError):
        canonical_pair(low, low)


def test_terminal_interaction_states_cannot_be_reopened() -> None:
    assert can_transition(LIKE_TRANSITIONS, LikeStatus.ACTIVE, LikeStatus.MATCHED)
    assert not can_transition(LIKE_TRANSITIONS, LikeStatus.MATCHED, LikeStatus.ACTIVE)
    assert can_transition(
        INVITATION_TRANSITIONS, InvitationStatus.PENDING, InvitationStatus.ACCEPTED
    )
    assert not can_transition(
        INVITATION_TRANSITIONS, InvitationStatus.ACCEPTED, InvitationStatus.PENDING
    )


@pytest.mark.parametrize(
    "message,code",
    [
        ("联系我 138-0013-8000", "phone_number"),
        ("邮箱 me@example.com", "email_address"),
        ("加微信 my-id", "messaging_handle"),
        ("去 https://example.com", "external_link"),
        ("请给我转账", "payment_or_investment"),
    ],
)
def test_invitation_screening_blocks_consent_bypasses(message: str, code: str) -> None:
    assert code in screen_invitation_message(message)


def test_skip_is_a_cooldown_not_a_permanent_block() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    assert (
        skip_cooldown_until(
            SkipType.NOT_NOW, now=now, not_now_days=30, not_interested_days=180
        )
        - now
    ).days == 30
