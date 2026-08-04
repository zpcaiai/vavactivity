"""Partner-preference criteria validation."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.modules.matchmaking_profiles import preferences


def _criterion(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "criterion_code": "age_range",
        "operator": "range",
        "desired_value": {"minimum": 28, "maximum": 45},
        "importance": "required",
        "hard_constraint": True,
        "allow_unknown": False,
        "allow_system_relaxation": False,
    }
    return base | overrides


def test_age_range_is_accepted_and_normalised() -> None:
    result = preferences.validate_criterion(_criterion())
    assert result["desired_value"] == {"minimum": 28, "maximum": 45}
    assert result["hard_constraint"] is True


def test_criteria_outside_the_approved_set_are_rejected() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criterion(
            _criterion(criterion_code="income_level", operator="at_least", desired_value=100000)
        )
    assert error.value.code == "DATING_PREFERENCE_INVALID"


def test_operator_must_be_allowed_for_the_criterion() -> None:
    with pytest.raises(VavError):
        preferences.validate_criterion(_criterion(operator="contains_all"))


def test_age_range_cannot_start_below_the_platform_minimum() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criterion(_criterion(desired_value={"minimum": 16, "maximum": 30}))
    assert "minimum" in error.value.message


def test_inverted_range_is_rejected() -> None:
    with pytest.raises(VavError):
        preferences.validate_criterion(_criterion(desired_value={"minimum": 40, "maximum": 30}))


def test_hard_constraint_must_be_marked_required() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criterion(_criterion(importance="nice_to_have"))
    assert "required" in error.value.message


def test_relaxing_a_hard_constraint_needs_explicit_acknowledgement() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criterion(_criterion(allow_system_relaxation=True))
    assert "acknowledgement" in error.value.message


def test_acknowledged_relaxation_is_accepted() -> None:
    result = preferences.validate_criterion(
        _criterion(allow_system_relaxation=True, relaxation_acknowledged=True)
    )
    assert result["allow_system_relaxation"] is True


def test_taxonomy_values_must_be_active() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criterion(
            _criterion(
                criterion_code="faith_status_code",
                operator="in",
                desired_value=["believer_baptized", "not_a_real_value"],
                hard_constraint=False,
                importance="important",
            )
        )
    assert "not_a_real_value" in error.value.message


def test_duplicate_criteria_are_rejected() -> None:
    with pytest.raises(VavError):
        preferences.validate_criteria([_criterion(), _criterion()])


def test_contradictory_children_criteria_are_explained() -> None:
    with pytest.raises(VavError) as error:
        preferences.validate_criteria(
            [
                _criterion(
                    criterion_code="has_children",
                    operator="boolean",
                    desired_value=True,
                    importance="required",
                    hard_constraint=True,
                ),
                _criterion(
                    criterion_code="open_to_partner_with_children",
                    operator="in",
                    desired_value=["prefer_not"],
                    importance="required",
                    hard_constraint=True,
                ),
            ]
        )
    assert error.value.code == "DATING_PREFERENCE_CONTRADICTION"


def test_hard_constraint_summary_lists_only_excluding_criteria() -> None:
    criteria = preferences.validate_criteria(
        [
            _criterion(),
            _criterion(
                criterion_code="faith_status_code",
                operator="in",
                desired_value=["believer_baptized"],
                importance="very_important",
                hard_constraint=False,
            ),
        ]
    )
    summary = preferences.hard_constraint_summary(criteria)
    assert [item["criterion_code"] for item in summary] == ["age_range"]
    assert summary[0]["excludes_unknown_values"] is True
