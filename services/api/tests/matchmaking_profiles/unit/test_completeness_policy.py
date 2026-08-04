"""Completeness scoring is backend-authoritative and gate-driven."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from vav.modules.matchmaking_profiles import completeness
from vav.modules.matchmaking_profiles.taxonomies import (
    COMPLETENESS_POLICY,
    FIELD_MANIFEST,
)

from ..helpers import COMPLETE_FIELDS, SELF_INTRODUCTION


def _full_payload() -> dict[str, Any]:
    payload = dict(COMPLETE_FIELDS)
    payload["self_introduction.self_introduction"] = SELF_INTRODUCTION
    payload["photos.primary_photo"] = "11111111-1111-1111-1111-111111111111"
    payload["privacy.privacy_settings_confirmed"] = True
    payload["privacy.partner_preferences_confirmed"] = True
    return payload


def test_empty_profile_scores_zero_and_lists_every_required_field() -> None:
    result = completeness.evaluate({}, FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert result["total_basis_points"] == 0
    assert not result["submission_eligible"]
    required = {
        definition["field_code"]
        for definition in FIELD_MANIFEST
        if definition["required_for_submission"]
    }
    assert set(result["missing_required_fields"]) == required


def test_complete_profile_is_submission_eligible() -> None:
    result = completeness.evaluate(_full_payload(), FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert result["missing_required_fields"] == []
    assert result["submission_eligible"]
    assert result["total_basis_points"] >= 8000


def test_high_score_cannot_override_a_missing_mandatory_field() -> None:
    payload = _full_payload()
    del payload["family.desire_children_code"]
    result = completeness.evaluate(payload, FIELD_MANIFEST, COMPLETENESS_POLICY)
    # The aggregate score stays well above the submission floor...
    assert result["total_basis_points"] >= 8000
    # ...but a single missing mandatory field still blocks submission.
    assert "family.desire_children_code" in result["missing_required_fields"]
    assert not result["submission_eligible"]
    assert not result["recommendation_eligible"]


def test_empty_collection_counts_as_missing() -> None:
    payload = _full_payload()
    payload["basic.eligible_partner_gender_codes"] = []
    result = completeness.evaluate(payload, FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert "basic.eligible_partner_gender_codes" in result["missing_required_fields"]


def test_unconfirmed_privacy_boolean_counts_as_missing() -> None:
    payload = _full_payload()
    payload["privacy.privacy_settings_confirmed"] = False
    result = completeness.evaluate(payload, FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert "privacy.privacy_settings_confirmed" in result["missing_required_fields"]


def test_section_scores_are_reported_in_basis_points() -> None:
    result = completeness.evaluate(_full_payload(), FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert set(result["section_scores"]) >= {"basic", "faith", "photos", "privacy"}
    assert all(0 <= score <= 10000 for score in result["section_scores"].values())


def test_completeness_only_measures_form_completion() -> None:
    result = completeness.evaluate(_full_payload(), FIELD_MANIFEST, COMPLETENESS_POLICY)
    assert result["measures"] == "form_completion_only"
    assert COMPLETENESS_POLICY["not_a_measure_of"] == [
        "personal_worth",
        "marriage_value",
        "spiritual_maturity",
        "match_probability",
    ]


def test_policy_version_travels_with_the_snapshot() -> None:
    result = completeness.evaluate(
        _full_payload(), FIELD_MANIFEST, {**COMPLETENESS_POLICY, "policy_version": "9.9.9"}
    )
    assert result["policy_version"] == "9.9.9"
