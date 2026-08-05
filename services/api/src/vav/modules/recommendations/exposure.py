"""Exposure budgets, repeat-exposure cooldowns and popularity caps.

The rules here are pure so they can be unit tested; the concurrency-safe
counters live in the service layer, where they are updated inside a single
conditional UPDATE per budget row.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from vav.modules.recommendations.domain import RecommendationExposureType

EXPOSURE_POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class ExposurePolicy:
    daily_received_limit: int = 20
    daily_batch_size: int = 10
    daily_shown_limit_per_profile: int = 50
    repeat_exposure_cooldown_days: int = 30
    visible_min_ms: int = 1_000
    cold_start_minimum_exposures: int = 5

    def as_dict(self) -> dict[str, Any]:
        return {
            "daily_received_limit": self.daily_received_limit,
            "daily_batch_size": self.daily_batch_size,
            "daily_shown_limit_per_profile": self.daily_shown_limit_per_profile,
            "repeat_exposure_cooldown_days": self.repeat_exposure_cooldown_days,
            "visible_min_ms": self.visible_min_ms,
            "cold_start_minimum_exposures": self.cold_start_minimum_exposures,
            "policy_version": EXPOSURE_POLICY_VERSION,
        }


@dataclass(frozen=True)
class ExposureDecision:
    allowed: bool
    reason_code: str
    remaining_received: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "remaining_received": self.remaining_received,
        }


def remaining_daily_capacity(*, daily_received_limit: int, current_received_count: int) -> int:
    return max(0, daily_received_limit - current_received_count)


def can_receive(
    *,
    policy: ExposurePolicy,
    current_received_count: int,
    requested: int,
) -> ExposureDecision:
    """Decide how many more recommendations a member may receive today."""
    remaining = remaining_daily_capacity(
        daily_received_limit=policy.daily_received_limit,
        current_received_count=current_received_count,
    )
    if remaining <= 0:
        return ExposureDecision(False, "daily_received_limit_reached", 0)
    if requested > remaining:
        return ExposureDecision(True, "partially_granted", remaining)
    return ExposureDecision(True, "granted", remaining)


def can_show_profile(*, policy: ExposurePolicy, shown_count_today: int) -> ExposureDecision:
    """Popularity cap: a single profile cannot dominate everybody's list."""
    if shown_count_today >= policy.daily_shown_limit_per_profile:
        return ExposureDecision(False, "daily_shown_limit_reached")
    return ExposureDecision(True, "granted")


def cooldown_active(*, policy: ExposurePolicy, days_since_last_exposure: int | None) -> bool:
    if days_since_last_exposure is None:
        return False
    return days_since_last_exposure < policy.repeat_exposure_cooldown_days


def counts_as_visible(
    *, exposure_type: str, duration_ms: int | None, policy: ExposurePolicy
) -> bool:
    """A loaded card is not a seen card.

    ``CARD_IMPRESSION`` only records that the list rendered; a card counts as
    genuinely seen once it stayed visible for the configured minimum.
    """
    if exposure_type == RecommendationExposureType.CARD_IMPRESSION.value:
        return False
    if exposure_type in {
        RecommendationExposureType.PROFILE_OPENED.value,
        RecommendationExposureType.PHOTO_VIEWED.value,
    }:
        return True
    if exposure_type == RecommendationExposureType.CARD_VISIBLE.value:
        return duration_ms is not None and duration_ms >= policy.visible_min_ms
    return False


def idempotency_key(
    *,
    viewer_user_id: UUID,
    recommendation_item_id: UUID,
    exposure_type: str,
    occurred_at: datetime,
    bucket_seconds: int = 60,
) -> str:
    """Stable key so a retried client event is recorded exactly once."""
    bucket = int(occurred_at.timestamp() // bucket_seconds)
    material = f"{viewer_user_id}:{recommendation_item_id}:{exposure_type}:{bucket}".encode()
    return hashlib.sha256(material).hexdigest()[:64]


def budget_date_for(moment: datetime) -> date:
    return moment.date()


def exposure_coverage_ratio(*, exposed_profiles: int, eligible_profiles: int) -> int:
    if eligible_profiles <= 0:
        return 0
    return int(round(min(1.0, exposed_profiles / eligible_profiles) * 10_000))
