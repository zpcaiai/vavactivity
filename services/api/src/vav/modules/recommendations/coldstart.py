"""Cold start, exploration slots and new-profile protection.

A new member is served from their explicit preferences and transparent
defaults. The platform never substitutes inferred taste, appearance
prediction, spend or private conversation content for missing data.
"""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from vav.modules.recommendations.domain import ColdStartType
from vav.modules.recommendations.strategy import COLD_START_POLICY


def classify(
    *,
    account_created_at: datetime,
    profile_approved_at: datetime | None,
    criteria_count: int,
    pool_size_in_region: int,
    interaction_count: int,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """Return every cold-start condition that applies to this member."""
    settings = policy or COLD_START_POLICY
    reference = now or datetime.now(UTC)
    protection_days = int(settings["new_profile_protection_days"])
    types: list[str] = []

    if account_created_at > reference - timedelta(days=protection_days):
        types.append(ColdStartType.NEW_USER.value)
    if profile_approved_at is not None and profile_approved_at > reference - timedelta(
        days=protection_days
    ):
        types.append(ColdStartType.NEW_PROFILE.value)
    if criteria_count < int(settings["sparse_preference_threshold"]):
        types.append(ColdStartType.SPARSE_PREFERENCES.value)
    if pool_size_in_region < 25:
        types.append(ColdStartType.SPARSE_REGION.value)
    if interaction_count == 0:
        types.append(ColdStartType.NO_INTERACTION_HISTORY.value)
    return types


def exploration_slot_count(
    cold_start_types: list[str],
    exploration_level: str,
    policy: dict[str, Any] | None = None,
) -> int:
    settings = policy or COLD_START_POLICY
    base = int(settings["exploration_slot_count"])
    if exploration_level == "focused":
        base = max(0, base - 1)
    elif exploration_level == "open":
        base += 2
    if ColdStartType.SPARSE_PREFERENCES.value in cold_start_types:
        base += 1
    return base


def select_exploration_candidates(
    qualified: list[dict[str, Any]],
    *,
    already_selected_ids: set[str],
    slots: int,
    minimum_bidirectional_bps: int,
    exploration_bonus_bps: int = 400,
) -> list[dict[str, Any]]:
    """Pick exploration candidates from the *qualified* pool only.

    Exploration varies the soft mix; it never bypasses hard constraints,
    safety, privacy or the minimum bidirectional score.
    """
    if slots <= 0:
        return []
    eligible = [
        candidate
        for candidate in qualified
        if str(candidate["candidate_pair_id"]) not in already_selected_ids
        and int(candidate["bidirectional_score_bps"]) >= minimum_bidirectional_bps
        and candidate.get("hard_constraints_passed", True)
        and candidate.get("safety_allowed", True)
    ]
    # Prefer profiles nobody has seen yet, then the newest approved profiles.
    eligible.sort(
        key=lambda candidate: (
            0 if candidate.get("never_exposed") else 1,
            -int(candidate.get("profile_recency_score", 0)),
            str(candidate["candidate_pair_id"]),
        )
    )
    chosen = eligible[:slots]
    for candidate in chosen:
        candidate["is_exploration_slot"] = True
        candidate["exploration_adjustment_bps"] = exploration_bonus_bps
    return chosen


def new_profile_needs_exposure(
    *,
    profile_approved_at: datetime | None,
    exposure_count: int,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> bool:
    """A newly approved profile gets a floor of exposure among qualified matches."""
    settings = policy or COLD_START_POLICY
    if profile_approved_at is None:
        return False
    reference = now or datetime.now(UTC)
    within_window = profile_approved_at > reference - timedelta(
        days=int(settings["new_profile_protection_days"])
    )
    return within_window and exposure_count < int(settings["new_profile_minimum_exposures"])


def preference_guidance(
    criteria_count: int, policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Non-coercive guidance shown when preferences are sparse."""
    settings = policy or COLD_START_POLICY
    threshold = int(settings["sparse_preference_threshold"])
    if criteria_count >= threshold:
        return {"needed": False, "messages": []}
    return {
        "needed": True,
        "messages": [
            f"补充 {threshold}-5 个重要条件可以改善推荐解释",
            "你可以把条件设为“硬性”“重要”或“无偏好”",
            "所有敏感字段都可以选择不填写",
        ],
        "mandatory_fields": [],
    }


def empty_result_guidance(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Explain an empty batch honestly instead of manufacturing candidates."""
    blocking = diagnostics.get("blocking_criteria", {})
    top = list(blocking.items())[:3]
    return {
        "message": "当前没有完全符合你全部硬性条件的推荐。",
        "largest_reductions": [
            {"criterion_code": code, "excluded_candidates": count} for code, count in top
        ],
        "options": [
            "调整或放宽部分硬性条件",
            "允许系统在候选不足时放宽你标记为可放宽的条件",
            "等待新的合格档案加入",
            "浏览相关活动或课程",
            "暂停推荐",
        ],
        "never_done": [
            "静默绕过硬性条件",
            "制造虚假推荐",
            "推荐已屏蔽的用户",
            "暗中修改你的偏好",
        ],
    }
