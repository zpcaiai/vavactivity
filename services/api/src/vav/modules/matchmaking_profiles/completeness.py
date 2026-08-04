"""Backend-authoritative dating-profile completeness.

Completeness answers one question only: did the member fill in what the
active schema release asks for? It is never a measure of personal worth,
spiritual maturity or match probability, and the frontend never computes it.

Scoring is split by the policy: required fields carry a fixed share of the
total, optional fields carry the remainder. Filling every required field
therefore lands exactly on the submission floor, and optional detail is what
lifts a profile toward recommendation eligibility.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.core.config import get_settings

#: Fields whose value is a list; an empty list counts as missing.
_COLLECTION_TYPES = frozenset({"enum_set", "string_set"})

#: Confirmation flags are only satisfied by an explicit yes.
_CONFIRMATION_FIELDS = frozenset(
    {"privacy.privacy_settings_confirmed", "privacy.partner_preferences_confirmed"}
)

DEFAULT_REQUIRED_SHARE_BASIS_POINTS = 8000


def _has_value(field_code: str, field_type: str, value: Any) -> bool:
    if value is None:
        return False
    if field_type in _COLLECTION_TYPES:
        return isinstance(value, list) and len(value) > 0
    if field_type == "boolean":
        # "No children" is a real answer, so False counts as answered — except
        # for confirmation flags, where only an explicit yes counts.
        if field_code in _CONFIRMATION_FIELDS:
            return value is True
        return isinstance(value, bool)
    if isinstance(value, str):
        return value.strip() != ""
    return True


def evaluate(
    payload: dict[str, Any],
    field_manifest: list[dict[str, Any]],
    completeness_policy: dict[str, Any],
) -> dict[str, Any]:
    """Score a flattened profile payload against a schema release policy.

    ``payload`` maps ``field_code`` to its stored value. The result carries
    section scores in basis points, the missing-field lists a member sees, and
    the two independent eligibility gates.
    """
    settings = get_settings()
    required_share = int(
        completeness_policy.get("required_share_basis_points", DEFAULT_REQUIRED_SHARE_BASIS_POINTS)
    )
    optional_share = 10000 - required_share

    section_weight: dict[str, int] = {}
    section_earned: dict[str, int] = {}
    missing_required: list[str] = []
    missing_optional: list[str] = []
    missing_for_recommendation: list[str] = []

    required_weight = required_earned = 0
    optional_weight = optional_earned = 0

    for definition in field_manifest:
        code = definition["field_code"]
        section = definition["section_code"]
        weight = int(definition.get("weight", 0))
        present = _has_value(code, definition["field_type"], payload.get(code))
        is_required = bool(definition.get("required_for_submission"))

        section_weight[section] = section_weight.get(section, 0) + weight
        section_earned.setdefault(section, 0)
        if present:
            section_earned[section] += weight

        if is_required:
            required_weight += weight
            if present:
                required_earned += weight
            else:
                missing_required.append(code)
        else:
            optional_weight += weight
            if present:
                optional_earned += weight
            else:
                missing_optional.append(code)

        if definition.get("required_for_recommendation") and not present:
            missing_for_recommendation.append(code)

    required_score = (
        round(required_earned * required_share / required_weight)
        if required_weight
        else required_share
    )
    optional_score = (
        round(optional_earned * optional_share / optional_weight)
        if optional_weight
        else optional_share
    )
    total_basis_points = min(10000, required_score + optional_score)

    section_scores = {
        section: (round(section_earned.get(section, 0) * 10000 / weight) if weight else 10000)
        for section, weight in section_weight.items()
    }

    # A missing mandatory field always blocks submission, no matter how high
    # the aggregate score is.
    submission_eligible = (
        not missing_required
        and total_basis_points >= settings.dating_profile_submission_min_completeness_bps
    )
    recommendation_eligible = (
        submission_eligible
        and not missing_for_recommendation
        and total_basis_points >= settings.dating_profile_recommendation_min_completeness_bps
    )

    return {
        "policy_version": str(completeness_policy.get("policy_version", "1.0.0")),
        "total_basis_points": total_basis_points,
        "required_basis_points": required_score,
        "optional_basis_points": optional_score,
        "section_scores": section_scores,
        "missing_required_fields": sorted(missing_required),
        "missing_recommended_fields": sorted(
            set(missing_optional) | set(missing_for_recommendation)
        ),
        "submission_eligible": submission_eligible,
        "recommendation_eligible": recommendation_eligible,
        "measures": "form_completion_only",
    }
