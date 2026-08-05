"""Offline evaluation metrics and release gating."""

from __future__ import annotations

from vav.modules.recommendations.evaluation import (
    GUARDRAIL_METRICS,
    RELEASE_BLOCKING_METRICS,
    catalog_coverage,
    evaluate,
    gini_bps,
    ndcg_at_k,
    pairwise_agreement,
    precision_at_k,
    qualified_exposure_gap_bps,
    rate_bps,
)


def test_rates_are_basis_points_and_bounded() -> None:
    assert rate_bps(1, 4) == 2_500
    assert rate_bps(5, 4) == 10_000
    assert rate_bps(1, 0) == 0


def test_ranking_metrics_behave_as_expected() -> None:
    assert ndcg_at_k([3, 2, 1], 3) == 10_000
    assert ndcg_at_k([1, 2, 3], 3) < 10_000
    assert ndcg_at_k([], 3) == 0
    assert precision_at_k([1, 0, 1], 3) == 6_667
    assert pairwise_agreement([9, 5, 1], [2, 1, 0]) == 10_000


def test_coverage_and_concentration_metrics() -> None:
    assert catalog_coverage({"a", "b"}, {"a", "b", "c", "d"}) == 5_000
    assert gini_bps([5, 5, 5]) == 0
    assert gini_bps([0, 0, 30]) > 5_000
    assert gini_bps([]) == 0


def test_fairness_compares_equally_qualified_groups() -> None:
    gap = qualified_exposure_gap_bps({"a": (5, 10), "b": (9, 10)})
    assert gap == 4_000
    assert qualified_exposure_gap_bps({"a": (5, 10)}) == 0


def test_any_correctness_violation_blocks_a_release() -> None:
    for metric in RELEASE_BLOCKING_METRICS:
        result = evaluate(
            dataset_code="d",
            strategy_code="s",
            strategy_version="1.0.0",
            metrics={metric: 1},
        )
        assert not result.passed
        assert metric in result.blocking_failures


def test_guardrails_are_compared_against_configured_thresholds() -> None:
    result = evaluate(
        dataset_code="d",
        strategy_code="s",
        strategy_version="1.0.0",
        metrics={"report_rate_bps": 500},
        guardrail_thresholds={"report_rate_bps": 100},
    )
    assert not result.passed
    assert "report_rate_bps" in result.guardrail_failures
    assert set(result.guardrail_failures) <= set(GUARDRAIL_METRICS)


def test_a_clean_run_passes() -> None:
    result = evaluate(
        dataset_code="d",
        strategy_code="s",
        strategy_version="1.0.0",
        metrics={metric: 0 for metric in RELEASE_BLOCKING_METRICS},
    )
    assert result.passed
    assert result.blocking_failures == []


def test_click_metrics_alone_cannot_pass_a_strategy() -> None:
    result = evaluate(
        dataset_code="d",
        strategy_code="s",
        strategy_version="1.0.0",
        metrics={"like_rate_bps": 9_000, "hard_constraint_violation_rate_bps": 5},
    )
    assert not result.passed
