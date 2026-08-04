"""The baseline recommendation strategy manifest.

Every weight, threshold and policy lives in a versioned strategy record rather
than scattered across services, so a change is reviewable, reproducible and
reversible. Nothing here reads a raw profile: the only profile input is the
Batch 13 de-identified recommendation projection.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

STRATEGY_CODE = "baseline-bidirectional"
STRATEGY_SEMANTIC_VERSION = "1.0.0"
SCORING_POLICY_VERSION = "1.0.0"
EXPLANATION_POLICY_VERSION = "1.0.0"
HARD_CONSTRAINT_POLICY_VERSION = "1.0.0"

#: Preference importance to soft weight. REQUIRED never appears here — it is a
#: hard constraint and must not be double-counted as a soft signal.
IMPORTANCE_WEIGHTS: dict[str, int] = {
    "very_important": 100,
    "important": 70,
    "nice_to_have": 35,
    "no_preference": 0,
}

#: Criteria the platform may enforce as hard exclusions when the member marks
#: them as such. Anything outside this list is soft-only, whatever a member or
#: an operator asks for.
HARD_CONSTRAINT_CRITERIA: tuple[str, ...] = (
    "relationship_eligibility",
    "age_range",
    "country_code",
    "region_code",
    "city_code",
    "relocation_willingness",
    "language_codes",
    "faith_status_code",
    "church_tradition_codes",
    "marital_status_code",
    "open_to_partner_with_children",
    "has_children",
    "desire_children_code",
    "smoking_status_code",
    "relationship_intent",
)


def _feature(
    code: str,
    group: str,
    function: str,
    *,
    projection_field: str,
    preference_criterion: str | None = None,
    default_weight: int = 40,
    explainable: bool = True,
    user_configurable: bool = True,
    explanation_code: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "feature_code": code,
        "feature_group": group,
        "scoring_function_code": function,
        "projection_field": projection_field,
        "preference_criterion": preference_criterion,
        "default_weight": default_weight,
        "explainable": explainable,
        "user_configurable": user_configurable,
        "explanation_code": explanation_code or f"{code}_aligned",
        "sensitivity": "restricted"
        if group in {"faith_and_values", "family_and_parenting"}
        else "confidential",
        "options": options or {},
    }


FEATURE_MANIFEST: list[dict[str, Any]] = [
    _feature(
        "faith_status_alignment",
        "faith_and_values",
        "exact_match",
        projection_field="faith_codes",
        preference_criterion="faith_status_code",
        default_weight=90,
        explanation_code="shared_faith_status",
    ),
    _feature(
        "church_tradition_overlap",
        "faith_and_values",
        "set_overlap",
        projection_field="faith_codes",
        preference_criterion="church_tradition_codes",
        default_weight=60,
        explanation_code="shared_church_tradition",
    ),
    _feature(
        "faith_importance_distance",
        "faith_and_values",
        "ordered_distance",
        projection_field="faith_codes",
        preference_criterion="marriage_faith_importance",
        default_weight=70,
        explanation_code="similar_faith_priority",
        options={"scale_prefix": "marriage_faith_importance:", "maximum_distance": 4},
    ),
    _feature(
        "relationship_intent_alignment",
        "relationship_intent",
        "exact_match",
        projection_field="relationship_intent",
        preference_criterion="relationship_intent",
        default_weight=90,
        explanation_code="similar_relationship_goal",
    ),
    _feature(
        "geographic_compatibility",
        "location_and_relocation",
        "geographic_compatibility",
        projection_field="city_code",
        default_weight=80,
        explanation_code="workable_location",
    ),
    _feature(
        "language_overlap",
        "language",
        "set_overlap",
        projection_field="language_codes",
        preference_criterion="language_codes",
        default_weight=70,
        explanation_code="shared_language",
    ),
    _feature(
        "children_expectation_alignment",
        "family_and_parenting",
        "exact_match",
        projection_field="lifestyle_codes",
        preference_criterion="desire_children_code",
        default_weight=80,
        explanation_code="similar_family_expectation",
        options={"code_prefix": "desire_children_code:"},
    ),
    _feature(
        "marital_history_acceptance",
        "family_and_parenting",
        "exact_match",
        projection_field="marital_status_code",
        preference_criterion="marital_status_code",
        default_weight=50,
        explanation_code="acceptable_relationship_history",
    ),
    _feature(
        "daily_schedule_alignment",
        "lifestyle",
        "exact_match",
        projection_field="lifestyle_codes",
        preference_criterion="daily_schedule_code",
        default_weight=35,
        explanation_code="similar_daily_rhythm",
        options={"code_prefix": "daily_schedule_code:"},
    ),
    _feature(
        "smoking_alignment",
        "lifestyle",
        "exact_match",
        projection_field="lifestyle_codes",
        preference_criterion="smoking_status_code",
        default_weight=45,
        explanation_code="similar_lifestyle_choice",
        options={"code_prefix": "smoking_status_code:"},
    ),
    _feature(
        "alcohol_alignment",
        "lifestyle",
        "exact_match",
        projection_field="lifestyle_codes",
        default_weight=30,
        explanation_code="similar_lifestyle_choice",
        options={"code_prefix": "alcohol_use_code:"},
    ),
    _feature(
        "interest_overlap",
        "interests",
        "set_overlap",
        projection_field="lifestyle_codes",
        preference_criterion="leisure_interest_codes",
        default_weight=40,
        explanation_code="shared_interests",
        options={"code_prefix": "leisure_interest_codes:"},
    ),
    _feature(
        "communication_overlap",
        "communication",
        "set_overlap",
        projection_field="lifestyle_codes",
        preference_criterion="communication_preference_codes",
        default_weight=35,
        explanation_code="similar_communication_style",
        options={"code_prefix": "communication_preference_codes:"},
    ),
    _feature(
        "education_alignment",
        "education_and_work",
        "exact_match",
        projection_field="lifestyle_codes",
        preference_criterion="education_level_code",
        default_weight=30,
        explanation_code="similar_education_background",
        options={"code_prefix": "education_level_code:"},
    ),
    _feature(
        "age_preference_centrality",
        "relationship_intent",
        "range_match",
        projection_field="age_years",
        preference_criterion="age_range",
        default_weight=45,
        explanation_code="age_within_preferred_range",
    ),
    _feature(
        # Readiness only stabilises ranking and confidence. It is never a
        # judgement of the person.
        "profile_readiness",
        "profile_readiness",
        "readiness",
        projection_field="lifestyle_codes",
        default_weight=15,
        explainable=False,
        user_configurable=False,
        explanation_code="profile_detail_available",
    ),
]

SCORING_POLICY: dict[str, Any] = {
    "policy_version": SCORING_POLICY_VERSION,
    "importance_weights": IMPORTANCE_WEIGHTS,
    "missingness_policy": "ignore_and_lower_confidence",
    "minimum_effective_weight": 100,
    "confidence_floor_bps": 1000,
    # A single matching field must not produce a confident perfect score.
    "confidence_full_information_weight": 600,
    "prohibited_signals_are_rejected": True,
}

BIDIRECTIONAL_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    # An arithmetic mean would hide a 95/25 split; the harmonic mean does not.
    "combination_function": "harmonic_mean_with_minimum_floor",
    "minimum_directional_weight_bps": 3000,
    "balance_penalty_bps_per_10_percent_gap": 200,
}

HARD_CONSTRAINT_POLICY: dict[str, Any] = {
    "policy_version": HARD_CONSTRAINT_POLICY_VERSION,
    "criteria": list(HARD_CONSTRAINT_CRITERIA),
    "unknown_value_default": "lower_confidence",
    "auto_relaxation_enabled": False,
    "relaxable_criteria": ["country_code", "region_code", "city_code", "relocation_willingness"],
    "never_relaxable": [
        "adult_eligibility",
        "relationship_eligibility",
        "safety_block",
        "marital_status_explicit_rejection",
    ],
}

RANKING_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "primary_sort": ["adjusted_score_bps", "confidence_bps", "candidate_pair_id"],
    "novelty_bonus_bps": 300,
    "repeat_exposure_penalty_bps": 800,
    "popular_profile_penalty_bps": 600,
    "popular_profile_exposure_threshold": 30,
    "stable_within_batch": True,
}

DIVERSIFICATION_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "method": "maximal_marginal_relevance",
    "lambda_bps": 7000,
    "dimensions": ["city_code", "faith_codes", "lifestyle_codes"],
    "max_per_city": 4,
    # Diversification reorders qualified candidates; it never admits one.
    "may_bypass_hard_constraints": False,
}

EXPOSURE_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "count_impression_as_exposure": False,
    "visible_minimum_ms": 1000,
    "repeat_cooldown_days": 30,
    "membership_may_affect": ["daily_received_limit", "advanced_filters", "batch_frequency"],
    "membership_may_never_affect": [
        "other_party_hard_constraints",
        "safety_restrictions",
        "privacy_settings",
    ],
}

EXPLANATION_POLICY: dict[str, Any] = {
    "policy_version": EXPLANATION_POLICY_VERSION,
    "generation": "rule_and_template_only",
    "max_items_per_section": 4,
    "caveat": "推荐只是一个认识的机会，不代表平台对适配结果的保证。",
    "forbidden_disclosures": [
        "other_party_preference_criteria",
        "other_party_directional_score",
        "internal_feature_weights",
        "success_probability",
        "other_candidate_rankings",
        "other_party_past_rejections",
    ],
}

COLD_START_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "exploration_slot_count": 2,
    "new_profile_protection_days": 14,
    "new_profile_minimum_exposures": 5,
    "sparse_preference_threshold": 3,
    # Exploration varies the soft mix; it never bypasses eligibility.
    "exploration_must_pass_hard_constraints": True,
    "exploration_must_meet_minimum_bidirectional_score": True,
}


def strategy_payload() -> dict[str, Any]:
    """The full versioned strategy record persisted at seed time."""
    return {
        "strategy_code": STRATEGY_CODE,
        "semantic_version": STRATEGY_SEMANTIC_VERSION,
        "hard_constraint_policy": HARD_CONSTRAINT_POLICY,
        "feature_manifest": FEATURE_MANIFEST,
        "scoring_policy": SCORING_POLICY,
        "bidirectional_policy": BIDIRECTIONAL_POLICY,
        "ranking_policy": RANKING_POLICY,
        "diversification_policy": DIVERSIFICATION_POLICY,
        "exposure_policy": EXPOSURE_POLICY,
        "explanation_policy": EXPLANATION_POLICY,
        "cold_start_policy": COLD_START_POLICY,
    }


def feature_by_code(code: str) -> dict[str, Any] | None:
    for feature in FEATURE_MANIFEST:
        if feature["feature_code"] == code:
            return feature
    return None
