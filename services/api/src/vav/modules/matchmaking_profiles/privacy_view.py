"""Viewer-specific dating-profile projections.

The backend decides what each viewer may see. The frontend never receives a
full profile and then hides parts of it, so a client bug can never leak a
restricted field. Contact details are never released here under any context.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.modules.matchmaking_profiles.domain import (
    DatingProfileViewContext,
    FieldSensitivity,
)

#: Sections released per view context, before per-field privacy rules apply.
CONTEXT_SECTIONS: dict[DatingProfileViewContext, frozenset[str]] = {
    DatingProfileViewContext.SELF: frozenset(
        {
            "basic",
            "location",
            "faith",
            "relationship_history",
            "family",
            "children_and_parenting",
            "lifestyle",
            "education_and_work",
            "interests",
            "communication",
            "relationship_values",
            "self_introduction",
            "future_vision",
            "photos",
            "privacy",
        }
    ),
    DatingProfileViewContext.ADMIN_REVIEW: frozenset(
        {
            "basic",
            "location",
            "faith",
            "relationship_history",
            "family",
            "children_and_parenting",
            "lifestyle",
            "education_and_work",
            "interests",
            "communication",
            "relationship_values",
            "self_introduction",
            "future_vision",
            "photos",
        }
    ),
    DatingProfileViewContext.RECOMMENDATION_CARD: frozenset(
        {"basic", "location", "faith", "photos"}
    ),
    DatingProfileViewContext.PROFILE_DETAIL: frozenset(
        {
            "basic",
            "location",
            "faith",
            "lifestyle",
            "education_and_work",
            "interests",
            "communication",
            "relationship_values",
            "self_introduction",
            "future_vision",
            "photos",
        }
    ),
    DatingProfileViewContext.ACTIVITY_DIRECTORY: frozenset({"basic", "location", "photos"}),
    DatingProfileViewContext.MUTUAL_MATCH: frozenset(
        {
            "basic",
            "location",
            "faith",
            "family",
            "lifestyle",
            "education_and_work",
            "interests",
            "communication",
            "relationship_values",
            "self_introduction",
            "future_vision",
            "photos",
        }
    ),
    DatingProfileViewContext.INTRODUCTION_ACCEPTED: frozenset(
        {
            "basic",
            "location",
            "faith",
            "relationship_history",
            "family",
            "children_and_parenting",
            "lifestyle",
            "education_and_work",
            "interests",
            "communication",
            "relationship_values",
            "self_introduction",
            "future_vision",
            "photos",
        }
    ),
    DatingProfileViewContext.AI_CONTEXT: frozenset(
        {"basic", "faith", "lifestyle", "relationship_values", "future_vision"}
    ),
}

#: The highest sensitivity a context may release.
CONTEXT_MAX_SENSITIVITY: dict[DatingProfileViewContext, FieldSensitivity] = {
    DatingProfileViewContext.SELF: FieldSensitivity.HIGHLY_RESTRICTED,
    DatingProfileViewContext.ADMIN_REVIEW: FieldSensitivity.RESTRICTED,
    DatingProfileViewContext.RECOMMENDATION_CARD: FieldSensitivity.CONTROLLED_PUBLIC,
    DatingProfileViewContext.PROFILE_DETAIL: FieldSensitivity.CONFIDENTIAL,
    DatingProfileViewContext.ACTIVITY_DIRECTORY: FieldSensitivity.CONTROLLED_PUBLIC,
    DatingProfileViewContext.MUTUAL_MATCH: FieldSensitivity.RESTRICTED,
    DatingProfileViewContext.INTRODUCTION_ACCEPTED: FieldSensitivity.RESTRICTED,
    DatingProfileViewContext.AI_CONTEXT: FieldSensitivity.CONFIDENTIAL,
}

_SENSITIVITY_ORDER: dict[str, int] = {
    FieldSensitivity.CONTROLLED_PUBLIC.value: 0,
    FieldSensitivity.CONFIDENTIAL.value: 1,
    FieldSensitivity.RESTRICTED.value: 2,
    FieldSensitivity.HIGHLY_RESTRICTED.value: 3,
}

#: Locations are always coarsened to city level; a street address is never
#: collected or released by the matchmaking domain.
COARSE_LOCATION_FIELDS = frozenset({"location.city_code", "location.region_code"})

#: Never released by any viewer projection, regardless of context.
NEVER_RELEASED = frozenset(
    {
        "faith.faith_journey_summary",
        "relationship_history.history_summary",
        "family.family_summary",
    }
)


class ProfileNotVisibleError(Exception):
    """Raised when no field at all may be released to this viewer."""


def _visibility_allows(visibility: str, context: DatingProfileViewContext) -> bool:
    if visibility == "private":
        return context in {DatingProfileViewContext.SELF, DatingProfileViewContext.ADMIN_REVIEW}
    if visibility == "verified_members":
        return context is not DatingProfileViewContext.AI_CONTEXT
    if visibility == "mutual_only":
        return context in {
            DatingProfileViewContext.SELF,
            DatingProfileViewContext.ADMIN_REVIEW,
            DatingProfileViewContext.MUTUAL_MATCH,
            DatingProfileViewContext.INTRODUCTION_ACCEPTED,
        }
    return True


def build_projection(
    *,
    profile: dict[str, Any],
    payload: dict[str, Any],
    field_manifest: list[dict[str, Any]],
    context: DatingProfileViewContext,
    display_name: str,
    age_years: int | None,
    age_display_mode: str,
    primary_photo: dict[str, Any] | None,
    field_overrides: dict[str, str] | None = None,
    moderation_badges: list[str] | None = None,
    blocked: bool = False,
    ai_consent_granted: bool = False,
) -> dict[str, Any]:
    """Build the DTO a specific viewer is allowed to receive."""
    if blocked:
        raise ProfileNotVisibleError("viewer is blocked")
    if context is DatingProfileViewContext.AI_CONTEXT and not ai_consent_granted:
        raise ProfileNotVisibleError("AI profile access consent has not been granted")

    allowed_sections = CONTEXT_SECTIONS[context]
    max_sensitivity = _SENSITIVITY_ORDER[CONTEXT_MAX_SENSITIVITY[context].value]
    overrides = field_overrides or {}

    visible_fields: dict[str, Any] = {}
    withheld_fields: list[str] = []

    for definition in field_manifest:
        code = definition["field_code"]
        if code in NEVER_RELEASED and context is not DatingProfileViewContext.SELF:
            withheld_fields.append(code)
            continue
        if definition["section_code"] not in allowed_sections:
            withheld_fields.append(code)
            continue
        if _SENSITIVITY_ORDER[definition["sensitivity"]] > max_sensitivity:
            withheld_fields.append(code)
            continue
        visibility = overrides.get(code, definition["default_visibility"])
        if not _visibility_allows(visibility, context):
            withheld_fields.append(code)
            continue
        value = payload.get(code)
        if value is None or value == [] or value == "":
            continue
        visible_fields[code] = value

    return {
        "profile_id": str(profile["id"]),
        "profile_number": profile["profile_number"],
        "display_name": display_name,
        "age_display": _age_display(age_years, age_display_mode, context),
        "city_display": visible_fields.get("location.city_code"),
        "primary_photo": primary_photo,
        "faith_summary": _section_summary(visible_fields, "faith"),
        "lifestyle_summary": _section_summary(visible_fields, "lifestyle"),
        "relationship_summary": _section_summary(visible_fields, "relationship_history"),
        "self_introduction": visible_fields.get("self_introduction.self_introduction"),
        "visible_fields": visible_fields,
        "withheld_field_count": len(withheld_fields),
        "view_context": context.value,
        # Contact exchange is always gated behind the Batch 15 consent flow.
        "contact_exchange_status": "not_exchanged",
        "contact_details_available": False,
        "moderation_badges": moderation_badges or [],
    }


def _age_display(age_years: int | None, mode: str, context: DatingProfileViewContext) -> str | None:
    if age_years is None:
        return None
    if context is DatingProfileViewContext.SELF:
        return str(age_years)
    if mode == "hidden":
        return None
    if mode == "age_range":
        lower = age_years - (age_years % 5)
        return f"{lower}-{lower + 4}"
    return str(age_years)


def _section_summary(visible_fields: dict[str, Any], section: str) -> dict[str, Any] | None:
    prefix = f"{section}."
    summary = {
        code[len(prefix) :]: value
        for code, value in visible_fields.items()
        if code.startswith(prefix)
    }
    return summary or None
