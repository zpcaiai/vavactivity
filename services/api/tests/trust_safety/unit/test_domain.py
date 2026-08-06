from uuid import uuid4

import pytest

from vav.modules.trust_safety.domain import (
    CASE_TRANSITIONS,
    REPORT_TRANSITIONS,
    canonical_pair,
    classify_text,
    evaluate_condition,
    requires_second_approval,
    validate_transition,
)


def test_report_and_case_state_machines_reject_skips() -> None:
    validate_transition("submitted", "triaged", REPORT_TRANSITIONS)
    validate_transition("resolved", "reopened", CASE_TRANSITIONS)
    with pytest.raises(ValueError):
        validate_transition("submitted", "closed", REPORT_TRANSITIONS)
    with pytest.raises(ValueError):
        validate_transition("open", "resolved", CASE_TRANSITIONS)


def test_canonical_pair_is_direction_independent_and_rejects_self() -> None:
    first, second = uuid4(), uuid4()
    assert canonical_pair(first, second) == canonical_pair(second, first)
    with pytest.raises(ValueError):
        canonical_pair(first, first)


def test_high_impact_restrictions_require_four_eyes() -> None:
    assert requires_second_approval("account_permanently_disabled", None)
    assert requires_second_approval("invitation_disabled", 24 * 31)
    assert not requires_second_approval("invitation_disabled", 24)


def test_static_moderation_distinguishes_faith_content_from_safety_risk() -> None:
    assert not classify_text("我喜欢读圣经，也参加本地教会活动。")
    assert "money_request" in classify_text("请买礼品卡，然后把号码发给我")
    assert "threat" in classify_text("I will hurt you if you refuse")
    assert "contact_information_bypass" in classify_text("微 信: hidden_contact_123")


def test_rule_dsl_only_accepts_registered_signals_and_operators() -> None:
    assert evaluate_condition(
        {"signal": "like_rate", "operator": "gte", "value": 10}, {"like_rate": 12}
    )
    with pytest.raises(ValueError):
        evaluate_condition(
            {"signal": "religion", "operator": "eq", "value": "x"}, {"religion": "x"}
        )
    with pytest.raises(ValueError):
        evaluate_condition(
            {"signal": "like_rate", "operator": "exec", "value": "import os"},
            {"like_rate": 1},
        )
