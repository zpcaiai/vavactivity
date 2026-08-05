"""Interaction vocabulary, state machines and the rules that never vary.

Three consents are modelled separately on purpose: expressing interest, being
formally invited, and agreeing to be contactable. Collapsing any two of them
would let one click imply a decision the member never made.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

# --------------------------------------------------------------------------
# Canonical pair identity
# --------------------------------------------------------------------------


def canonical_pair(user_a: UUID, user_b: UUID) -> tuple[UUID, UUID]:
    """Return the stable ``(low, high)`` ordering for two members.

    Ordering is derived from the identifiers themselves so that "A and B" is
    one pair regardless of who acted first. Text ordering is used because the
    database ``CHECK`` compares ``::text`` — the two must agree or a row that
    Python accepts would be refused by Postgres.
    """
    if user_a == user_b:
        raise ValueError("an interaction pair requires two different users")
    return (user_a, user_b) if str(user_a) < str(user_b) else (user_b, user_a)


def pair_direction(actor_id: UUID, target_id: UUID) -> str:
    """Which direction of the canonical pair this action travels."""
    low, _high = canonical_pair(actor_id, target_id)
    return "low_to_high" if actor_id == low else "high_to_low"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class InteractionSource(StrEnum):
    RECOMMENDATION = "recommendation"
    ACTIVITY_POST_EVENT = "activity_post_event"
    PROFILE_DETAIL = "profile_detail"
    MIGRATION = "migration"


#: Sources a member can actually act through in production. Liking an
#: arbitrary profile is a product policy that has not been approved, so
#: ``PROFILE_DETAIL`` stays defined but unreachable.
ENABLED_INTERACTION_SOURCES = frozenset(
    {InteractionSource.RECOMMENDATION, InteractionSource.ACTIVITY_POST_EVENT}
)


class PairStatus(StrEnum):
    PENDING = "pending"
    INTERACTING = "interacting"
    MUTUAL_MATCHED = "mutual_matched"
    RESTRICTED = "restricted"
    CLOSED = "closed"


class LikeStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    MATCHED = "matched"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class SkipStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class SkipType(StrEnum):
    NOT_NOW = "not_now"
    NOT_INTERESTED = "not_interested"
    NOT_RELEVANT = "not_relevant"


class MutualMatchStatus(StrEnum):
    ACTIVE = "active"
    INVITATION_PENDING = "invitation_pending"
    INTRODUCTION_ACCEPTED = "introduction_accepted"
    CLOSED = "closed"
    INVALIDATED = "invalidated"
    SAFETY_FROZEN = "safety_frozen"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ContactExchangeStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    ONE_SIDE_CONSENTED = "one_side_consented"
    MUTUALLY_CONSENTED = "mutually_consented"
    ACTIVE = "active"
    PARTIALLY_REVOKED = "partially_revoked"
    REVOKED = "revoked"
    INVALIDATED = "invalidated"


class ConsentStatus(StrEnum):
    PENDING = "pending"
    CONSENTED = "consented"
    PLATFORM_ONLY = "platform_only"
    WITHDRAWN = "withdrawn"
    STALE = "stale"


class GrantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ContactExchangePolicy(StrEnum):
    PLATFORM_ONLY = "platform_only"
    MUTUAL_CONFIRMATION_REQUIRED = "mutual_confirmation_required"
    AUTOMATIC_AFTER_INVITATION_ACCEPTED = "automatic_after_invitation_accepted"


# --------------------------------------------------------------------------
# State machines
# --------------------------------------------------------------------------

#: A matched like is deliberately terminal. Deleting it would let a member
#: unwind a match by removing its cause instead of going through the match
#: lifecycle, which is what the other member actually consented to.
LIKE_TRANSITIONS: dict[LikeStatus, frozenset[LikeStatus]] = {
    LikeStatus.ACTIVE: frozenset(
        {LikeStatus.WITHDRAWN, LikeStatus.MATCHED, LikeStatus.INVALIDATED, LikeStatus.EXPIRED}
    ),
    LikeStatus.MATCHED: frozenset({LikeStatus.INVALIDATED}),
    LikeStatus.WITHDRAWN: frozenset(),
    LikeStatus.INVALIDATED: frozenset(),
    LikeStatus.EXPIRED: frozenset(),
}

SKIP_TRANSITIONS: dict[SkipStatus, frozenset[SkipStatus]] = {
    SkipStatus.ACTIVE: frozenset({SkipStatus.WITHDRAWN, SkipStatus.EXPIRED, SkipStatus.SUPERSEDED}),
    SkipStatus.WITHDRAWN: frozenset(),
    SkipStatus.EXPIRED: frozenset({SkipStatus.SUPERSEDED}),
    SkipStatus.SUPERSEDED: frozenset(),
}

MATCH_TRANSITIONS: dict[MutualMatchStatus, frozenset[MutualMatchStatus]] = {
    MutualMatchStatus.ACTIVE: frozenset(
        {
            MutualMatchStatus.INVITATION_PENDING,
            MutualMatchStatus.CLOSED,
            MutualMatchStatus.INVALIDATED,
            MutualMatchStatus.SAFETY_FROZEN,
        }
    ),
    MutualMatchStatus.INVITATION_PENDING: frozenset(
        {
            MutualMatchStatus.INTRODUCTION_ACCEPTED,
            MutualMatchStatus.ACTIVE,
            MutualMatchStatus.CLOSED,
            MutualMatchStatus.INVALIDATED,
            MutualMatchStatus.SAFETY_FROZEN,
        }
    ),
    MutualMatchStatus.INTRODUCTION_ACCEPTED: frozenset(
        {
            MutualMatchStatus.CLOSED,
            MutualMatchStatus.INVALIDATED,
            MutualMatchStatus.SAFETY_FROZEN,
        }
    ),
    MutualMatchStatus.SAFETY_FROZEN: frozenset(
        {MutualMatchStatus.INVALIDATED, MutualMatchStatus.CLOSED, MutualMatchStatus.ACTIVE}
    ),
    MutualMatchStatus.CLOSED: frozenset(),
    MutualMatchStatus.INVALIDATED: frozenset(),
}

#: Accept, decline, cancel and expire are mutually exclusive final outcomes.
INVITATION_TRANSITIONS: dict[InvitationStatus, frozenset[InvitationStatus]] = {
    InvitationStatus.PENDING: frozenset(
        {
            InvitationStatus.ACCEPTED,
            InvitationStatus.DECLINED,
            InvitationStatus.CANCELLED,
            InvitationStatus.EXPIRED,
            InvitationStatus.INVALIDATED,
        }
    ),
    InvitationStatus.ACCEPTED: frozenset({InvitationStatus.INVALIDATED}),
    InvitationStatus.DECLINED: frozenset(),
    InvitationStatus.CANCELLED: frozenset(),
    InvitationStatus.EXPIRED: frozenset(),
    InvitationStatus.INVALIDATED: frozenset(),
}

CONTACT_EXCHANGE_TRANSITIONS: dict[ContactExchangeStatus, frozenset[ContactExchangeStatus]] = {
    ContactExchangeStatus.NOT_REQUESTED: frozenset({ContactExchangeStatus.REQUESTED}),
    ContactExchangeStatus.REQUESTED: frozenset(
        {
            ContactExchangeStatus.ONE_SIDE_CONSENTED,
            ContactExchangeStatus.REVOKED,
            ContactExchangeStatus.INVALIDATED,
        }
    ),
    ContactExchangeStatus.ONE_SIDE_CONSENTED: frozenset(
        {
            ContactExchangeStatus.MUTUALLY_CONSENTED,
            ContactExchangeStatus.REQUESTED,
            ContactExchangeStatus.REVOKED,
            ContactExchangeStatus.INVALIDATED,
        }
    ),
    ContactExchangeStatus.MUTUALLY_CONSENTED: frozenset(
        {
            ContactExchangeStatus.ACTIVE,
            ContactExchangeStatus.PARTIALLY_REVOKED,
            ContactExchangeStatus.REVOKED,
            ContactExchangeStatus.INVALIDATED,
        }
    ),
    ContactExchangeStatus.ACTIVE: frozenset(
        {
            ContactExchangeStatus.PARTIALLY_REVOKED,
            ContactExchangeStatus.REVOKED,
            ContactExchangeStatus.INVALIDATED,
        }
    ),
    ContactExchangeStatus.PARTIALLY_REVOKED: frozenset(
        {
            ContactExchangeStatus.ACTIVE,
            ContactExchangeStatus.REVOKED,
            ContactExchangeStatus.INVALIDATED,
        }
    ),
    ContactExchangeStatus.REVOKED: frozenset({ContactExchangeStatus.INVALIDATED}),
    ContactExchangeStatus.INVALIDATED: frozenset(),
}


def can_transition(table: dict[object, frozenset[object]], current: object, target: object) -> bool:
    """True when ``current -> target`` is a declared transition."""
    return target in table.get(current, frozenset())


# --------------------------------------------------------------------------
# Reason codes
# --------------------------------------------------------------------------

#: Why a member skipped. The free-text detail is encrypted separately; these
#: codes are the only part the recommendation engine ever learns.
SKIP_REASON_CODES = frozenset(
    {
        "distance",
        "life_stage",
        "faith_practice",
        "family_expectations",
        "lifestyle",
        "communication_style",
        "not_ready",
        "prefer_not_to_say",
        "other",
    }
)

#: Why a member declined an introduction. Stored for safety review and never
#: returned to the sender.
DECLINE_REASON_CODES = frozenset(
    {
        "not_ready",
        "changed_mind",
        "different_expectations",
        "distance",
        "already_seeing_someone",
        "felt_uncomfortable",
        "prefer_not_to_say",
        "other",
    }
)

#: Internal invalidation causes. These stay behind the sensitive-read
#: permission — the other member is told only that the introduction ended.
INVALIDATION_REASON_CODES = frozenset(
    {
        "profile_paused",
        "profile_suspended",
        "profile_archived",
        "privacy_updated",
        "account_suspended",
        "erasure_started",
        "block_created",
        "restriction_created",
        "high_risk_report",
        "relationship_started",
        "contact_changed",
        "moderation_unavailable",
        "admin_action",
    }
)

#: What a member is allowed to see when an interaction ends. One string, no
#: internal cause, no hint about who acted.
MEMBER_SAFE_UNAVAILABLE_STATE = "no_longer_available"


# --------------------------------------------------------------------------
# Invitation message screening
# --------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(
    r"[\w.+-]+\s*(?:@|\(at\)|\[at\]|＠)\s*[\w-]+\s*(?:\.|dot)\s*\w{2,}", re.I
)
#: Seven or more digits with optional separators catches phone numbers written
#: as 138-0013-8000 or 138 0013 8000 without flagging an ordinary year.
_PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().\-]{6,}\d)")
_URL_PATTERN = re.compile(r"(?:https?://|www\.|\w+\.(?:com|cn|net|org|io|me|app)\b)", re.I)
_HANDLE_PATTERN = re.compile(
    r"(?:微信|weixin|wechat|whatsapp|telegram|line\s*id|qq|instagram|ig\b|snapchat|скайп|skype)"
    r"\s*(?:号|id|:|：|是|＝|=)?",
    re.I,
)
_PAYMENT_PATTERN = re.compile(
    r"(?:转账|汇款|打款|红包|投资|理财|比特币|usdt|crypto|bitcoin|paypal|venmo|western\s*union|"
    r"wire\s*transfer|send\s+money|invest\s+with)",
    re.I,
)

MESSAGE_SCREENING_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email_address", _EMAIL_PATTERN),
    ("phone_number", _PHONE_PATTERN),
    ("external_link", _URL_PATTERN),
    ("messaging_handle", _HANDLE_PATTERN),
    ("payment_or_investment", _PAYMENT_PATTERN),
)


def screen_invitation_message(message: str) -> list[str]:
    """Return the rule codes a message violates.

    Contact details are blocked here because the exchange flow exists exactly
    so that sharing them is a separate, mutual, revocable decision. Letting a
    number through in free text would route around that consent entirely.
    """
    return [code for code, pattern in MESSAGE_SCREENING_RULES if pattern.search(message)]


# --------------------------------------------------------------------------
# Numbers and identifiers
# --------------------------------------------------------------------------


def match_number(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    return f"MM-{moment:%Y%m%d}-{uuid4().hex[:12].upper()}"


def invitation_number(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    return f"INV-{moment:%Y%m%d}-{uuid4().hex[:12].upper()}"


# --------------------------------------------------------------------------
# Cooldowns
# --------------------------------------------------------------------------


def skip_cooldown_until(
    skip_type: SkipType,
    *,
    now: datetime,
    not_now_days: int,
    not_interested_days: int,
) -> datetime:
    """When a skipped member may be recommended again.

    A skip is a scheduling signal, not a block: it delays the candidate and
    never removes them from anyone else's pool.
    """
    if skip_type is SkipType.NOT_INTERESTED:
        return now + timedelta(days=not_interested_days)
    if skip_type is SkipType.NOT_RELEVANT:
        return now + timedelta(days=not_now_days)
    return now + timedelta(days=not_now_days)


class CooldownType(StrEnum):
    SKIP = "skip"
    INVITATION_DECLINED = "invitation_declined"
    INVITATION_EXPIRED = "invitation_expired"
    MATCH_CLOSED = "match_closed"


__all__ = [
    "CONTACT_EXCHANGE_TRANSITIONS",
    "DECLINE_REASON_CODES",
    "ENABLED_INTERACTION_SOURCES",
    "INVALIDATION_REASON_CODES",
    "INVITATION_TRANSITIONS",
    "LIKE_TRANSITIONS",
    "MATCH_TRANSITIONS",
    "MEMBER_SAFE_UNAVAILABLE_STATE",
    "MESSAGE_SCREENING_RULES",
    "SKIP_REASON_CODES",
    "SKIP_TRANSITIONS",
    "ConsentStatus",
    "ContactExchangePolicy",
    "ContactExchangeStatus",
    "CooldownType",
    "GrantStatus",
    "InteractionSource",
    "InvitationStatus",
    "LikeStatus",
    "MutualMatchStatus",
    "PairStatus",
    "SkipStatus",
    "SkipType",
    "can_transition",
    "canonical_pair",
    "invitation_number",
    "match_number",
    "pair_direction",
    "screen_invitation_message",
    "skip_cooldown_until",
]
