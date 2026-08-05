"""Directional soft scoring.

A directional score answers one question only: how well does the candidate
match what *this* member explicitly asked for, plus the platform's transparent
defaults. Missing information lowers confidence instead of scoring zero, and
required criteria are never counted twice because they are already enforced by
the hard-constraint engine.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from vav.modules.recommendations.domain import MissingnessPolicy, clamp_bps
from vav.modules.recommendations.features import (
    FEATURE_DEFINITIONS,
    FEATURE_REGISTRY_VERSION,
    NEUTRAL_BPS,
    FeatureDefinition,
    apply_scoring_function,
    extract_value,
)

SCORING_POLICY_VERSION = "1.0.0"

#: Member importance to base weight. ``required`` becomes a hard constraint.
IMPORTANCE_WEIGHTS: dict[str, int] = {
    "required": 0,
    "very_important": 100,
    "important": 70,
    "nice_to_have": 35,
    "no_preference": 0,
}

#: Members may nudge a feature weight, but never beyond this multiplier range.
MIN_TUNING_MULTIPLIER = 0.5
MAX_TUNING_MULTIPLIER = 1.5

#: Confidence is capped until enough independent features carry information.
CONFIDENCE_FEATURE_TARGET = 8


@dataclass(frozen=True)
class FeatureScore:
    feature_code: str
    raw_match_bps: int
    importance_weight: int
    weighted_score: int
    confidence_bps: int
    explanation_code: str | None = None
    #: ``True`` when the criterion was already enforced as a hard constraint.
    hard_constraint_satisfied: bool = False
    information_available: bool = True
    source: str = "member_preference"

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_code": self.feature_code,
            "raw_match_bps": self.raw_match_bps,
            "importance_weight": self.importance_weight,
            "weighted_score": self.weighted_score,
            "confidence_bps": self.confidence_bps,
            "explanation_code": self.explanation_code,
            "hard_constraint_satisfied": self.hard_constraint_satisfied,
            "information_available": self.information_available,
            "source": self.source,
        }


@dataclass(frozen=True)
class DirectionalCompatibilityScore:
    source_user_id: UUID
    target_user_id: UUID
    total_score_bps: int
    confidence_bps: int
    feature_scores: list[FeatureScore]
    missing_information: list[str]
    unknown_feature_count: int
    scoring_policy_version: str = SCORING_POLICY_VERSION
    feature_registry_version: str = FEATURE_REGISTRY_VERSION
    satisfied_preferences: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_user_id": str(self.source_user_id),
            "target_user_id": str(self.target_user_id),
            "total_score_bps": self.total_score_bps,
            "confidence_bps": self.confidence_bps,
            "feature_scores": [score.as_dict() for score in self.feature_scores],
            "missing_information": self.missing_information,
            "unknown_feature_count": self.unknown_feature_count,
            "scoring_policy_version": self.scoring_policy_version,
            "feature_registry_version": self.feature_registry_version,
            "satisfied_preferences": self.satisfied_preferences,
        }


def importance_weight(importance: str | None) -> int:
    if importance is None:
        return 0
    return IMPORTANCE_WEIGHTS.get(str(importance), 0)


def _tuned(weight: int, feature_code: str, adjustments: dict[str, Any] | None) -> int:
    if not adjustments:
        return weight
    raw = adjustments.get(feature_code)
    if raw is None:
        return weight
    try:
        multiplier = float(raw)
    except (TypeError, ValueError):
        return weight
    multiplier = max(MIN_TUNING_MULTIPLIER, min(MAX_TUNING_MULTIPLIER, multiplier))
    return int(round(weight * multiplier))


def _criteria_by_code(criteria: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["criterion_code"]): item for item in criteria}


def readiness_bps(projection: dict[str, Any]) -> int:
    """How much published information the candidate profile carries."""
    populated = 0
    checked = 0
    for code in (
        "age_years",
        "country_code",
        "city_code",
        "gender_code",
        "relationship_intent",
        "marital_status_code",
        "children_status_code",
        "relocation_willingness",
        "language_codes",
        "faith_codes",
        "lifestyle_codes",
    ):
        checked += 1
        value = projection.get(code)
        if value not in (None, [], ""):
            populated += 1
    if checked == 0:
        return 0
    return clamp_bps(populated / checked * 10_000)


def score_feature(
    definition: FeatureDefinition,
    *,
    viewer_projection: dict[str, Any],
    candidate_projection: dict[str, Any],
    criteria: dict[str, dict[str, Any]],
    tuning_adjustments: dict[str, Any] | None,
    missingness_policy: str,
    missing_penalty_bps: int,
) -> FeatureScore:
    """Score one feature in one direction."""
    if definition.confidence_only:
        readiness = readiness_bps(candidate_projection)
        return FeatureScore(
            feature_code=definition.feature_code,
            raw_match_bps=readiness,
            importance_weight=0,
            weighted_score=0,
            confidence_bps=readiness,
            explanation_code=definition.explanation_code,
            information_available=True,
            source="platform_default",
        )

    criterion = criteria.get(definition.criterion_code or "")
    source = "member_preference"
    if criterion is not None and criterion.get("hard_constraint"):
        # Already enforced as a hard rule; scoring it again would double count.
        return FeatureScore(
            feature_code=definition.feature_code,
            raw_match_bps=10_000,
            importance_weight=0,
            weighted_score=0,
            confidence_bps=10_000,
            explanation_code=definition.explanation_code,
            hard_constraint_satisfied=True,
            information_available=True,
            source="hard_constraint",
        )

    if criterion is not None:
        desired = criterion.get("desired_value")
        weight = importance_weight(str(criterion.get("importance")))
        lookup_code = definition.criterion_code or definition.similarity_code
    else:
        source = "platform_default"
        lookup_code = definition.similarity_code
        desired = extract_value(viewer_projection, lookup_code) if lookup_code else None
        weight = definition.default_weight

    weight = _tuned(weight, definition.feature_code, tuning_adjustments)
    actual = extract_value(candidate_projection, lookup_code) if lookup_code else None

    if definition.scoring_function_code == "geographic_compatibility":
        raw, explanation_code = apply_scoring_function(
            definition,
            desired=None,
            actual=None,
            viewer_projection=viewer_projection,
            candidate_projection=candidate_projection,
        )
        available = bool(
            viewer_projection.get("country_code") and candidate_projection.get("country_code")
        )
    else:
        available = desired is not None and actual is not None
        if available:
            raw, explanation_code = apply_scoring_function(
                definition, desired=desired, actual=actual
            )
        else:
            raw, explanation_code = 0, None

    if not available:
        if missingness_policy == MissingnessPolicy.NEUTRAL_SCORE.value:
            return FeatureScore(
                feature_code=definition.feature_code,
                raw_match_bps=NEUTRAL_BPS,
                importance_weight=weight,
                weighted_score=NEUTRAL_BPS * weight,
                confidence_bps=0,
                explanation_code=None,
                information_available=False,
                source=source,
            )
        if missingness_policy == MissingnessPolicy.CONFIGURED_PENALTY.value:
            penalty = clamp_bps(missing_penalty_bps)
            return FeatureScore(
                feature_code=definition.feature_code,
                raw_match_bps=penalty,
                importance_weight=weight,
                weighted_score=penalty * weight,
                confidence_bps=0,
                explanation_code=None,
                information_available=False,
                source=source,
            )
        # Default: ignore the feature and lower confidence instead.
        return FeatureScore(
            feature_code=definition.feature_code,
            raw_match_bps=0,
            importance_weight=weight,
            weighted_score=0,
            confidence_bps=0,
            explanation_code=None,
            information_available=False,
            source=source,
        )

    raw = clamp_bps(raw)
    return FeatureScore(
        feature_code=definition.feature_code,
        raw_match_bps=raw,
        importance_weight=weight,
        weighted_score=raw * weight,
        confidence_bps=10_000,
        explanation_code=explanation_code,
        information_available=True,
        source=source,
    )


def score_direction(
    *,
    source_user_id: UUID,
    target_user_id: UUID,
    viewer_projection: dict[str, Any],
    candidate_projection: dict[str, Any],
    viewer_criteria: list[dict[str, Any]],
    tuning_adjustments: dict[str, Any] | None = None,
    missingness_policy: str = MissingnessPolicy.IGNORE_AND_LOWER_CONFIDENCE.value,
    missing_penalty_bps: int = 0,
) -> DirectionalCompatibilityScore:
    """Score how well the candidate matches this member's stated preferences."""
    criteria = _criteria_by_code(viewer_criteria)
    scores: list[FeatureScore] = []
    for definition in FEATURE_DEFINITIONS:
        scores.append(
            score_feature(
                definition,
                viewer_projection=viewer_projection,
                candidate_projection=candidate_projection,
                criteria=criteria,
                tuning_adjustments=tuning_adjustments,
                missingness_policy=missingness_policy,
                missing_penalty_bps=missing_penalty_bps,
            )
        )

    informed_weight = sum(
        score.importance_weight
        for score in scores
        if score.information_available and score.importance_weight > 0
    )
    declared_weight = sum(
        score.importance_weight for score in scores if score.importance_weight > 0
    )
    weighted_sum = sum(
        score.weighted_score
        for score in scores
        if score.importance_weight > 0
        and (
            score.information_available
            or missingness_policy != MissingnessPolicy.IGNORE_AND_LOWER_CONFIDENCE.value
        )
    )

    total = clamp_bps(weighted_sum / informed_weight) if informed_weight else 0

    informed_features = [
        score for score in scores if score.information_available and score.importance_weight > 0
    ]
    coverage = (informed_weight / declared_weight) if declared_weight else 0.0
    breadth = min(1.0, len(informed_features) / CONFIDENCE_FEATURE_TARGET)
    readiness = next(
        (score.confidence_bps for score in scores if score.feature_code == "profile_readiness"),
        0,
    )
    confidence = clamp_bps((0.5 * coverage + 0.3 * breadth + 0.2 * readiness / 10_000) * 10_000)

    missing = sorted(score.feature_code for score in scores if not score.information_available)
    satisfied = sorted(
        score.feature_code
        for score in scores
        if score.hard_constraint_satisfied
        or (
            score.information_available
            and score.importance_weight >= 70
            and score.raw_match_bps >= 7_000
        )
    )

    return DirectionalCompatibilityScore(
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        total_score_bps=total,
        confidence_bps=confidence,
        feature_scores=scores,
        missing_information=missing,
        unknown_feature_count=len(missing),
        satisfied_preferences=satisfied,
    )
