"""Exposure budgets, repeat control and popular-profile protection.

Two independent budgets exist: how many recommendations a member *receives*
today, and how many times a profile may be *shown* to others today. A loaded
card is not an exposure — only a card that was actually visible long enough.
"""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from vav.modules.recommendations.domain import RecommendationExposureType


def counts_as_visible(
    exposure_type: str, duration_ms: int | None, *, minimum_visible_ms: int
) -> bool:
    """Distinguish a rendered card from one the member actually saw."""
    if exposure_type == RecommendationExposureType.CARD_IMPRESSION.value:
        return False
    if exposure_type == RecommendationExposureType.CARD_VISIBLE.value:
        return duration_ms is not None and duration_ms >= minimum_visible_ms
    # Opening a profile or a photo is an unambiguous view.
    return True


def remaining_received(budget: dict[str, Any] | None, limit: int) -> int:
    if budget is None:
        return limit
    return max(0, int(budget["daily_received_limit"]) - int(budget["current_received_count"]))


def can_show_profile(budget: dict[str, Any] | None, limit: int) -> bool:
    if budget is None:
        return True
    return int(budget["current_shown_count"]) < int(budget["daily_shown_limit"])


def in_repeat_cooldown(
    last_exposed_at: datetime | None, *, cooldown_days: int, now: datetime | None = None
) -> bool:
    if last_exposed_at is None:
        return False
    reference = now or datetime.now(UTC)
    return last_exposed_at > reference - timedelta(days=cooldown_days)


def exposure_fairness(exposure_counts: dict[str, int], eligible_user_count: int) -> dict[str, Any]:
    """Fairness is measured among *qualified* profiles only.

    Balancing exposure must never mean showing someone who fails the other
    party's stated conditions.
    """
    if eligible_user_count <= 0:
        return {
            "eligible_profiles": 0,
            "profiles_with_exposure": 0,
            "coverage_bps": 0,
            "never_exposed_count": 0,
            "max_exposure_share_bps": 0,
            "gini_bps": 0,
            "measured_within_qualified_candidates_only": True,
        }
    exposed = len([count for count in exposure_counts.values() if count > 0])
    total = sum(exposure_counts.values())
    values = sorted(exposure_counts.get(str(index), 0) for index in range(0)) or sorted(
        exposure_counts.values()
    )
    while len(values) < eligible_user_count:
        values.insert(0, 0)
    gini = 0
    if total > 0 and len(values) > 1:
        cumulative = 0
        weighted = 0
        for index, value in enumerate(values, start=1):
            cumulative += value
            weighted += index * value
        gini = round(
            (2 * weighted / (len(values) * total) - (len(values) + 1) / len(values)) * 10000
        )
    return {
        "eligible_profiles": eligible_user_count,
        "profiles_with_exposure": exposed,
        "coverage_bps": round(exposed * 10000 / eligible_user_count),
        "never_exposed_count": max(0, eligible_user_count - exposed),
        "max_exposure_share_bps": round(max(values, default=0) * 10000 / total) if total else 0,
        "gini_bps": max(0, gini),
        "measured_within_qualified_candidates_only": True,
    }


def popularity_suppressed(recent_exposure_count: int, threshold: int) -> bool:
    """Suppression limits new exposure; it never removes existing interactions."""
    return recent_exposure_count >= threshold
