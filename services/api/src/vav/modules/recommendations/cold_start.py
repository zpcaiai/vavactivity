"""Cold-start classification, transparent defaults and honest empty results.

Cold start never guesses hidden preferences. It relies on what the member
explicitly published, applies the platform's transparent default weights, and
says plainly when no candidate satisfies the conditions.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vav.modules.recommendations.domain import ColdStartType, ExplorationLevel

COLD_START_POLICY_VERSION = "1.0.0"

#: Below this number of stated criteria a member counts as sparse.
SPARSE_PREFERENCE_THRESHOLD = 3

#: Below this number of eligible profiles a region counts as sparse.
SPARSE_REGION_THRESHOLD = 25

#: Preference guidance shown when a member stated very little.
GUIDANCE_CODES: tuple[str, ...] = (
    "add_three_to_five_important_criteria",
    "mark_criteria_required_important_or_no_preference",
    "review_relaxable_criteria",
)

#: Alternatives offered when no candidate passes the member's own conditions.
EMPTY_RESULT_ACTIONS: tuple[str, ...] = (
    "review_most_restrictive_criteria",
    "enable_allowed_relaxations",
    "wait_for_new_profiles",
    "browse_activities_or_courses",
    "pause_recommendations",
)


@dataclass(frozen=True)
class ColdStartAssessment:
    types: list[str]
    exploration_slots: int
    uses_platform_defaults: bool
    guidance_codes: list[str] = field(default_factory=list)

    @property
    def is_cold_start(self) -> bool:
        return bool(self.types)

    def as_dict(self) -> dict[str, Any]:
        return {
            "types": self.types,
            "exploration_slots": self.exploration_slots,
            "uses_platform_defaults": self.uses_platform_defaults,
            "guidance_codes": self.guidance_codes,
            "policy_version": COLD_START_POLICY_VERSION,
        }


def exploration_slots_for(level: str, base_slots: int) -> int:
    if level == ExplorationLevel.CONSERVATIVE.value:
        return max(0, base_slots - 1)
    if level == ExplorationLevel.ADVENTUROUS.value:
        return base_slots + 2
    return base_slots


def assess(
    *,
    account_age_days: int,
    profile_approved_days: int | None,
    stated_criteria_count: int,
    eligible_profiles_in_region: int,
    interaction_count: int,
    exploration_level: str = ExplorationLevel.BALANCED.value,
    base_exploration_slots: int = 2,
) -> ColdStartAssessment:
    """Classify a member's cold-start situation without inspecting behaviour data."""
    types: list[str] = []
    if account_age_days <= 14:
        types.append(ColdStartType.NEW_USER.value)
    if profile_approved_days is not None and profile_approved_days <= 14:
        types.append(ColdStartType.NEW_PROFILE.value)
    if stated_criteria_count < SPARSE_PREFERENCE_THRESHOLD:
        types.append(ColdStartType.SPARSE_PREFERENCES.value)
    if eligible_profiles_in_region < SPARSE_REGION_THRESHOLD:
        types.append(ColdStartType.SPARSE_REGION.value)
    if interaction_count == 0:
        types.append(ColdStartType.NO_INTERACTION_HISTORY.value)

    slots = exploration_slots_for(exploration_level, base_exploration_slots)
    if ColdStartType.SPARSE_REGION.value in types:
        slots += 1

    guidance = list(GUIDANCE_CODES) if ColdStartType.SPARSE_PREFERENCES.value in types else []
    return ColdStartAssessment(
        types=types,
        exploration_slots=slots,
        uses_platform_defaults=ColdStartType.SPARSE_PREFERENCES.value in types,
        guidance_codes=guidance,
    )


def empty_result_report(
    *,
    pool_size: int,
    recalled: int,
    hard_constraint_failures: dict[str, int],
    safety_excluded: int,
    cooldown_excluded: int,
) -> dict[str, Any]:
    """Aggregate, member-safe explanation of why a list came back empty.

    The report never names another member and never reveals which account
    excluded whom; it only counts criteria.
    """
    ranked = sorted(hard_constraint_failures.items(), key=lambda item: (-item[1], item[0]))
    return {
        "eligible_pool_size": pool_size,
        "recalled_candidates": recalled,
        "most_restrictive_criteria": [
            {"criterion_code": code, "excluded_count": count} for code, count in ranked[:5]
        ],
        "safety_excluded_count": safety_excluded,
        "cooldown_excluded_count": cooldown_excluded,
        "available_actions": list(EMPTY_RESULT_ACTIONS),
        "policy_version": COLD_START_POLICY_VERSION,
    }
