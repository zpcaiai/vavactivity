"""Recommendation feature registry, projection extraction and scoring functions.

Every feature is declared here with a code, version, group, sensitivity and a
deterministic scoring function. Nothing outside this registry may influence a
recommendation score, which is what keeps prohibited signals (appearance,
wealth, health, private conversations) structurally impossible.
"""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS, clamp_bps

FEATURE_REGISTRY_VERSION = "1.0.0"

#: Neutral score used when a policy asks for neutrality instead of omission.
NEUTRAL_BPS = 5_000


# --------------------------------------------------------------------------
# Projection value extraction
# --------------------------------------------------------------------------

#: Values stored inside ``lifestyle_codes`` as ``"<code>:<value>"`` entries.
PREFIXED_LIFESTYLE_CODES: frozenset[str] = frozenset(
    {
        "daily_schedule_code",
        "smoking_status_code",
        "alcohol_use_code",
        "exercise_frequency_code",
        "travel_frequency_code",
        "education_level_code",
        "occupation_category_code",
        "desire_children_code",
    }
)

#: List values stored inside ``lifestyle_codes`` as repeated prefixed entries.
PREFIXED_LIFESTYLE_LISTS: frozenset[str] = frozenset(
    {
        "leisure_interest_codes",
        "communication_preference_codes",
        "social_style_codes",
    }
)


def _prefixed(values: Sequence[str] | None, prefix: str) -> list[str]:
    if not values:
        return []
    marker = f"{prefix}:"
    return [str(value)[len(marker) :] for value in values if str(value).startswith(marker)]


def extract_value(projection: dict[str, Any], code: str) -> Any:
    """Return the normalised projection value for a criterion or feature code.

    Returns ``None`` when the value is unknown. Unknown is a first-class
    outcome: it is never silently converted into a failure or a zero score.
    """
    if code in PREFIXED_LIFESTYLE_CODES:
        found = _prefixed(projection.get("lifestyle_codes"), code)
        return found[0] if found else None
    if code in PREFIXED_LIFESTYLE_LISTS:
        found = _prefixed(projection.get("lifestyle_codes"), code)
        return found or None
    if code == "marriage_faith_importance":
        found = _prefixed(projection.get("faith_codes"), "marriage_faith_importance")
        if not found:
            return None
        try:
            return int(found[0])
        except ValueError:
            return None
    if code == "faith_status_code":
        return projection.get("faith_codes") or None
    if code == "church_tradition_codes":
        return projection.get("faith_codes") or None
    if code == "has_children":
        status = projection.get("children_status_code")
        if status is None:
            return None
        return status != "no_children"
    if code == "open_to_partner_with_children":
        return projection.get("children_status_code")
    if code == "age_range":
        return projection.get("age_years")
    if code in {
        "age_years",
        "age_bucket",
        "country_code",
        "region_code",
        "city_code",
        "gender_code",
        "eligible_partner_gender_codes",
        "relationship_intent",
        "marital_status_code",
        "children_status_code",
        "relocation_willingness",
        "language_codes",
        "faith_codes",
        "lifestyle_codes",
    }:
        value = projection.get(code)
        if isinstance(value, list) and not value:
            return None
        return value
    return None


# --------------------------------------------------------------------------
# Scoring functions
# --------------------------------------------------------------------------


def score_exact_match(desired: Any, actual: Any) -> int:
    if isinstance(desired, list | tuple | set):
        return 10_000 if actual in set(desired) else 0
    return 10_000 if desired == actual else 0


def score_set_overlap(desired: Any, actual: Any) -> int:
    """Normalised overlap between two code sets.

    The result is the share of the smaller set that is shared, which keeps a
    member with two interests comparable to a member with twenty.
    """
    left = {str(item) for item in _as_list(desired)}
    right = {str(item) for item in _as_list(actual)}
    if not left or not right:
        return 0
    shared = left & right
    return clamp_bps(len(shared) / min(len(left), len(right)) * 10_000)


def score_jaccard(desired: Any, actual: Any) -> int:
    left = {str(item) for item in _as_list(desired)}
    right = {str(item) for item in _as_list(actual)}
    if not left or not right:
        return 0
    union = left | right
    return clamp_bps(len(left & right) / len(union) * 10_000)


def score_ordered_distance(desired: Any, actual: Any, *, scale: int) -> int:
    """Distance on an ordered scale, normalised to basis points."""
    try:
        left = int(desired)
        right = int(actual)
    except (TypeError, ValueError):
        return 0
    if scale <= 0:
        return 0
    distance = min(abs(left - right), scale)
    return clamp_bps((1 - distance / scale) * 10_000)


def score_range_match(desired: Any, actual: Any) -> int:
    """Centrality of a value inside a preferred range.

    Hard ranges are enforced by the constraint engine; this only expresses how
    close the candidate sits to the middle of the member's preferred band.
    """
    bounds = _range_bounds(desired)
    if bounds is None or actual is None:
        return 0
    minimum, maximum = bounds
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return 0
    if maximum < minimum:
        return 0
    if value < minimum or value > maximum:
        return 0
    if maximum == minimum:
        return 10_000
    centre = (minimum + maximum) / 2
    half_width = (maximum - minimum) / 2
    return clamp_bps((1 - abs(value - centre) / half_width) * 10_000)


def score_geographic_compatibility(
    viewer: dict[str, Any], candidate: dict[str, Any]
) -> tuple[int, str]:
    """Geographic compatibility from city/region/country and relocation intent.

    Exact addresses never reach this function; only normalised location codes
    and the relocation willingness both members published.
    """
    viewer_city = viewer.get("city_code")
    candidate_city = candidate.get("city_code")
    viewer_region = viewer.get("region_code")
    candidate_region = candidate.get("region_code")
    viewer_country = viewer.get("country_code")
    candidate_country = candidate.get("country_code")

    if viewer_city and candidate_city and viewer_city == candidate_city:
        return 10_000, "same_city"
    if viewer_region and candidate_region and viewer_region == candidate_region:
        return 8_000, "same_region"

    relocation = {
        str(viewer.get("relocation_willingness") or "unknown"),
        str(candidate.get("relocation_willingness") or "unknown"),
    }
    open_to_move = relocation & {
        "willing",
        "open_to_relocation",
        "flexible",
        "willing_for_marriage",
    }

    if viewer_country and candidate_country and viewer_country == candidate_country:
        return (7_000 if open_to_move else 5_000), "same_country"
    if open_to_move:
        return 4_000, "cross_border_with_relocation"
    return 1_500, "distant_without_relocation"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]


def _range_bounds(desired: Any) -> tuple[float, float] | None:
    if isinstance(desired, dict):
        minimum = desired.get("min", desired.get("minimum"))
        maximum = desired.get("max", desired.get("maximum"))
    elif isinstance(desired, list | tuple) and len(desired) == 2:
        minimum, maximum = desired
    else:
        return None
    if minimum is None or maximum is None:
        return None
    try:
        return float(minimum), float(maximum)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Feature registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureDefinition:
    """A single approved, versioned and explainable recommendation feature."""

    feature_code: str
    feature_group: str
    scoring_function_code: str
    sensitivity: str
    explanation_code: str
    #: Partner-preference criterion supplying desired value and importance.
    criterion_code: str | None = None
    #: Projection code compared when the member set no explicit preference.
    similarity_code: str | None = None
    #: Platform default weight used when the member expressed no importance.
    default_weight: int = 30
    explainable: bool = True
    user_configurable: bool = True
    semantic_version: str = FEATURE_REGISTRY_VERSION
    #: Ordered scale size for ordered-distance features.
    scale: int = 4
    #: Features that only inform confidence never contribute to the score.
    confidence_only: bool = False
    value_schema: dict[str, Any] = field(default_factory=dict)


FEATURE_DEFINITIONS: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        feature_code="faith_status_alignment",
        feature_group="faith_and_values",
        scoring_function_code="set_overlap",
        sensitivity="restricted",
        explanation_code="shared_faith_background",
        criterion_code="faith_status_code",
        similarity_code="faith_codes",
        default_weight=70,
        value_schema={"type": "array", "items": {"type": "string"}},
    ),
    FeatureDefinition(
        feature_code="church_tradition_overlap",
        feature_group="faith_and_values",
        scoring_function_code="set_overlap",
        sensitivity="restricted",
        explanation_code="shared_church_tradition",
        criterion_code="church_tradition_codes",
        similarity_code="faith_codes",
        default_weight=50,
        value_schema={"type": "array", "items": {"type": "string"}},
    ),
    FeatureDefinition(
        feature_code="marriage_faith_importance_alignment",
        feature_group="faith_and_values",
        scoring_function_code="ordered_distance",
        sensitivity="restricted",
        explanation_code="similar_faith_importance",
        criterion_code="marriage_faith_importance",
        similarity_code="marriage_faith_importance",
        default_weight=60,
        scale=4,
        value_schema={"type": "integer", "minimum": 0, "maximum": 4},
    ),
    FeatureDefinition(
        feature_code="location_compatibility",
        feature_group="location_and_relocation",
        scoring_function_code="geographic_compatibility",
        sensitivity="confidential",
        explanation_code="location_compatible",
        similarity_code="city_code",
        default_weight=70,
        value_schema={"type": "object"},
    ),
    FeatureDefinition(
        feature_code="relocation_alignment",
        feature_group="location_and_relocation",
        scoring_function_code="exact_match",
        sensitivity="confidential",
        explanation_code="similar_relocation_openness",
        criterion_code="relocation_willingness",
        similarity_code="relocation_willingness",
        default_weight=35,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="relationship_intent_alignment",
        feature_group="relationship_intent",
        scoring_function_code="exact_match",
        sensitivity="controlled_public",
        explanation_code="similar_relationship_goals",
        criterion_code="relationship_intent",
        similarity_code="relationship_intent",
        default_weight=90,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="age_preference_centrality",
        feature_group="relationship_intent",
        scoring_function_code="range_match",
        sensitivity="controlled_public",
        explanation_code="age_within_preferred_range",
        criterion_code="age_range",
        default_weight=40,
        value_schema={"type": "object"},
    ),
    FeatureDefinition(
        feature_code="marital_status_alignment",
        feature_group="family_and_parenting",
        scoring_function_code="exact_match",
        sensitivity="restricted",
        explanation_code="relationship_history_compatible",
        criterion_code="marital_status_code",
        default_weight=50,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="children_expectation_alignment",
        feature_group="family_and_parenting",
        scoring_function_code="exact_match",
        sensitivity="restricted",
        explanation_code="similar_children_expectations",
        criterion_code="open_to_partner_with_children",
        similarity_code="children_status_code",
        default_weight=60,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="desire_children_alignment",
        feature_group="family_and_parenting",
        scoring_function_code="exact_match",
        sensitivity="restricted",
        explanation_code="similar_family_plans",
        criterion_code="desire_children_code",
        similarity_code="desire_children_code",
        default_weight=70,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="daily_schedule_alignment",
        feature_group="lifestyle",
        scoring_function_code="exact_match",
        sensitivity="confidential",
        explanation_code="similar_daily_rhythm",
        criterion_code="daily_schedule_code",
        similarity_code="daily_schedule_code",
        default_weight=30,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="smoking_alignment",
        feature_group="lifestyle",
        scoring_function_code="exact_match",
        sensitivity="confidential",
        explanation_code="similar_smoking_habits",
        criterion_code="smoking_status_code",
        similarity_code="smoking_status_code",
        default_weight=40,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="alcohol_alignment",
        feature_group="lifestyle",
        scoring_function_code="exact_match",
        sensitivity="confidential",
        explanation_code="similar_alcohol_habits",
        criterion_code="alcohol_use_code",
        similarity_code="alcohol_use_code",
        default_weight=30,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="interest_overlap",
        feature_group="interests",
        scoring_function_code="jaccard",
        sensitivity="controlled_public",
        explanation_code="shared_interests",
        criterion_code="leisure_interest_codes",
        similarity_code="leisure_interest_codes",
        default_weight=35,
        value_schema={"type": "array", "items": {"type": "string"}},
    ),
    FeatureDefinition(
        feature_code="communication_style_overlap",
        feature_group="communication",
        scoring_function_code="set_overlap",
        sensitivity="confidential",
        explanation_code="similar_communication_style",
        criterion_code="communication_preference_codes",
        similarity_code="communication_preference_codes",
        default_weight=40,
        value_schema={"type": "array", "items": {"type": "string"}},
    ),
    FeatureDefinition(
        feature_code="language_overlap",
        feature_group="language",
        scoring_function_code="set_overlap",
        sensitivity="controlled_public",
        explanation_code="shared_languages",
        criterion_code="language_codes",
        similarity_code="language_codes",
        default_weight=60,
        value_schema={"type": "array", "items": {"type": "string"}},
    ),
    FeatureDefinition(
        feature_code="education_alignment",
        feature_group="education_and_work",
        scoring_function_code="exact_match",
        sensitivity="confidential",
        explanation_code="similar_education_background",
        criterion_code="education_level_code",
        similarity_code="education_level_code",
        default_weight=25,
        value_schema={"type": "string"},
    ),
    FeatureDefinition(
        feature_code="profile_readiness",
        feature_group="profile_readiness",
        scoring_function_code="readiness",
        sensitivity="controlled_public",
        explanation_code="profile_information_available",
        default_weight=0,
        user_configurable=False,
        confidence_only=True,
        value_schema={"type": "integer"},
    ),
)

FEATURES_BY_CODE: dict[str, FeatureDefinition] = {
    definition.feature_code: definition for definition in FEATURE_DEFINITIONS
}

FEATURE_GROUPS: tuple[str, ...] = (
    "faith_and_values",
    "location_and_relocation",
    "family_and_parenting",
    "relationship_intent",
    "lifestyle",
    "communication",
    "interests",
    "language",
    "education_and_work",
    "profile_readiness",
)


def assert_registry_is_clean() -> None:
    """Fail closed if a prohibited signal was ever added to the registry."""
    for definition in FEATURE_DEFINITIONS:
        haystack = (
            f"{definition.feature_code} {definition.criterion_code or ''} "
            f"{definition.similarity_code or ''}"
        )
        for prohibited in PROHIBITED_SCORING_SIGNALS:
            if prohibited in haystack:
                raise ValueError(
                    f"feature {definition.feature_code} uses prohibited signal {prohibited}"
                )
        if definition.feature_group not in FEATURE_GROUPS:
            raise ValueError(f"feature {definition.feature_code} has an unknown group")


def feature_manifest() -> list[dict[str, Any]]:
    """Serialisable manifest stored inside a strategy version."""
    assert_registry_is_clean()
    return [
        {
            "feature_code": definition.feature_code,
            "semantic_version": definition.semantic_version,
            "feature_group": definition.feature_group,
            "scoring_function_code": definition.scoring_function_code,
            "sensitivity": definition.sensitivity,
            "explainable": definition.explainable,
            "user_configurable": definition.user_configurable,
            "criterion_code": definition.criterion_code,
            "similarity_code": definition.similarity_code,
            "default_weight": definition.default_weight,
            "confidence_only": definition.confidence_only,
            "value_schema": definition.value_schema,
            "status": "active",
        }
        for definition in FEATURE_DEFINITIONS
    ]


def apply_scoring_function(
    definition: FeatureDefinition,
    *,
    desired: Any,
    actual: Any,
    viewer_projection: dict[str, Any] | None = None,
    candidate_projection: dict[str, Any] | None = None,
) -> tuple[int, str | None]:
    """Run a feature's scoring function and return ``(bps, explanation_code)``."""
    code = definition.scoring_function_code
    if code == "geographic_compatibility":
        if viewer_projection is None or candidate_projection is None:
            return 0, None
        score, reason = score_geographic_compatibility(viewer_projection, candidate_projection)
        return score, reason
    if code == "exact_match":
        return score_exact_match(desired, actual), definition.explanation_code
    if code == "set_overlap":
        return score_set_overlap(desired, actual), definition.explanation_code
    if code == "jaccard":
        return score_jaccard(desired, actual), definition.explanation_code
    if code == "ordered_distance":
        return (
            score_ordered_distance(desired, actual, scale=definition.scale),
            definition.explanation_code,
        )
    if code == "range_match":
        return score_range_match(desired, actual), definition.explanation_code
    if code == "readiness":
        return clamp_bps(actual or 0), definition.explanation_code
    raise ValueError(f"unknown scoring function {code}")
