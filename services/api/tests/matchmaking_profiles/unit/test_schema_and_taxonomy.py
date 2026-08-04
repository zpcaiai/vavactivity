"""Schema manifest and taxonomy invariants."""

# ruff: noqa: E501
from __future__ import annotations

from vav.modules.matchmaking_profiles.domain import (
    DOMAIN_SENSITIVITY,
    PRIVACY_DATA_DOMAINS,
    PROFILE_SECTIONS,
    FieldSensitivity,
)
from vav.modules.matchmaking_profiles.taxonomies import (
    APPROVED_PREFERENCE_CRITERIA,
    FIELD_MANIFEST,
    TAXONOMIES,
    field_definition,
    taxonomy_value_codes,
)


def test_every_field_belongs_to_a_declared_section() -> None:
    for definition in FIELD_MANIFEST:
        assert definition["section_code"] in PROFILE_SECTIONS, definition["field_code"]


def test_field_codes_are_unique() -> None:
    codes = [definition["field_code"] for definition in FIELD_MANIFEST]
    assert len(codes) == len(set(codes))


def test_every_enum_field_points_at_an_existing_taxonomy() -> None:
    for definition in FIELD_MANIFEST:
        taxonomy = definition["value_schema"].get("taxonomy")
        if taxonomy:
            assert taxonomy in TAXONOMIES, definition["field_code"]


def test_faith_history_and_family_default_to_restricted() -> None:
    for definition in FIELD_MANIFEST:
        if definition["section_code"] in {"faith", "relationship_history", "family"}:
            assert definition["sensitivity"] == FieldSensitivity.RESTRICTED.value


def test_no_field_defaults_to_a_wide_open_visibility() -> None:
    allowed = {"private", "mutual_only", "verified_members"}
    for definition in FIELD_MANIFEST:
        assert definition["default_visibility"] in allowed, definition["field_code"]


def test_privacy_domains_all_carry_a_sensitivity_classification() -> None:
    assert set(PRIVACY_DATA_DOMAINS) == set(DOMAIN_SENSITIVITY)
    assert DOMAIN_SENSITIVITY["dating_profile.review_notes"] == FieldSensitivity.HIGHLY_RESTRICTED


def test_marriage_faith_importance_is_not_framed_as_a_spiritual_score() -> None:
    definition = field_definition("faith.marriage_faith_importance")
    assert definition is not None
    assert definition["value_schema"]["not_a_spiritual_score"] is True


def test_financial_lifestyle_does_not_collect_bank_or_asset_records() -> None:
    definition = field_definition("lifestyle.financial_attitude_codes")
    assert definition is not None
    assert definition["value_schema"]["no_bank_or_asset_records"] is True


def test_disabled_taxonomy_values_are_excluded_but_still_resolvable() -> None:
    active = taxonomy_value_codes("faith_status")
    historical = taxonomy_value_codes("faith_status", include_disabled=True)
    assert active <= historical


def test_every_approved_preference_criterion_declares_operators() -> None:
    for code, definition in APPROVED_PREFERENCE_CRITERIA.items():
        assert definition["operators"], code
        assert definition["projection_field"], code


def test_recommendation_required_fields_are_also_submission_required() -> None:
    for definition in FIELD_MANIFEST:
        if definition["required_for_recommendation"]:
            assert definition["required_for_submission"], definition["field_code"]
