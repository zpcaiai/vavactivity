"""Strategy versioning and policy documents."""

from __future__ import annotations

from vav.modules.recommendations.domain import (
    RecommendationBatchStatus,
    RecommendationItemStatus,
    RecommendationStrategyStatus,
    can_transition_batch,
    can_transition_item,
    can_transition_strategy,
    clamp_bps,
)
from vav.modules.recommendations.strategy import (
    BASELINE_STRATEGY_CODE,
    baseline_strategy_payload,
)


def test_baseline_strategy_carries_every_required_policy() -> None:
    payload = baseline_strategy_payload()
    assert payload["strategy_code"] == BASELINE_STRATEGY_CODE
    for key in (
        "hard_constraint_policy",
        "feature_manifest",
        "scoring_policy",
        "bidirectional_policy",
        "ranking_policy",
        "diversification_policy",
        "exposure_policy",
        "explanation_policy",
        "cold_start_policy",
    ):
        assert payload[key], key


def test_policies_are_versioned() -> None:
    payload = baseline_strategy_payload()
    assert payload["hard_constraint_policy"]["policy_version"]
    assert payload["scoring_policy"]["policy_version"]
    assert payload["bidirectional_policy"]["policy_version"]
    assert payload["explanation_policy"]["policy_version"]


def test_automatic_relaxation_is_off_and_diversification_cannot_bypass_constraints() -> None:
    payload = baseline_strategy_payload()
    assert payload["hard_constraint_policy"]["auto_relax"] is False
    assert payload["diversification_policy"]["bypasses_hard_constraints"] is False
    assert payload["explanation_policy"]["shows_numeric_score"] is False
    assert payload["explanation_policy"]["shows_other_member_preferences"] is False


def test_strategy_lifecycle_transitions() -> None:
    assert can_transition_strategy(
        RecommendationStrategyStatus.APPROVED.value, RecommendationStrategyStatus.ACTIVE.value
    )
    assert not can_transition_strategy(
        RecommendationStrategyStatus.DRAFT.value, RecommendationStrategyStatus.ACTIVE.value
    )
    assert can_transition_strategy(
        RecommendationStrategyStatus.ACTIVE.value, RecommendationStrategyStatus.ROLLED_BACK.value
    )
    assert not can_transition_strategy("nonsense", "active")


def test_batch_and_item_lifecycles() -> None:
    assert can_transition_batch(
        RecommendationBatchStatus.READY.value, RecommendationBatchStatus.ACTIVE.value
    )
    assert not can_transition_batch(
        RecommendationBatchStatus.EXPIRED.value, RecommendationBatchStatus.ACTIVE.value
    )
    assert can_transition_item(
        RecommendationItemStatus.READY.value, RecommendationItemStatus.EXPOSED.value
    )
    assert not can_transition_item(
        RecommendationItemStatus.INVALIDATED.value, RecommendationItemStatus.READY.value
    )


def test_basis_points_are_clamped() -> None:
    assert clamp_bps(-5) == 0
    assert clamp_bps(20_000) == 10_000
    assert clamp_bps(4_999.6) == 5_000
