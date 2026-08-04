"""Field-level visibility across every viewer context."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

import pytest

from vav.modules.matchmaking_profiles.domain import DatingProfileViewContext
from vav.modules.matchmaking_profiles.privacy_view import (
    CONTEXT_SECTIONS,
    ProfileNotVisibleError,
    build_projection,
)
from vav.modules.matchmaking_profiles.taxonomies import FIELD_MANIFEST

from ..helpers import COMPLETE_FIELDS, SELF_INTRODUCTION

PROFILE = {"id": "11111111-1111-1111-1111-111111111111", "profile_number": "VAV-TEST-0001"}


def _payload() -> dict[str, Any]:
    return dict(COMPLETE_FIELDS) | {
        "self_introduction.self_introduction": SELF_INTRODUCTION,
        "faith.faith_journey_summary": "A private faith summary.",
        "relationship_history.history_summary": "A private history summary.",
    }


def _build(context: DatingProfileViewContext, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "profile": PROFILE,
        "payload": _payload(),
        "field_manifest": FIELD_MANIFEST,
        "context": context,
        "display_name": "Test Member",
        "age_years": 32,
        "age_display_mode": "exact_age",
        "primary_photo": None,
    }
    return build_projection(**(kwargs | overrides))


def test_recommendation_card_hides_restricted_history() -> None:
    projection = _build(DatingProfileViewContext.RECOMMENDATION_CARD)
    assert "relationship_history.marital_status_code" not in projection["visible_fields"]
    assert "faith.faith_status_code" not in projection["visible_fields"]


def test_self_view_returns_the_most_fields() -> None:
    self_view = _build(DatingProfileViewContext.SELF)
    card = _build(DatingProfileViewContext.RECOMMENDATION_CARD)
    assert len(self_view["visible_fields"]) > len(card["visible_fields"])


def test_private_encrypted_summaries_never_leave_the_self_view() -> None:
    for context in DatingProfileViewContext:
        if context is DatingProfileViewContext.SELF:
            continue
        if context is DatingProfileViewContext.AI_CONTEXT:
            projection = _build(context, ai_consent_granted=True)
        else:
            projection = _build(context)
        assert "faith.faith_journey_summary" not in projection["visible_fields"]
        assert "relationship_history.history_summary" not in projection["visible_fields"]


@pytest.mark.parametrize("context", list(DatingProfileViewContext))
def test_contact_details_are_never_available_in_any_context(
    context: DatingProfileViewContext,
) -> None:
    projection = _build(context, ai_consent_granted=True)
    assert projection["contact_details_available"] is False
    assert projection["contact_exchange_status"] == "not_exchanged"


def test_mutual_match_does_not_automatically_release_contact_details() -> None:
    projection = _build(DatingProfileViewContext.MUTUAL_MATCH)
    assert projection["contact_details_available"] is False


def test_ai_context_requires_consent() -> None:
    with pytest.raises(ProfileNotVisibleError):
        _build(DatingProfileViewContext.AI_CONTEXT, ai_consent_granted=False)
    projection = _build(DatingProfileViewContext.AI_CONTEXT, ai_consent_granted=True)
    assert projection["view_context"] == "ai_context"


def test_blocked_viewer_receives_nothing() -> None:
    with pytest.raises(ProfileNotVisibleError):
        _build(DatingProfileViewContext.PROFILE_DETAIL, blocked=True)


def test_activity_directory_is_the_narrowest_member_context() -> None:
    assert CONTEXT_SECTIONS[DatingProfileViewContext.ACTIVITY_DIRECTORY] == frozenset(
        {"basic", "location", "photos"}
    )


def test_field_override_can_narrow_but_is_honoured() -> None:
    projection = _build(
        DatingProfileViewContext.PROFILE_DETAIL,
        field_overrides={"basic.gender_code": "private"},
    )
    assert "basic.gender_code" not in projection["visible_fields"]


def test_age_display_mode_is_respected_for_other_viewers() -> None:
    hidden = _build(DatingProfileViewContext.PROFILE_DETAIL, age_display_mode="hidden")
    assert hidden["age_display"] is None
    bucketed = _build(DatingProfileViewContext.PROFILE_DETAIL, age_display_mode="age_range")
    assert bucketed["age_display"] == "30-34"
    # The owner always sees their own exact age.
    assert _build(DatingProfileViewContext.SELF, age_display_mode="hidden")["age_display"] == "32"
