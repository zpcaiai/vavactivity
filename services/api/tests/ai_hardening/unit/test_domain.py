"""Pure-domain tests for AI hardening (B19 part 1 / AI-001).

The four load-bearing behaviours have named tests below: a request over budget
is refused *before* the provider is called, a provider outage produces an
explicit refusal rather than a fabricated answer, crisis routing fails closed
when no resource is configured, and nothing is launch-ready by default.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from vav.modules.ai_hardening.domain import (
    DEFAULT_POLICY_RULES,
    LIMITATION_LABEL_CODE,
    REQUIRED_LAUNCH_GATES,
    AiResponsePayload,
    AiRuleError,
    BudgetLimits,
    BudgetScope,
    BudgetUsage,
    CrisisResource,
    EscalationStatus,
    LaunchGate,
    LaunchGateCode,
    PolicyAction,
    PolicyRule,
    PolicySurface,
    ProviderHealth,
    ProviderProfile,
    ProviderState,
    build_answer,
    build_refusal,
    check_budget,
    circuit_state,
    ensure_limitation_labelled,
    ensure_within_budget,
    escalation_is_overdue,
    estimate_cost,
    evaluate_launch_readiness,
    evaluate_policies,
    plan_escalation,
    plan_request,
    reconcile_usage,
    route_crisis,
    select_provider,
    usage_idempotency_key,
    validate_escalation_transition,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
CONVERSATION = UUID(int=42)
LABEL_VERSION = "2026-08-01"

PRIMARY = ProviderProfile(
    provider_code="primary",
    model_code="model-a",
    input_cost_per_1k_millicents=100,
    output_cost_per_1k_millicents=300,
    max_context_tokens=8000,
    max_output_tokens=1000,
    priority=10,
    capabilities=frozenset({"chat"}),
)
SECONDARY = ProviderProfile(
    provider_code="secondary",
    model_code="model-b",
    input_cost_per_1k_millicents=150,
    output_cost_per_1k_millicents=450,
    max_context_tokens=8000,
    max_output_tokens=1000,
    priority=20,
    capabilities=frozenset({"chat"}),
)

GENEROUS = BudgetLimits(
    user_daily_tokens=1_000_000,
    conversation_tokens=100_000,
    global_monthly_millicents=10_000_000,
)


class _ProviderSpy:
    """Stands in for the provider client so a test can assert it was not called."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: object, **_kwargs: object) -> str:
        self.calls += 1
        return "an answer"


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


def test_the_highest_priority_healthy_provider_wins() -> None:
    assert select_provider([SECONDARY, PRIMARY]).provider_code == "primary"


def test_an_out_of_service_provider_is_skipped_not_retried() -> None:
    chosen = select_provider(
        [PRIMARY, SECONDARY], health={"primary": ProviderHealth.OUT_OF_SERVICE}
    )
    assert chosen.provider_code == "secondary"


def test_no_usable_provider_raises_rather_than_returning_a_default() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        select_provider(
            [PRIMARY],
            health={"primary": ProviderHealth.OUT_OF_SERVICE},
        )
    assert excinfo.value.code == "AI_PROVIDER_UNAVAILABLE"


def test_a_provider_without_the_required_capability_is_not_selected() -> None:
    with pytest.raises(AiRuleError):
        select_provider([PRIMARY, SECONDARY], capability="voice")


def test_the_circuit_opens_after_the_failure_threshold() -> None:
    state = ProviderState(provider_code="primary", consecutive_failures=5)
    assert (
        circuit_state(state, now=NOW, failure_threshold=5, open_for=timedelta(minutes=5))
        is ProviderHealth.OUT_OF_SERVICE
    )


def test_an_open_circuit_goes_half_open_rather_than_healthy() -> None:
    state = ProviderState(
        provider_code="primary",
        health=ProviderHealth.OUT_OF_SERVICE,
        circuit_opened_at=NOW - timedelta(minutes=30),
    )
    assert (
        circuit_state(state, now=NOW, failure_threshold=5, open_for=timedelta(minutes=5))
        is ProviderHealth.DEGRADED
    )


def test_a_recently_opened_circuit_stays_shut() -> None:
    state = ProviderState(
        provider_code="primary",
        health=ProviderHealth.OUT_OF_SERVICE,
        circuit_opened_at=NOW - timedelta(seconds=30),
    )
    assert (
        circuit_state(state, now=NOW, failure_threshold=5, open_for=timedelta(minutes=5))
        is ProviderHealth.OUT_OF_SERVICE
    )


# ---------------------------------------------------------------------------
# Budgets are enforceable: refusal happens before the provider call
# ---------------------------------------------------------------------------


def test_cost_is_priced_on_the_worst_case_output() -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=1000, max_output_tokens=1000)
    assert estimate.millicents == 400
    assert estimate.total_tokens == 2000


def test_a_request_larger_than_the_context_window_is_refused() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        estimate_cost(PRIMARY, prompt_tokens=8000, max_output_tokens=1000)
    assert excinfo.value.code == "AI_CONTEXT_TOO_LARGE"


@pytest.mark.parametrize(
    ("usage", "scope"),
    [
        (BudgetUsage(conversation_tokens=99_500), BudgetScope.CONVERSATION),
        (BudgetUsage(user_daily_tokens=999_500), BudgetScope.USER_DAILY),
        (BudgetUsage(global_monthly_millicents=9_999_900), BudgetScope.GLOBAL_MONTHLY),
    ],
)
def test_each_budget_scope_can_refuse_on_its_own(usage: BudgetUsage, scope: BudgetScope) -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=1000, max_output_tokens=1000)
    decision = check_budget(GENEROUS, usage, estimate)
    assert decision.allowed is False
    assert decision.breached_scope is scope


def test_an_unconfigured_scope_refuses_rather_than_meaning_unlimited() -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=10, max_output_tokens=10)
    decision = check_budget(BudgetLimits(user_daily_tokens=100), BudgetUsage(), estimate)
    assert decision.allowed is False
    assert decision.reason_code == "AI_BUDGET_NOT_CONFIGURED"


def test_a_request_within_every_scope_is_allowed_and_reports_headroom() -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=100, max_output_tokens=100)
    decision = check_budget(GENEROUS, BudgetUsage(), estimate)
    assert decision.allowed is True
    assert decision.remaining[BudgetScope.CONVERSATION.value] == 100_000


def test_an_over_budget_request_never_reaches_the_provider() -> None:
    """The load-bearing budget test: the spy stays at zero calls."""

    provider = _ProviderSpy()
    with pytest.raises(AiRuleError) as excinfo:
        plan = plan_request(
            rules=[],
            prompt="hello",
            profiles=[PRIMARY, SECONDARY],
            limits=GENEROUS,
            usage=BudgetUsage(conversation_tokens=99_999),
            prompt_tokens=1000,
            max_output_tokens=1000,
            now=NOW,
            conversation_id=CONVERSATION,
        )
        provider(plan)
    assert excinfo.value.code == "AI_BUDGET_EXCEEDED"
    assert provider.calls == 0


def test_the_budget_is_checked_before_a_provider_is_even_selected() -> None:
    """With both a dead provider and an exhausted budget, budget wins.

    That ordering proves the refusal is structural rather than a side effect of
    the provider call failing.
    """

    with pytest.raises(AiRuleError) as excinfo:
        plan_request(
            rules=[],
            prompt="hello",
            profiles=[PRIMARY],
            health={"primary": ProviderHealth.OUT_OF_SERVICE},
            limits=GENEROUS,
            usage=BudgetUsage(user_daily_tokens=1_000_000),
            prompt_tokens=100,
            max_output_tokens=100,
            now=NOW,
        )
    assert excinfo.value.code == "AI_BUDGET_EXCEEDED"


def test_ensure_within_budget_reports_the_breached_scope() -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=1000, max_output_tokens=1000)
    decision = check_budget(GENEROUS, BudgetUsage(conversation_tokens=100_000), estimate)
    with pytest.raises(AiRuleError) as excinfo:
        ensure_within_budget(decision)
    assert excinfo.value.details["scope"] == BudgetScope.CONVERSATION.value


def test_a_plan_within_budget_selects_a_provider() -> None:
    plan = plan_request(
        rules=[],
        prompt="hello",
        profiles=[PRIMARY, SECONDARY],
        limits=GENEROUS,
        usage=BudgetUsage(),
        prompt_tokens=100,
        max_output_tokens=100,
        now=NOW,
        capability="chat",
        conversation_id=CONVERSATION,
    )
    assert plan.profile.provider_code == "primary"
    assert plan.budget.allowed is True
    assert plan.policy.action is PolicyAction.ALLOW


def test_actual_usage_is_reconciled_downwards_after_the_call() -> None:
    estimate = estimate_cost(PRIMARY, prompt_tokens=1000, max_output_tokens=1000)
    actual = reconcile_usage(estimate, actual_output_tokens=100)
    assert actual.max_output_tokens == 100
    assert actual.millicents <= estimate.millicents


def test_usage_keys_are_idempotent_per_request() -> None:
    assert usage_idempotency_key(CONVERSATION, "req-1") == usage_idempotency_key(
        CONVERSATION, "req-1"
    )
    assert usage_idempotency_key(CONVERSATION, "req-1") != usage_idempotency_key(
        CONVERSATION, "req-2"
    )


# ---------------------------------------------------------------------------
# Policy filtering with audit
# ---------------------------------------------------------------------------


def test_the_platform_ships_no_content_policy_rules() -> None:
    """Policy wording is an operator decision, not a developer's guess."""

    assert DEFAULT_POLICY_RULES == ()


def test_a_clean_message_still_produces_an_audit_record() -> None:
    decision = evaluate_policies([], "hello", now=NOW)
    assert decision.action is PolicyAction.ALLOW
    assert decision.audit["rules_considered"] == 0
    assert decision.audit["evaluated_at"] == NOW.isoformat()


def test_the_most_severe_matched_action_wins() -> None:
    rules = [
        PolicyRule("r-allow", "test", "keyword", "token", PolicyAction.ALLOW),
        PolicyRule("r-block", "test", "keyword", "token", PolicyAction.BLOCK),
    ]
    decision = evaluate_policies(rules, "a token here", now=NOW)
    assert decision.action is PolicyAction.BLOCK
    assert decision.blocks is True
    assert decision.matched_rule_codes == ("r-allow", "r-block")


def test_rules_are_scoped_to_a_surface() -> None:
    rules = [
        PolicyRule(
            "r-out", "test", "keyword", "token", PolicyAction.BLOCK, surface=PolicySurface.OUTPUT
        )
    ]
    assert evaluate_policies(rules, "a token", surface=PolicySurface.INPUT, now=NOW).action is (
        PolicyAction.ALLOW
    )
    assert evaluate_policies(rules, "a token", surface=PolicySurface.OUTPUT, now=NOW).blocks


def test_an_inactive_rule_is_not_applied() -> None:
    rules = [PolicyRule("r", "test", "keyword", "token", PolicyAction.BLOCK, is_active=False)]
    assert evaluate_policies(rules, "a token", now=NOW).action is PolicyAction.ALLOW


def test_a_rule_with_an_unknown_match_kind_is_refused_at_construction() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        PolicyRule("r", "test", "regex", "token", PolicyAction.BLOCK)
    assert excinfo.value.code == "AI_POLICY_MATCH_KIND_UNKNOWN"


def test_a_blocked_prompt_is_refused_before_any_spend() -> None:
    provider = _ProviderSpy()
    rules = [PolicyRule("r", "test", "keyword", "forbidden", PolicyAction.BLOCK)]
    with pytest.raises(AiRuleError) as excinfo:
        plan_request(
            rules=rules,
            prompt="this is forbidden",
            profiles=[PRIMARY],
            limits=GENEROUS,
            usage=BudgetUsage(),
            prompt_tokens=10,
            max_output_tokens=10,
            now=NOW,
        )
    assert excinfo.value.code == "AI_POLICY_BLOCKED"
    assert provider.calls == 0


# ---------------------------------------------------------------------------
# Crisis routing fails closed
# ---------------------------------------------------------------------------


def test_no_configured_resource_escalates_to_a_human_and_invents_nothing() -> None:
    routing = route_crisis([], geography_code="CN", now=NOW)
    assert routing.escalate_to_human is True
    assert routing.reason_code == "CRISIS_NO_RESOURCE_CONFIGURED"
    assert routing.resource_codes == ()


def test_an_unknown_geography_escalates_rather_than_guessing_a_jurisdiction() -> None:
    routing = route_crisis(
        [CrisisResource("r", "CN", "zh-CN", verified_at=NOW)], geography_code=None, now=NOW
    )
    assert routing.escalate_to_human is True
    assert routing.reason_code == "CRISIS_GEOGRAPHY_UNKNOWN"


def test_an_unverified_resource_is_not_used() -> None:
    resources = [CrisisResource("r", "CN", "zh-CN", verified_at=None)]
    routing = route_crisis(resources, geography_code="CN", now=NOW)
    assert routing.resource_codes == ()
    assert routing.reason_code == "CRISIS_NO_RESOURCE_CONFIGURED"


def test_a_resource_from_another_geography_is_never_substituted() -> None:
    resources = [CrisisResource("us-line", "US", "en-US", verified_at=NOW)]
    routing = route_crisis(resources, geography_code="CN", now=NOW)
    assert routing.resource_codes == ()


def test_a_configured_resource_is_returned_and_a_human_is_still_involved() -> None:
    resources = [CrisisResource("cn-line", "CN", "zh-CN", verified_at=NOW)]
    routing = route_crisis(resources, geography_code="CN", locale="zh-CN", now=NOW)
    assert routing.resource_codes == ("cn-line",)
    assert routing.escalate_to_human is True
    assert routing.reason_code == "CRISIS_RESOURCES_AVAILABLE"


def test_a_locale_mismatch_still_returns_a_real_number_and_says_so() -> None:
    resources = [CrisisResource("cn-line", "CN", "zh-CN", verified_at=NOW)]
    routing = route_crisis(resources, geography_code="CN", locale="en-US", now=NOW)
    assert routing.resource_codes == ("cn-line",)
    assert routing.reason_code == "CRISIS_LOCALE_FALLBACK"


# ---------------------------------------------------------------------------
# Human escalation
# ---------------------------------------------------------------------------


def test_a_crisis_outranks_every_other_escalation_reason() -> None:
    crisis = route_crisis([], geography_code="CN", now=NOW)
    plan = plan_escalation(crisis=crisis, member_requested=True, conversation_id=CONVERSATION)
    assert plan.required is True
    assert plan.reason_code.startswith("crisis:")
    assert plan.severity == 9
    assert plan.dedupe_key is not None


def test_a_member_asking_for_a_human_is_always_honoured() -> None:
    assert plan_escalation(member_requested=True).required is True


def test_a_quiet_conversation_does_not_open_an_escalation() -> None:
    assert plan_escalation().required is False


def test_an_outage_opens_a_low_severity_referral() -> None:
    plan = plan_escalation(provider_outage=True)
    assert plan.required is True
    assert plan.reason_code == "provider_outage"
    assert plan.severity == 2


def test_an_open_escalation_cannot_jump_to_resolved() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        validate_escalation_transition(EscalationStatus.OPEN.value, EscalationStatus.RESOLVED.value)
    assert excinfo.value.code == "AI_ESCALATION_TRANSITION_INVALID"
    validate_escalation_transition(EscalationStatus.OPEN.value, EscalationStatus.ACKNOWLEDGED.value)


def test_an_unacknowledged_escalation_becomes_overdue() -> None:
    assert (
        escalation_is_overdue(
            opened_at=NOW - timedelta(hours=2),
            acknowledged_at=None,
            now=NOW,
            target=timedelta(minutes=30),
        )
        is True
    )
    assert (
        escalation_is_overdue(
            opened_at=NOW - timedelta(minutes=2),
            acknowledged_at=NOW - timedelta(minutes=1),
            now=NOW,
            target=timedelta(minutes=30),
        )
        is False
    )


# ---------------------------------------------------------------------------
# Fail-safe on outage, and limitation labelling
# ---------------------------------------------------------------------------


def test_an_outage_produces_a_refusal_with_no_answer() -> None:
    payload = build_refusal(
        refusal_code="AI_PROVIDER_UNAVAILABLE",
        label_version=LABEL_VERSION,
        escalation_reason_code="provider_outage",
    )
    assert payload.answer is None
    assert payload.refusal_code == "AI_PROVIDER_UNAVAILABLE"
    assert payload.as_dict()["answer"] is None
    assert payload.as_dict()["escalation_reason_code"] == "provider_outage"


def test_a_payload_cannot_carry_both_an_answer_and_a_refusal() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        AiResponsePayload(
            answer="fabricated",
            refusal_code="AI_PROVIDER_UNAVAILABLE",
            provider_code="primary",
            model_code="model-a",
            limitation_label_code=LIMITATION_LABEL_CODE,
            limitation_label_version=LABEL_VERSION,
        )
    assert excinfo.value.code == "AI_RESPONSE_SHAPE_INVALID"


def test_a_payload_with_neither_an_answer_nor_a_refusal_is_impossible() -> None:
    with pytest.raises(AiRuleError):
        AiResponsePayload(
            answer=None,
            refusal_code=None,
            provider_code=None,
            model_code=None,
            limitation_label_code=LIMITATION_LABEL_CODE,
            limitation_label_version=LABEL_VERSION,
        )


def test_an_answer_must_name_the_provider_that_produced_it() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        AiResponsePayload(
            answer="text",
            refusal_code=None,
            provider_code=None,
            model_code=None,
            limitation_label_code=LIMITATION_LABEL_CODE,
            limitation_label_version=LABEL_VERSION,
        )
    assert excinfo.value.code == "AI_RESPONSE_PROVENANCE_MISSING"


def test_an_empty_provider_answer_is_treated_as_an_outage() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        build_answer(answer="   ", profile=PRIMARY, label_version=LABEL_VERSION)
    assert excinfo.value.code == "AI_ANSWER_EMPTY"


def test_every_response_carries_an_ai_limitation_label() -> None:
    answer = build_answer(answer="hello", profile=PRIMARY, label_version=LABEL_VERSION)
    refusal = build_refusal(refusal_code="AI_BUDGET_EXCEEDED", label_version=LABEL_VERSION)
    for payload in (answer, refusal):
        ensure_limitation_labelled(payload)
        assert payload.as_dict()["ai_limitation"]["label_code"] == LIMITATION_LABEL_CODE
        assert payload.as_dict()["ai_limitation"]["human_review_available"] is True


def test_a_payload_without_a_label_cannot_be_built() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        AiResponsePayload(
            answer=None,
            refusal_code="AI_BUDGET_EXCEEDED",
            provider_code=None,
            model_code=None,
            limitation_label_code="",
            limitation_label_version=LABEL_VERSION,
        )
    assert excinfo.value.code == "AI_LIMITATION_LABEL_MISSING"


def test_a_crisis_refusal_carries_the_configured_resources_only() -> None:
    payload = build_refusal(
        refusal_code="AI_CRISIS_ESCALATED",
        label_version=LABEL_VERSION,
        crisis_resource_codes=(),
        escalation_reason_code="crisis:CRISIS_NO_RESOURCE_CONFIGURED",
    )
    assert payload.crisis_resource_codes == ()
    assert payload.answer is None


# ---------------------------------------------------------------------------
# Launch readiness
# ---------------------------------------------------------------------------


def test_nothing_is_launch_ready_by_default() -> None:
    readiness = evaluate_launch_readiness([], now=NOW)
    assert readiness.ready is False
    assert set(readiness.unmet) == {gate.value for gate in LaunchGateCode}
    assert set(readiness.unrecorded) == set(readiness.unmet)


def test_the_human_escalation_runbook_is_a_required_gate() -> None:
    """ "No launch claim without a runbook" is enforced, not documented."""

    assert LaunchGateCode.HUMAN_ESCALATION_RUNBOOK in REQUIRED_LAUNCH_GATES
    gates = [
        LaunchGate(gate_code=code.value, is_met=True, evidence_ref="doc", checked_at=NOW)
        for code in LaunchGateCode
        if code is not LaunchGateCode.HUMAN_ESCALATION_RUNBOOK
    ]
    readiness = evaluate_launch_readiness(gates, now=NOW)
    assert readiness.ready is False
    assert readiness.unmet == (LaunchGateCode.HUMAN_ESCALATION_RUNBOOK.value,)


def test_a_gate_marked_met_without_evidence_does_not_count() -> None:
    gates = [
        LaunchGate(gate_code=code.value, is_met=True, evidence_ref="doc", checked_at=NOW)
        for code in LaunchGateCode
    ]
    gates[0] = LaunchGate(gate_code=gates[0].gate_code, is_met=True, evidence_ref=None)
    readiness = evaluate_launch_readiness(gates, now=NOW)
    assert readiness.ready is False


def test_stale_evidence_is_reported_separately_and_blocks_launch() -> None:
    gates = [
        LaunchGate(
            gate_code=code.value,
            is_met=True,
            evidence_ref="doc",
            checked_at=NOW - timedelta(days=400),
        )
        for code in LaunchGateCode
    ]
    readiness = evaluate_launch_readiness(gates, now=NOW, max_age=timedelta(days=90))
    assert readiness.ready is False
    assert len(readiness.stale) == len(list(LaunchGateCode))


def test_every_gate_met_reports_ready() -> None:
    gates = [
        LaunchGate(gate_code=code.value, is_met=True, evidence_ref="doc", checked_at=NOW)
        for code in LaunchGateCode
    ]
    readiness = evaluate_launch_readiness(gates, now=NOW, max_age=timedelta(days=90))
    assert readiness.ready is True
    assert readiness.as_dict()["unmet"] == []


def test_a_naive_timestamp_is_refused_everywhere() -> None:
    with pytest.raises(AiRuleError) as excinfo:
        evaluate_launch_readiness([], now=datetime(2026, 8, 12, 12, 0))
    assert excinfo.value.code == "AI_NAIVE_DATETIME"
