"""Bidirectional hard-constraint evaluation."""

# ruff: noqa: E501
from __future__ import annotations

from vav.modules.recommendations import constraints
from vav.modules.recommendations.domain import NEVER_RELAXABLE_CONSTRAINTS

from ..helpers import criterion, projection


def _evaluate(**kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "viewer_projection": projection(),
        "candidate_projection": projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
        "viewer_criteria": [],
        "candidate_criteria": [],
        "viewer_preference_version": 1,
        "candidate_preference_version": 1,
    }
    return constraints.evaluate_pair(**{**defaults, **kwargs})


def test_compatible_pair_passes() -> None:
    result = _evaluate()
    assert result["passed"]
    assert result["blocking_codes"] == []


def test_relationship_eligibility_must_be_mutual() -> None:
    # The viewer accepts men, but this man only wants men.
    result = _evaluate(
        candidate_projection=projection(gender_code="male", eligible_partner_gender_codes=["male"])
    )
    assert not result["passed"]
    assert "relationship_eligibility" in result["blocking_codes"]
    assert result["relationship_eligibility_reason"] == "candidate_does_not_accept_viewer"


def test_viewer_preference_is_never_widened_by_the_system() -> None:
    result = _evaluate(
        viewer_projection=projection(eligible_partner_gender_codes=["female"]),
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
    )
    assert not result["passed"]
    assert result["relationship_eligibility_reason"] == "viewer_does_not_accept_candidate"


def test_viewer_hard_age_range_excludes_out_of_range_candidate() -> None:
    result = _evaluate(
        viewer_criteria=[
            criterion(
                "age_range",
                "range",
                {"minimum": 25, "maximum": 30},
                hard=True,
                importance="required",
            )
        ],
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"], age_years=44
        ),
    )
    assert not result["passed"]
    assert "age_range" in result["blocking_codes"]


def test_candidate_hard_constraint_also_excludes_the_viewer() -> None:
    """A is happy with B, but B's own hard rule rejects A."""
    result = _evaluate(
        candidate_criteria=[
            criterion(
                "age_range",
                "range",
                {"minimum": 20, "maximum": 25},
                hard=True,
                importance="required",
            )
        ],
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
    )
    assert not result["passed"]
    assert "age_range" in result["blocking_codes"]
    directions = {item["direction"] for item in result["candidate_constraints"]}
    assert directions == {"candidate_to_viewer"}


def test_a_blank_field_is_unknown_not_a_failure() -> None:
    result = _evaluate(
        viewer_criteria=[
            criterion(
                "marital_status_code",
                "in",
                ["never_married"],
                hard=True,
                importance="required",
                allow_unknown=True,
            )
        ],
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"], marital_status_code=None
        ),
    )
    assert result["passed"]
    assert "marital_status_code" in result["unknown_codes"]


def test_a_member_may_choose_to_exclude_unknowns() -> None:
    result = _evaluate(
        viewer_criteria=[
            criterion(
                "marital_status_code",
                "in",
                ["never_married"],
                hard=True,
                importance="required",
                allow_unknown=False,
            )
        ],
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"], marital_status_code=None
        ),
    )
    assert not result["passed"]
    assert "marital_status_code" in result["blocking_codes"]


def test_soft_criteria_never_exclude() -> None:
    result = _evaluate(
        viewer_criteria=[
            criterion(
                "faith_status_code", "in", ["seeker"], hard=False, importance="very_important"
            )
        ]
    )
    assert result["passed"]


def test_unapproved_criteria_cannot_exclude_anyone() -> None:
    result = _evaluate(
        viewer_criteria=[
            criterion("income_level", "at_least", 100000, hard=True, importance="required")
        ]
    )
    assert result["passed"]
    codes = {item["reason_code"] for item in result["viewer_constraints"]}
    assert "criterion_not_approved_for_hard_filtering" in codes


def test_relaxation_requires_member_permission_and_an_allowed_criterion() -> None:
    far_away = projection(
        gender_code="male",
        eligible_partner_gender_codes=["female"],
        city_code="chengdu",
    )
    strict = _evaluate(
        viewer_criteria=[
            criterion(
                "city_code",
                "in",
                ["shanghai"],
                hard=True,
                importance="required",
                allow_relaxation=True,
            )
        ],
        candidate_projection=far_away,
        viewer_allows_relaxation=False,
    )
    assert not strict["passed"]

    relaxed = _evaluate(
        viewer_criteria=[
            criterion(
                "city_code",
                "in",
                ["shanghai"],
                hard=True,
                importance="required",
                allow_relaxation=True,
            )
        ],
        candidate_projection=far_away,
        viewer_allows_relaxation=True,
    )
    assert relaxed["passed"]
    assert relaxed["relaxations_applied"] == ["city_code"]


def test_the_other_partys_constraints_are_never_relaxed_for_the_viewer() -> None:
    result = _evaluate(
        candidate_criteria=[
            criterion(
                "city_code",
                "in",
                ["beijing"],
                hard=True,
                importance="required",
                allow_relaxation=True,
            )
        ],
        candidate_projection=projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
        viewer_allows_relaxation=True,
    )
    assert not result["passed"]
    assert "city_code" in result["blocking_codes"]


def test_safety_and_eligibility_are_never_relaxable() -> None:
    assert "relationship_eligibility" in NEVER_RELAXABLE_CONSTRAINTS
    assert "safety_block" in NEVER_RELAXABLE_CONSTRAINTS
    assert "adult_eligibility" in NEVER_RELAXABLE_CONSTRAINTS


def test_diagnostics_are_aggregate_and_name_nobody() -> None:
    evaluations = [
        {"passed": False, "blocking_codes": ["age_range"], "unknown_codes": []},
        {
            "passed": False,
            "blocking_codes": ["age_range", "city_code"],
            "unknown_codes": ["faith_status_code"],
        },
        {"passed": True, "blocking_codes": [], "unknown_codes": []},
    ]
    summary = constraints.diagnostic_summary(evaluations)
    assert summary["evaluated_pairs"] == 3
    assert summary["passed_pairs"] == 1
    assert summary["pass_rate_bps"] == 3333
    assert summary["blocking_criteria"]["age_range"] == 2
    assert summary["aggregate_only"] is True
    assert "user_id" not in str(summary)
