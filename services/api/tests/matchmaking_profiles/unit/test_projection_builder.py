"""Recommendation projection construction and eligibility."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

import pytest

from vav.common.exceptions import VavError
from vav.modules.matchmaking_profiles import projections
from vav.modules.matchmaking_profiles.domain import (
    PROHIBITED_PROJECTION_FIELDS,
    age_bucket,
)

from ..helpers import COMPLETE_FIELDS, SELF_INTRODUCTION

CRITERIA: list[dict[str, Any]] = [
    {
        "criterion_code": "age_range",
        "operator": "range",
        "desired_value": {"minimum": 28, "maximum": 45},
        "importance": "required",
        "hard_constraint": True,
        "allow_unknown": False,
        "allow_system_relaxation": False,
    }
]


def _eligible(**overrides: Any) -> tuple[bool, list[str]]:
    kwargs: dict[str, Any] = {
        "profile_status": "active",
        "approved_version_number": 1,
        "account_active": True,
        "age_years": 32,
        "minimum_age": 18,
        "completeness_recommendation_eligible": True,
        "has_approved_primary_photo": True,
        "require_primary_photo": True,
        "privacy_allows_matchmaking": True,
        "security_suspended": False,
        "preferences_valid": True,
    }
    return projections.eligibility(**(kwargs | overrides))


def test_fully_qualified_profile_is_eligible() -> None:
    eligible, reasons = _eligible()
    assert eligible
    assert reasons == []


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    [
        ({"profile_status": "paused_by_user"}, "profile_not_active"),
        ({"profile_status": "suspended"}, "profile_not_active"),
        ({"approved_version_number": None}, "no_approved_version"),
        ({"account_active": False}, "account_not_active"),
        ({"age_years": 17}, "below_minimum_age"),
        ({"age_years": None}, "age_unknown"),
        ({"completeness_recommendation_eligible": False}, "completeness_below_threshold"),
        ({"has_approved_primary_photo": False}, "no_approved_primary_photo"),
        ({"privacy_allows_matchmaking": False}, "matchmaking_visibility_not_granted"),
        ({"security_suspended": True}, "security_suspension"),
        ({"preferences_valid": False}, "partner_preferences_incomplete"),
    ],
)
def test_each_gate_removes_the_profile_from_the_pool(
    override: dict[str, Any], expected_reason: str
) -> None:
    eligible, reasons = _eligible(**override)
    assert not eligible
    assert expected_reason in reasons


def test_projection_carries_only_normalised_codes() -> None:
    payload = dict(COMPLETE_FIELDS)
    built = projections.build_payload(payload, age_years=32, criteria=CRITERIA)
    assert set(built) == projections.ALLOWED_PROJECTION_KEYS
    assert built["age_bucket"] == "30_34"
    assert built["faith_codes"]
    assert built["marital_status_code"] == "never_married"
    assert built["children_status_code"] == "no_children"


def test_narratives_and_contact_details_cannot_enter_the_projection() -> None:
    payload = dict(COMPLETE_FIELDS)
    payload["self_introduction.self_introduction"] = SELF_INTRODUCTION
    built = projections.build_payload(payload, age_years=32, criteria=CRITERIA)
    serialised = str(built)
    assert SELF_INTRODUCTION not in serialised
    for prohibited in PROHIBITED_PROJECTION_FIELDS:
        assert prohibited not in built


def test_an_unexpected_key_fails_closed() -> None:
    with pytest.raises(VavError) as error:
        projections.assert_no_prohibited_fields({"email": "member@example.com"})
    assert error.value.code == "DATING_PROJECTION_FIELD_NOT_ALLOWED"


def test_checksum_is_stable_and_version_sensitive() -> None:
    built = projections.build_payload(dict(COMPLETE_FIELDS), age_years=32, criteria=CRITERIA)
    first = projections.checksum(built, approved_version=1, preference_version=1, privacy_version=1)
    same = projections.checksum(built, approved_version=1, preference_version=1, privacy_version=1)
    changed = projections.checksum(
        built, approved_version=1, preference_version=2, privacy_version=1
    )
    assert first == same
    assert first != changed


@pytest.mark.parametrize(
    ("age", "bucket"),
    [
        (None, None),
        (19, "18_24"),
        (27, "25_29"),
        (33, "30_34"),
        (38, "35_39"),
        (45, "40_49"),
        (55, "50_59"),
        (70, "60_plus"),
    ],
)
def test_age_buckets_are_coarse(age: int | None, bucket: str | None) -> None:
    assert age_bucket(age) == bucket
