"""Unknown-value handling and member-permitted relaxation."""

from __future__ import annotations

from vav.modules.recommendations import constraints

from ..helpers import criterion, projection


def _candidate(**overrides):
    return projection(
        gender_code="male", eligible_partner_gender_codes=["female"], age_years=35, **overrides
    )


def _evaluate(viewer_criteria, *, candidate=None, allow_relaxation=False):
    return constraints.evaluate_pair(
        viewer_projection=projection(),
        candidate_projection=candidate or _candidate(),
        viewer_criteria=viewer_criteria,
        candidate_criteria=[],
        viewer_preference_version=1,
        candidate_preference_version=1,
        minimum_age=18,
        allow_viewer_relaxation=allow_relaxation,
    )


def test_unknown_value_is_not_treated_as_a_failure_by_default() -> None:
    evaluation = _evaluate(
        [
            criterion(
                "marital_status_code", "equals", "never_married", hard=True, allow_unknown=True
            )
        ],
        candidate=_candidate(marital_status_code=None),
    )
    assert evaluation.passed
    assert "viewer_to_candidate:marital_status_code" in evaluation.unknown_codes


def test_a_member_can_require_the_value_to_be_known() -> None:
    evaluation = _evaluate(
        [
            criterion(
                "marital_status_code", "equals", "never_married", hard=True, allow_unknown=False
            )
        ],
        candidate=_candidate(marital_status_code=None),
    )
    assert not evaluation.passed
    assert "viewer_to_candidate:marital_status_code" in evaluation.blocking_codes


def test_relaxation_requires_both_the_member_permission_and_the_platform_flag() -> None:
    permitted = criterion("city_code", "equals", "beijing", hard=True, allow_system_relaxation=True)
    forbidden = criterion("city_code", "equals", "beijing", hard=True)

    assert _evaluate([permitted], allow_relaxation=True).passed
    assert not _evaluate([permitted], allow_relaxation=False).passed
    assert not _evaluate([forbidden], allow_relaxation=True).passed


def test_relaxed_criteria_are_recorded_so_the_member_can_be_told() -> None:
    evaluation = _evaluate(
        [criterion("city_code", "equals", "beijing", hard=True, allow_system_relaxation=True)],
        allow_relaxation=True,
    )
    assert evaluation.relaxed_codes == ["viewer_to_candidate:city_code"]


def test_relationship_eligibility_cannot_be_relaxed_even_with_permission() -> None:
    evaluation = constraints.evaluate_pair(
        viewer_projection=projection(eligible_partner_gender_codes=["female"]),
        candidate_projection=_candidate(),
        viewer_criteria=[
            criterion(
                "relationship_eligibility",
                "equals",
                "male",
                hard=True,
                allow_system_relaxation=True,
            )
        ],
        candidate_criteria=[],
        viewer_preference_version=1,
        candidate_preference_version=1,
        minimum_age=18,
        allow_viewer_relaxation=True,
    )
    assert not evaluation.passed


def test_operator_semantics_return_none_only_for_unknown_values() -> None:
    assert constraints.evaluate_operator("equals", "a", None) is None
    assert constraints.evaluate_operator("equals", "a", "a") is True
    assert constraints.evaluate_operator("in", ["a", "b"], "b") is True
    assert constraints.evaluate_operator("contains_any", ["a"], ["b"]) is False
    assert constraints.evaluate_operator("contains_all", ["a", "b"], ["a", "b", "c"]) is True
    assert constraints.evaluate_operator("range", {"minimum": 1, "maximum": 3}, 2) is True
    assert constraints.evaluate_operator("at_least", 3, 4) is True
    assert constraints.evaluate_operator("at_most", 3, 4) is False
    assert constraints.evaluate_operator("boolean", False, False) is True
