"""Pure membership rules shared by API and worker projections."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class MembershipAccountStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    TRIALING = "trialing"
    GRACE_PERIOD = "grace_period"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCEL_SCHEDULED = "cancel_scheduled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REVOKED = "revoked"


class MembershipCycleStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class MembershipChangeStatus(StrEnum):
    DRAFT = "draft"
    QUOTED = "quoted"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMED = "confirmed"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    APPLIED = "applied"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MembershipQuotaReservationStatus(StrEnum):
    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"


class MembershipBenefitType(StrEnum):
    CAPABILITY = "capability"
    RESOURCE_SCOPE = "resource_scope"
    QUOTA = "quota"
    LIMIT_OVERRIDE = "limit_override"
    PRICE_BENEFIT = "price_benefit"
    PRIORITY_ACCESS = "priority_access"


ACCOUNT_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"active", "trialing", "cancelled", "revoked"}),
    "active": frozenset({"past_due", "paused", "cancel_scheduled", "expired", "revoked"}),
    "trialing": frozenset({"active", "expired", "cancelled", "revoked"}),
    "past_due": frozenset({"grace_period", "active", "expired", "revoked"}),
    "grace_period": frozenset({"active", "expired", "revoked"}),
    "paused": frozenset({"active", "expired", "revoked"}),
    "cancel_scheduled": frozenset({"active", "cancelled", "expired"}),
    "cancelled": frozenset(),
    "expired": frozenset(),
    "revoked": frozenset(),
}

SAFETY_OVERRIDE_CODES = frozenset(
    {
        "safety.bypass",
        "privacy.bypass",
        "moderation.bypass",
        "matchmaking.hard_criteria_override",
        "matchmaking.block_override",
    }
)

REGISTERED_BENEFIT_CODES = frozenset(
    {
        "platform.basic_access",
        "ai.assistant.access",
        "ai.message_quota",
        "recommendation.daily_received_limit",
        "recommendation.advanced_filters",
        "recommendation.batch_frequency",
        "recommendation.feedback_personalization",
        "course.catalog_access",
        "course.category_access",
        "course.bundle_access",
        "activity.priority_registration",
        "activity.member_ticket_access",
        "counseling.booking_access",
        "counseling.discount_eligibility",
        "privacy.data_export_priority",
        "support.priority_queue",
    }
)


def validate_account_transition(current: str, target: str) -> None:
    if target not in ACCOUNT_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"invalid membership transition: {current} -> {target}")


def quota_remaining(*, allocated: int, rollover: int, consumed: int, reserved: int) -> int:
    values = (allocated, rollover, consumed, reserved)
    if any(value < 0 for value in values):
        raise ValueError("quota quantities cannot be negative")
    remaining = allocated + rollover - consumed - reserved
    if remaining < 0:
        raise ValueError("quota invariant violated")
    return remaining


def validate_benefit(code: str, benefit_type: str, value: dict[str, Any]) -> None:
    if code not in REGISTERED_BENEFIT_CODES:
        raise ValueError("benefit code is not in the governed registry")
    if code in SAFETY_OVERRIDE_CODES or code.endswith(".safety_override"):
        raise ValueError("benefits cannot bypass safety or privacy controls")
    if benefit_type == MembershipBenefitType.QUOTA:
        if not isinstance(value.get("limit"), int) or value["limit"] < 0:
            raise ValueError("quota benefit requires a non-negative integer limit")
        if value.get("period") not in {
            "membership_cycle",
            "calendar_day",
            "calendar_week",
            "calendar_month",
            "lifetime",
            "one_time",
        }:
            raise ValueError("quota benefit has an invalid period")
    if benefit_type == MembershipBenefitType.CAPABILITY and value.get("enabled") is not True:
        raise ValueError("capability benefits must explicitly set enabled=true")


def effective_policy(change_type: str) -> str:
    return "immediate" if change_type in {"upgrade", "reactivate"} else "next_cycle"
