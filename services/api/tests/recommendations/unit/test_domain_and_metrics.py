"""Domain state machines, invariants and offline ranking metrics."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from vav.modules.recommendations import evaluation
from vav.modules.recommendations.domain import (
    BATCH_TRANSITIONS,
    CANDIDATE_INVALIDATION_EVENTS,
    GUARDRAIL_METRICS,
    ITEM_TRANSITIONS,
    PROHIBITED_SCORING_SIGNALS,
    RecommendationBatchStatus,
    RecommendationItemStatus,
    can_transition_batch,
    can_transition_item,
    normalise_pair,
)
from vav.modules.recommendations.strategy import FEATURE_MANIFEST, HARD_CONSTRAINT_CRITERIA


def test_a_pair_has_exactly_one_ordering_whoever_asked() -> None:
    left = UUID("00000000-0000-0000-0000-00000000000a")
    right = UUID("ffffffff-0000-0000-0000-00000000000b")
    assert normalise_pair(left, right) == normalise_pair(right, left)
    assert normalise_pair(left, right) == (left, right)


def test_a_member_can_never_be_paired_with_themselves() -> None:
    same = uuid4()
    with pytest.raises(ValueError):
        normalise_pair(same, same)


def test_the_batch_lifecycle_only_moves_forward() -> None:
    assert can_transition_batch("building", "validating")
    assert can_transition_batch("ready", "active")
    assert can_transition_batch("active", "exhausted")
    assert not can_transition_batch("building", "active")
    assert not can_transition_batch("expired", "active")
    assert not can_transition_batch("cancelled", "ready")
    assert not can_transition_batch("nonsense", "active")


def test_terminal_batch_states_are_terminal() -> None:
    for state in (RecommendationBatchStatus.EXPIRED, RecommendationBatchStatus.CANCELLED):
        assert BATCH_TRANSITIONS[state] == frozenset()


def test_an_item_can_always_be_invalidated_before_it_is_terminal() -> None:
    for state, allowed in ITEM_TRANSITIONS.items():
        if state in {RecommendationItemStatus.INVALIDATED, RecommendationItemStatus.EXPIRED}:
            assert allowed == frozenset()
        else:
            assert RecommendationItemStatus.INVALIDATED in allowed


def test_the_item_lifecycle_refuses_impossible_moves() -> None:
    assert can_transition_item("ready", "exposed")
    assert can_transition_item("exposed", "viewed")
    assert can_transition_item("viewed", "acted")
    assert not can_transition_item("ready", "acted")
    assert not can_transition_item("invalidated", "ready")


def test_privacy_safety_and_preference_changes_all_invalidate_candidates() -> None:
    for event in (
        "dating_profile.paused",
        "dating_profile.privacy_updated",
        "dating_profile.preference_updated",
        "moderation.block.created",
        "privacy.erasure.started",
        "matchmaking.relationship.started",
    ):
        assert event in CANDIDATE_INVALIDATION_EVENTS


def test_no_prohibited_signal_ever_appears_in_the_feature_manifest() -> None:
    codes = {feature["feature_code"] for feature in FEATURE_MANIFEST}
    assert not codes & PROHIBITED_SCORING_SIGNALS
    fields = {feature["projection_field"] for feature in FEATURE_MANIFEST}
    for banned in ("photo", "face", "income", "salary", "payment", "conversation"):
        assert not any(banned in field for field in fields)


def test_appearance_income_and_counselling_can_never_be_scored() -> None:
    for signal in (
        "photo_attractiveness",
        "facial_features",
        "ethnicity_inference",
        "income_inference",
        "counseling_records",
        "ai_conversation_content",
        "spend_amount",
    ):
        assert signal in PROHIBITED_SCORING_SIGNALS


def test_every_feature_declares_a_sensitivity_and_an_explanation_code() -> None:
    for feature in FEATURE_MANIFEST:
        assert feature["sensitivity"] in {"restricted", "confidential"}
        assert feature["explanation_code"]
        assert 0 <= int(feature["default_weight"]) <= 100
        criterion = feature.get("preference_criterion")
        assert criterion is None or isinstance(criterion, str)


def test_hard_constraint_criteria_are_an_explicit_allow_list() -> None:
    assert "relationship_eligibility" in HARD_CONSTRAINT_CRITERIA
    # Nothing about money, looks or inferred class may act as a hard filter.
    for banned in ("income", "photo", "attractiveness", "spend", "social_class"):
        assert not any(banned in code for code in HARD_CONSTRAINT_CRITERIA)


def test_a_release_is_decided_by_safety_guardrails_not_engagement() -> None:
    assert {
        "report_rate",
        "block_rate",
        "privacy_violation_rate",
        "hard_constraint_violation_rate",
        "empty_result_rate",
    } <= set(GUARDRAIL_METRICS)
    for engagement in ("click_through_rate", "dwell_time", "session_length"):
        assert engagement not in GUARDRAIL_METRICS


# --- offline metrics ------------------------------------------------------


def test_ndcg_rewards_putting_the_best_result_first() -> None:
    assert evaluation.ndcg_at_k([3, 2, 1], 3) == 10000
    assert evaluation.ndcg_at_k([1, 2, 3], 3) < 10000
    assert evaluation.ndcg_at_k([0, 0, 0], 3) == 0
    assert evaluation.ndcg_at_k([], 3) == 0


def test_ndcg_only_looks_at_the_first_k_positions() -> None:
    assert evaluation.ndcg_at_k([3, 0, 0, 0], 1) == 10000
    assert evaluation.ndcg_at_k([0, 3, 3], 1) == 0


def test_precision_counts_relevant_results_in_the_window() -> None:
    assert evaluation.precision_at_k([1, 1, 0, 0], 2) == 10000
    assert evaluation.precision_at_k([1, 0, 0, 0], 4) == 2500
    assert evaluation.precision_at_k([], 5) == 0
    assert evaluation.precision_at_k([2, 0], 2, threshold=2) == 5000
