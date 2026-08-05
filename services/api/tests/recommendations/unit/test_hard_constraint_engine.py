"""Bidirectional hard-constraint evaluation."""

from __future__ import annotations

from vav.modules.recommendations import constraints

from ..helpers import criterion, projection


def _evaluate(viewer_criteria=None, candidate_criteria=None, **candidate_overrides):
    return constraints.evaluate_pair(
        viewer_projection=projection(),
        candidate_projection=projection(
            gender_code="male",
            eligible_partner_gender_codes=["female"],
            age_years=35,
            **candidate_overrides,
        ),
        viewer_criteria=viewer_criteria or [],
        candidate_criteria=candidate_criteria or [],
        viewer_preference_version=1,
        candidate_preference_version=1,
        minimum_age=18,
    )


def test_pair_passes_when_both_directions_accept() -> None:
    evaluation = _evaluate(
        viewer_criteria=[
            criterion("age_range", "range", {"minimum": 30, "maximum": 40}, hard=True)
        ],
        candidate_criteria=[
            criterion("age_range", "range", {"minimum": 28, "maximum": 38}, hard=True)
        ],
    )
    assert evaluation.passed
    assert evaluation.blocking_codes == []


def test_either_side_can_block_the_pair() -> None:
    viewer_blocks = _evaluate(
        viewer_criteria=[criterion("age_range", "range", {"minimum": 20, "maximum": 30}, hard=True)]
    )
    assert not viewer_blocks.passed
    assert "viewer_to_candidate:age_range" in viewer_blocks.blocking_codes

    candidate_blocks = _evaluate(
        candidate_criteria=[
            criterion("age_range", "range", {"minimum": 20, "maximum": 25}, hard=True)
        ]
    )
    assert not candidate_blocks.passed
    assert "candidate_to_viewer:age_range" in candidate_blocks.blocking_codes


def test_relationship_eligibility_is_checked_in_both_directions() -> None:
    evaluation = constraints.evaluate_pair(
        viewer_projection=projection(eligible_partner_gender_codes=["female"]),
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
        viewer_criteria=[],
        candidate_criteria=[],
        viewer_preference_version=1,
        candidate_preference_version=1,
        minimum_age=18,
    )
    assert not evaluation.passed
    assert any("relationship_eligibility" in code for code in evaluation.blocking_codes)


def test_adult_eligibility_is_a_platform_rule_not_a_member_setting() -> None:
    evaluation = constraints.evaluate_pair(
        viewer_projection=projection(),
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"], age_years=17
        ),
        viewer_criteria=[],
        candidate_criteria=[],
        viewer_preference_version=1,
        candidate_preference_version=1,
        minimum_age=18,
    )
    assert not evaluation.passed
    assert "viewer_to_candidate:adult_eligibility" in evaluation.blocking_codes


def test_only_criteria_marked_hard_can_exclude() -> None:
    evaluation = _evaluate(
        viewer_criteria=[
            criterion("city_code", "equals", "beijing", importance="very_important", hard=False)
        ]
    )
    assert evaluation.passed


def test_faith_and_marital_criteria_are_evaluated_from_the_projection() -> None:
    passing = _evaluate(
        viewer_criteria=[
            criterion("faith_status_code", "in", ["believer_baptized"], hard=True),
            criterion("marital_status_code", "equals", "never_married", hard=True),
        ]
    )
    assert passing.passed

    failing = _evaluate(
        viewer_criteria=[criterion("marital_status_code", "equals", "widowed", hard=True)]
    )
    assert not failing.passed


def test_diagnostics_aggregate_criteria_without_identifying_members() -> None:
    failures = [
        _evaluate(
            viewer_criteria=[
                criterion("age_range", "range", {"minimum": 20, "maximum": 25}, hard=True)
            ]
        )
        for _ in range(3)
    ]
    aggregated = constraints.aggregate_failure_reasons(failures)
    assert aggregated["age_range"] == 3
    assert all(":" not in key for key in aggregated)
