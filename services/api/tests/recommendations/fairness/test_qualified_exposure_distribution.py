"""Exposure fairness is measured across equally qualified members."""

# ruff: noqa: E501
from __future__ import annotations

from vav.modules.recommendations.evaluation import (
    catalog_coverage,
    gini_bps,
    qualified_exposure_gap_bps,
    rate_bps,
)


def test_even_exposure_produces_no_concentration() -> None:
    assert gini_bps([4, 4, 4, 4]) == 0


def test_one_profile_taking_everything_is_flagged() -> None:
    assert gini_bps([0, 0, 0, 40]) > 6_000


def test_the_gap_is_computed_between_equally_qualified_groups() -> None:
    balanced = qualified_exposure_gap_bps({"region_a": (8, 10), "region_b": (8, 10)})
    skewed = qualified_exposure_gap_bps({"region_a": (9, 10), "region_b": (2, 10)})
    assert balanced == 0
    assert skewed == 7_000


def test_a_group_with_no_qualified_members_is_not_compared() -> None:
    assert qualified_exposure_gap_bps({"a": (5, 10), "b": (0, 0)}) == 0


def test_coverage_counts_only_eligible_profiles() -> None:
    assert catalog_coverage({"a", "b", "z"}, {"a", "b", "c", "d"}) == 5_000
    assert rate_bps(0, 0) == 0
