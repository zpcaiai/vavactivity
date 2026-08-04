"""Directional soft scoring.

Scores come from explicit member preferences and transparent platform defaults
only. Missing information lowers confidence rather than silently scoring zero,
so a profile with one lucky matching field can never look like a confident
perfect match.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.common.exceptions import VavError
from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS
from vav.modules.recommendations.strategy import (
    FEATURE_MANIFEST,
    IMPORTANCE_WEIGHTS,
    SCORING_POLICY,
    SCORING_POLICY_VERSION,
)

RELOCATION_OPENNESS: dict[str, int] = {
    "not_willing": 0,
    "same_region": 1,
    "same_country": 2,
    "open_to_discuss": 2,
    "international": 3,
}


def assert_no_prohibited_signal(feature_codes: list[str]) -> None:
    """Fail closed if a prohibited signal ever reaches the scorer."""
    prohibited = sorted(set(feature_codes) & PROHIBITED_SCORING_SIGNALS)
    if prohibited:
        raise VavError(
            "RECOMMENDATION_PROHIBITED_SIGNAL",
            f"These signals may never be scored: {', '.join(prohibited)}.",
            status_code=500,
        )


# --------------------------------------------------------------------------
# Scoring functions — each returns basis points in [0, 10000] or None (unknown)
# --------------------------------------------------------------------------


def exact_match(desired: Any, actual: Any) -> int | None:
    if desired is None or actual is None:
        return None
    if isinstance(desired, list):
        return 10000 if actual in desired else 0
    return 10000 if desired == actual else 0


def set_overlap(desired: Any, actual: Any) -> int | None:
    """Normalised Jaccard-style overlap, explainable as "shared values"."""
    desired_set = {str(item) for item in (desired or [])}
    actual_set = {str(item) for item in (actual or [])}
    if not desired_set or not actual_set:
        return None
    union = desired_set | actual_set
    return round(len(desired_set & actual_set) * 10000 / len(union))


def ordered_distance(desired: Any, actual: Any, *, maximum_distance: int) -> int | None:
    if desired is None or actual is None or maximum_distance <= 0:
        return None
    try:
        gap = abs(int(desired) - int(actual))
    except (TypeError, ValueError):
        return None
    return round(max(0, maximum_distance - gap) * 10000 / maximum_distance)


def range_match(desired: Any, actual: Any) -> int | None:
    """How central the value sits inside a preferred range, not a pass/fail."""
    if not isinstance(desired, dict) or actual is None:
        return None
    try:
        minimum = int(desired["minimum"])
        maximum = int(desired["maximum"])
        value = int(actual)
    except (TypeError, ValueError, KeyError):
        return None
    if maximum < minimum:
        return None
    if value < minimum or value > maximum:
        return 0
    if maximum == minimum:
        return 10000
    midpoint = (minimum + maximum) / 2
    half_span = (maximum - minimum) / 2
    return round(max(0.0, 1 - abs(value - midpoint) / half_span) * 10000)


def geographic_compatibility(source: dict[str, Any], target: dict[str, Any]) -> int | None:
    """Combine city, region, country and both sides' relocation openness.

    A precise address is never read — only the coarse codes the Batch 13
    projection publishes.
    """
    source_city = source.get("city_code")
    target_city = target.get("city_code")
    source_region = source.get("region_code")
    target_region = target.get("region_code")
    source_country = source.get("country_code")
    target_country = target.get("country_code")
    if not source_country or not target_country:
        return None

    if source_city and target_city and source_city == target_city:
        return 10000
    openness = min(
        RELOCATION_OPENNESS.get(str(source.get("relocation_willingness")), 0),
        RELOCATION_OPENNESS.get(str(target.get("relocation_willingness")), 0),
    )
    if source_region and target_region and source_region == target_region:
        return min(10000, 7000 + openness * 700)
    if source_country == target_country:
        return min(10000, 4500 + openness * 900)
    if openness >= 3:
        return 4000
    if openness >= 2:
        return 2500
    return 500


def readiness(target: dict[str, Any]) -> int | None:
    """How much detail is available, used for confidence and tie-breaking only."""
    filled = sum(
        1 for key in ("faith_codes", "lifestyle_codes", "language_codes") if target.get(key)
    )
    filled += sum(
        1
        for key in (
            "relationship_intent",
            "marital_status_code",
            "children_status_code",
            "city_code",
        )
        if target.get(key)
    )
    return round(filled * 10000 / 7)


# --------------------------------------------------------------------------
# Directional scoring
# --------------------------------------------------------------------------


def _preference_lookup(criteria: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["criterion_code"]): item for item in criteria}


def _extract(projection: dict[str, Any], feature: dict[str, Any]) -> Any:
    field = feature["projection_field"]
    value = projection.get(field)
    prefix = feature["options"].get("code_prefix")
    scale_prefix = feature["options"].get("scale_prefix")
    if prefix and isinstance(value, list):
        for item in value:
            if str(item).startswith(prefix):
                return str(item).split(":", 1)[1]
        return None
    if scale_prefix and isinstance(value, list):
        for item in value:
            if str(item).startswith(scale_prefix):
                try:
                    return int(str(item).split(":", 1)[1])
                except ValueError:
                    return None
        return None
    if field == "faith_codes" and isinstance(value, list):
        return [item for item in value if not str(item).startswith("marriage_faith_importance:")]
    return value


def score_direction(
    *,
    source_projection: dict[str, Any],
    target_projection: dict[str, Any],
    source_criteria: list[dict[str, Any]],
    weight_adjustments: dict[str, int] | None = None,
    feature_manifest: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score how well the target matches what the source asked for."""
    manifest = feature_manifest or FEATURE_MANIFEST
    assert_no_prohibited_signal([feature["feature_code"] for feature in manifest])

    preferences = _preference_lookup(source_criteria)
    adjustments = weight_adjustments or {}
    feature_scores: list[dict[str, Any]] = []
    missing: list[str] = []

    weighted_total = 0
    effective_weight = 0
    declared_weight = 0

    for feature in manifest:
        code = feature["feature_code"]
        criterion_code = feature.get("preference_criterion")
        preference = preferences.get(criterion_code) if criterion_code else None

        # REQUIRED lives in the hard-constraint stage and is never re-weighted here.
        importance = str(preference["importance"]) if preference else None
        if importance == "required":
            weight = feature["default_weight"]
        elif importance is not None:
            weight = IMPORTANCE_WEIGHTS.get(importance, 0)
        else:
            weight = feature["default_weight"]
        weight = max(0, weight + int(adjustments.get(code, 0)))
        if weight == 0:
            continue
        declared_weight += weight

        function = feature["scoring_function_code"]
        desired = (
            preference["desired_value"] if preference else _extract(source_projection, feature)
        )
        actual = _extract(target_projection, feature)

        if function == "exact_match":
            raw = exact_match(desired, actual)
        elif function == "set_overlap":
            raw = set_overlap(desired, actual)
        elif function == "ordered_distance":
            raw = ordered_distance(
                desired, actual, maximum_distance=int(feature["options"].get("maximum_distance", 4))
            )
        elif function == "range_match":
            raw = range_match(desired, actual)
        elif function == "geographic_compatibility":
            raw = geographic_compatibility(source_projection, target_projection)
        elif function == "readiness":
            raw = readiness(target_projection)
        else:
            raw = None

        if raw is None:
            missing.append(code)
            feature_scores.append(
                {
                    "feature_code": code,
                    "raw_match_bps": None,
                    "importance_weight": weight,
                    "weighted_score": 0,
                    "confidence_bps": 0,
                    "explanation_code": None,
                }
            )
            continue

        weighted = raw * weight
        weighted_total += weighted
        effective_weight += weight
        feature_scores.append(
            {
                "feature_code": code,
                "raw_match_bps": raw,
                "importance_weight": weight,
                "weighted_score": weighted,
                "confidence_bps": 10000,
                "explanation_code": feature["explanation_code"] if raw >= 6000 else None,
            }
        )

    total_score = round(weighted_total / effective_weight) if effective_weight else 0

    # Confidence reflects how much of the declared weight actually had data,
    # capped by an absolute floor so a single field cannot look authoritative.
    coverage_bps = round(effective_weight * 10000 / declared_weight) if declared_weight else 0
    absolute_bps = min(
        10000,
        round(effective_weight * 10000 / int(SCORING_POLICY["confidence_full_information_weight"])),
    )
    confidence = min(coverage_bps, absolute_bps)

    return {
        "total_score_bps": total_score,
        "confidence_bps": confidence,
        "feature_scores": feature_scores,
        "missing_information": sorted(missing),
        "unknown_feature_count": len(missing),
        "effective_weight": effective_weight,
        "declared_weight": declared_weight,
        "scoring_policy_version": SCORING_POLICY_VERSION,
        "missingness_policy": SCORING_POLICY["missingness_policy"],
    }
