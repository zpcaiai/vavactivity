"""De-identified recommendation projections consumed by Batch 14.

A projection is built only from the approved profile version, contains only
normalised codes, and is rejected outright if a prohibited value ever reaches
it. Recommendation eligibility is recomputed on every rebuild.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from typing import Any

from vav.common.exceptions import VavError
from vav.modules.matchmaking_profiles.domain import (
    PROHIBITED_PROJECTION_FIELDS,
    DatingProfileStatus,
    age_bucket,
)

#: Payload keys the projection is allowed to carry.
ALLOWED_PROJECTION_KEYS = frozenset(
    {
        "age_bucket",
        "age_years",
        "country_code",
        "region_code",
        "city_code",
        "gender_code",
        "eligible_partner_gender_codes",
        "faith_codes",
        "relationship_intent",
        "marital_status_code",
        "children_status_code",
        "relocation_willingness",
        "language_codes",
        "lifestyle_codes",
        "indexed_preference_criteria",
    }
)


def eligibility(
    *,
    profile_status: str,
    approved_version_number: int | None,
    account_active: bool,
    age_years: int | None,
    minimum_age: int,
    completeness_recommendation_eligible: bool,
    has_approved_primary_photo: bool,
    require_primary_photo: bool,
    privacy_allows_matchmaking: bool,
    security_suspended: bool,
    preferences_valid: bool,
) -> tuple[bool, list[str]]:
    """Return the recommendation-pool decision and every reason it failed."""
    reasons: list[str] = []
    if profile_status != DatingProfileStatus.ACTIVE.value:
        reasons.append("profile_not_active")
    if approved_version_number is None:
        reasons.append("no_approved_version")
    if not account_active:
        reasons.append("account_not_active")
    if age_years is None:
        reasons.append("age_unknown")
    elif age_years < minimum_age:
        reasons.append("below_minimum_age")
    if not completeness_recommendation_eligible:
        reasons.append("completeness_below_threshold")
    if require_primary_photo and not has_approved_primary_photo:
        reasons.append("no_approved_primary_photo")
    if not privacy_allows_matchmaking:
        reasons.append("matchmaking_visibility_not_granted")
    if security_suspended:
        reasons.append("security_suspension")
    if not preferences_valid:
        reasons.append("partner_preferences_incomplete")
    return (not reasons, reasons)


def build_payload(
    payload: dict[str, Any],
    *,
    age_years: int | None,
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalise an approved profile snapshot into projection columns."""
    faith_codes: list[str] = []
    for code in (
        payload.get("faith.faith_status_code"),
        payload.get("faith.current_church_participation_code"),
    ):
        if code:
            faith_codes.append(str(code))
    faith_codes.extend(str(item) for item in payload.get("faith.church_tradition_codes") or [])
    importance = payload.get("faith.marriage_faith_importance")
    if importance is not None:
        faith_codes.append(f"marriage_faith_importance:{importance}")

    lifestyle_codes: list[str] = []
    for key in (
        "lifestyle.daily_schedule_code",
        "lifestyle.smoking_status_code",
        "lifestyle.alcohol_use_code",
        "lifestyle.exercise_frequency_code",
        "lifestyle.travel_frequency_code",
        "education_and_work.education_level_code",
        "education_and_work.occupation_category_code",
        "family.desire_children_code",
    ):
        value = payload.get(key)
        if value:
            lifestyle_codes.append(f"{key.split('.')[-1]}:{value}")
    for key in (
        "lifestyle.leisure_interest_codes",
        "lifestyle.communication_preference_codes",
        "lifestyle.social_style_codes",
    ):
        for value in payload.get(key) or []:
            lifestyle_codes.append(f"{key.split('.')[-1]}:{value}")

    languages = [str(item) for item in payload.get("location.primary_language_codes") or []]
    languages += [str(item) for item in payload.get("location.additional_language_codes") or []]

    children_status = payload.get("relationship_history.children_living_arrangement_code")
    if children_status is None:
        has_children = payload.get("relationship_history.has_children")
        if has_children is False:
            children_status = "no_children"

    projection = {
        "age_bucket": age_bucket(age_years),
        "age_years": age_years,
        "country_code": payload.get("location.country_code"),
        "region_code": payload.get("location.region_code"),
        "city_code": payload.get("location.city_code"),
        "gender_code": payload.get("basic.gender_code"),
        "eligible_partner_gender_codes": [
            str(item) for item in payload.get("basic.eligible_partner_gender_codes") or []
        ],
        "faith_codes": faith_codes,
        "relationship_intent": payload.get("basic.relationship_intent"),
        "marital_status_code": payload.get("relationship_history.marital_status_code"),
        "children_status_code": children_status,
        "relocation_willingness": payload.get("location.relocation_willingness"),
        "language_codes": sorted(set(languages)),
        "lifestyle_codes": sorted(set(lifestyle_codes)),
        "indexed_preference_criteria": [
            {
                "criterion_code": criterion["criterion_code"],
                "operator": criterion["operator"],
                "desired_value": criterion["desired_value"],
                "importance": criterion["importance"],
                "hard_constraint": criterion["hard_constraint"],
                "allow_unknown": criterion["allow_unknown"],
                "allow_system_relaxation": criterion["allow_system_relaxation"],
            }
            for criterion in criteria
        ],
    }
    assert_no_prohibited_fields(projection)
    return projection


def assert_no_prohibited_fields(projection: dict[str, Any]) -> None:
    """Fail closed if a projection ever carries a forbidden key."""
    unexpected = set(projection) - ALLOWED_PROJECTION_KEYS
    if unexpected:
        raise VavError(
            "DATING_PROJECTION_FIELD_NOT_ALLOWED",
            f"Recommendation projections cannot carry: {', '.join(sorted(unexpected))}.",
            status_code=500,
        )
    prohibited = set(projection) & PROHIBITED_PROJECTION_FIELDS
    if prohibited:
        raise VavError(
            "DATING_PROJECTION_PROHIBITED_FIELD",
            f"Recommendation projections cannot carry: {', '.join(sorted(prohibited))}.",
            status_code=500,
        )


def checksum(
    projection: dict[str, Any],
    *,
    approved_version: int,
    preference_version: int,
    privacy_version: int,
) -> str:
    material = json.dumps(
        {
            "projection": projection,
            "approved_version": approved_version,
            "preference_version": preference_version,
            "privacy_version": privacy_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()
