"""Offline recommendation evaluation metrics and release guardrails.

Correctness metrics (hard-constraint violations, blocked-pair leakage, privacy
leakage) are release blocking and must be exactly zero. Ranking-quality metrics
are informative only: a better NDCG can never unlock a strategy that violates a
member's stated conditions.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from math import log2
from typing import Any

EVALUATION_POLICY_VERSION = "1.0.0"

#: Metrics that must be zero for a strategy to be activated.
RELEASE_BLOCKING_METRICS: tuple[str, ...] = (
    "hard_constraint_violation_rate_bps",
    "eligibility_violation_rate_bps",
    "blocked_pair_leakage_rate_bps",
    "privacy_violation_rate_bps",
    "safety_restriction_violation_rate_bps",
    "contact_information_leakage_rate_bps",
    "unapproved_profile_exposure_rate_bps",
)

#: Guardrails compared against configured thresholds instead of zero.
GUARDRAIL_METRICS: tuple[str, ...] = (
    "report_rate_bps",
    "block_rate_bps",
    "severe_negative_feedback_rate_bps",
    "empty_result_rate_bps",
    "pool_opt_out_rate_bps",
    "exposure_gini_bps",
)


@dataclass(frozen=True)
class EvaluationResult:
    dataset_code: str
    strategy_code: str
    strategy_version: str
    metrics: dict[str, int]
    passed: bool
    blocking_failures: list[str] = field(default_factory=list)
    guardrail_failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_code": self.dataset_code,
            "strategy_code": self.strategy_code,
            "strategy_version": self.strategy_version,
            "metrics": self.metrics,
            "passed": self.passed,
            "blocking_failures": self.blocking_failures,
            "guardrail_failures": self.guardrail_failures,
            "policy_version": EVALUATION_POLICY_VERSION,
        }


def rate_bps(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int(round(min(1.0, numerator / denominator) * 10_000))


def ndcg_at_k(relevances: list[int], k: int) -> int:
    """NDCG in basis points for a ranked relevance list."""
    if k <= 0 or not relevances:
        return 0
    top = relevances[:k]
    gain = sum((2**value - 1) / log2(index + 2) for index, value in enumerate(top))
    ideal_order = sorted(relevances, reverse=True)[:k]
    ideal = sum((2**value - 1) / log2(index + 2) for index, value in enumerate(ideal_order))
    if ideal == 0:
        return 0
    return int(round(min(1.0, gain / ideal) * 10_000))


def precision_at_k(relevances: list[int], k: int, *, threshold: int = 1) -> int:
    if k <= 0 or not relevances:
        return 0
    top = relevances[:k]
    hits = sum(1 for value in top if value >= threshold)
    return rate_bps(hits, len(top))


def pairwise_agreement(predicted: list[int], observed: list[int]) -> int:
    """Share of candidate pairs ordered the same way by score and by outcome."""
    if len(predicted) != len(observed) or len(predicted) < 2:
        return 0
    agree = 0
    total = 0
    for i in range(len(predicted)):
        for j in range(i + 1, len(predicted)):
            if observed[i] == observed[j]:
                continue
            total += 1
            if (predicted[i] - predicted[j]) * (observed[i] - observed[j]) > 0:
                agree += 1
    return rate_bps(agree, total)


def catalog_coverage(exposed_profiles: set[str], eligible_profiles: set[str]) -> int:
    return rate_bps(len(exposed_profiles & eligible_profiles), len(eligible_profiles))


def gini_bps(values: list[int]) -> int:
    """Exposure concentration; 0 means perfectly even, 10000 fully concentrated."""
    if not values:
        return 0
    ordered = sorted(values)
    total = sum(ordered)
    if total == 0:
        return 0
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    gini = (2 * weighted) / (count * total) - (count + 1) / count
    return int(round(max(0.0, min(1.0, gini)) * 10_000))


def qualified_exposure_gap_bps(group_exposure: dict[str, tuple[int, int]]) -> int:
    """Largest exposure-rate gap between equally qualified groups.

    Each entry is ``(exposed_count, qualified_count)``; comparing anything but
    equally qualified populations would justify pushing unsuitable profiles.
    """
    rates = [
        rate_bps(exposed, qualified)
        for exposed, qualified in group_exposure.values()
        if qualified > 0
    ]
    if len(rates) < 2:
        return 0
    return max(rates) - min(rates)


def evaluate(
    *,
    dataset_code: str,
    strategy_code: str,
    strategy_version: str,
    metrics: dict[str, int],
    guardrail_thresholds: dict[str, int] | None = None,
) -> EvaluationResult:
    """Apply release rules to a computed metric set."""
    blocking = [name for name in RELEASE_BLOCKING_METRICS if int(metrics.get(name, 0)) > 0]
    thresholds = guardrail_thresholds or {}
    guardrails = [
        name
        for name in GUARDRAIL_METRICS
        if name in thresholds and int(metrics.get(name, 0)) > int(thresholds[name])
    ]
    return EvaluationResult(
        dataset_code=dataset_code,
        strategy_code=strategy_code,
        strategy_version=strategy_version,
        metrics=metrics,
        passed=not blocking and not guardrails,
        blocking_failures=blocking,
        guardrail_failures=guardrails,
    )
