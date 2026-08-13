"""Pure AI safety, budget and readiness rules (B19 part 1 / AI-001).

The four things this file exists to hold, none of which can be enforced by a
provider SDK:

1. A budget is checked **before** a provider is selected, let alone called. The
   ordering is structural (:func:`plan_request` refuses first and picks a
   provider second), not a convention, so a request over budget cannot be
   billed and then rejected.
2. A provider outage produces an explicit refusal payload with no ``answer``
   field at all. There is no code path that emits a fabricated answer, because
   the only way to build a response is through a constructor that requires
   either provider output or a refusal reason.
3. Crisis routing fails **closed**. When no crisis resource is configured for a
   member's geography, the decision is "escalate to a human", never a guessed
   hotline. The platform ships no hotline numbers and no content-policy copy:
   those are operator-filled tables (DEC-003 discipline).
4. Nothing is "launch ready" by default. :func:`evaluate_launch_readiness`
   treats an unrecorded gate as unmet, so silence is never mistaken for a pass.

No database, settings, network or clock access: ``now`` is always an argument.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID


class AiRuleError(Exception):
    """Raised when a caller violates an AI safety or budget rule."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


def _require_aware(**values: datetime | None) -> None:
    for label, value in values.items():
        if value is not None and value.tzinfo is None:
            raise AiRuleError("AI_NAIVE_DATETIME", f"{label} must be timezone-aware.")


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


class ProviderHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    #: Circuit breaker open: the provider is not called at all.
    OUT_OF_SERVICE = "out_of_service"


@dataclass(frozen=True)
class ProviderProfile:
    """One callable model behind one provider.

    Costs are integer tenths of a cent per 1000 tokens so the whole budget
    arithmetic is exact. Floating-point money in a spend limit is how a limit
    becomes advisory.
    """

    provider_code: str
    model_code: str
    input_cost_per_1k_millicents: int
    output_cost_per_1k_millicents: int
    max_context_tokens: int
    max_output_tokens: int
    priority: int = 100
    is_enabled: bool = True
    #: Capabilities an operator has certified this model for, e.g. "chat".
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.input_cost_per_1k_millicents < 0 or self.output_cost_per_1k_millicents < 0:
            raise AiRuleError("AI_PROVIDER_COST_INVALID", "Provider costs cannot be negative.")
        if self.max_context_tokens < 1 or self.max_output_tokens < 1:
            raise AiRuleError(
                "AI_PROVIDER_LIMIT_INVALID", "Provider token limits must be positive."
            )


@dataclass(frozen=True)
class ProviderState:
    provider_code: str
    health: ProviderHealth = ProviderHealth.HEALTHY
    consecutive_failures: int = 0
    circuit_opened_at: datetime | None = None


def circuit_state(
    state: ProviderState,
    *,
    now: datetime,
    failure_threshold: int,
    open_for: timedelta,
) -> ProviderHealth:
    """Derive the effective health of a provider from its failure record.

    A circuit that has been open longer than ``open_for`` becomes ``DEGRADED``
    (half-open): one request is allowed through to find out whether the
    provider recovered. It never jumps straight back to healthy on a timer.
    """

    _require_aware(now=now, circuit_opened_at=state.circuit_opened_at)
    if state.health is ProviderHealth.OUT_OF_SERVICE:
        if state.circuit_opened_at is not None and now - state.circuit_opened_at >= open_for:
            return ProviderHealth.DEGRADED
        return ProviderHealth.OUT_OF_SERVICE
    if state.consecutive_failures >= failure_threshold:
        return ProviderHealth.OUT_OF_SERVICE
    return state.health


def select_provider(
    profiles: Sequence[ProviderProfile],
    *,
    health: Mapping[str, ProviderHealth] | None = None,
    capability: str | None = None,
    required_output_tokens: int = 1,
) -> ProviderProfile:
    """Pick the highest-priority usable provider, or fail loudly.

    "Fail loudly" is the point. There is no fallback to a canned answer and no
    silent downgrade to a smaller model that was not certified for the
    capability - a caller that cannot get a provider gets an exception and, one
    level up, a refusal payload (:func:`build_refusal`).
    """

    states = dict(health or {})
    usable = [
        profile
        for profile in profiles
        if profile.is_enabled
        and states.get(profile.provider_code, ProviderHealth.HEALTHY)
        is not ProviderHealth.OUT_OF_SERVICE
        and (capability is None or capability in profile.capabilities)
        and profile.max_output_tokens >= required_output_tokens
    ]
    if not usable:
        raise AiRuleError(
            "AI_PROVIDER_UNAVAILABLE",
            "No enabled and healthy AI provider is available for this request.",
            details={"capability": capability, "candidates": len(profiles)},
        )
    return sorted(usable, key=lambda profile: (profile.priority, profile.provider_code))[0]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class BudgetScope(StrEnum):
    USER_DAILY = "user_daily"
    CONVERSATION = "conversation"
    GLOBAL_MONTHLY = "global_monthly"


#: All three scopes must be configured before any request is allowed when
#: ``require_all_scopes`` is on. An unconfigured limit is not "unlimited".
REQUIRED_BUDGET_SCOPES: frozenset[BudgetScope] = frozenset(BudgetScope)


@dataclass(frozen=True)
class BudgetLimits:
    """Configured ceilings. ``None`` means *not configured*, not *unlimited*."""

    user_daily_tokens: int | None = None
    conversation_tokens: int | None = None
    global_monthly_millicents: int | None = None

    def limit_for(self, scope: BudgetScope) -> int | None:
        if scope is BudgetScope.USER_DAILY:
            return self.user_daily_tokens
        if scope is BudgetScope.CONVERSATION:
            return self.conversation_tokens
        return self.global_monthly_millicents

    def unconfigured_scopes(self) -> tuple[BudgetScope, ...]:
        return tuple(
            scope for scope in sorted(BudgetScope, key=str) if self.limit_for(scope) is None
        )


@dataclass(frozen=True)
class BudgetUsage:
    """Usage already recorded, in the same units as :class:`BudgetLimits`."""

    user_daily_tokens: int = 0
    conversation_tokens: int = 0
    global_monthly_millicents: int = 0

    def used_for(self, scope: BudgetScope) -> int:
        if scope is BudgetScope.USER_DAILY:
            return self.user_daily_tokens
        if scope is BudgetScope.CONVERSATION:
            return self.conversation_tokens
        return self.global_monthly_millicents


@dataclass(frozen=True)
class CostEstimate:
    prompt_tokens: int
    max_output_tokens: int
    millicents: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.max_output_tokens

    def cost_for(self, scope: BudgetScope) -> int:
        return self.millicents if scope is BudgetScope.GLOBAL_MONTHLY else self.total_tokens


def estimate_cost(
    profile: ProviderProfile, *, prompt_tokens: int, max_output_tokens: int
) -> CostEstimate:
    """Price a request at its **worst case** before it is sent.

    ``max_output_tokens`` rather than an expected value: a budget that is
    checked against an optimistic estimate is a budget that is exceeded by
    every verbose answer. Reconciliation with actual usage happens afterwards
    through :func:`reconcile_usage`.
    """

    if prompt_tokens < 0 or max_output_tokens < 0:
        raise AiRuleError("AI_TOKEN_COUNT_INVALID", "Token counts cannot be negative.")
    if prompt_tokens + max_output_tokens > profile.max_context_tokens:
        raise AiRuleError(
            "AI_CONTEXT_TOO_LARGE",
            "The request exceeds the model's context window.",
            details={
                "prompt_tokens": prompt_tokens,
                "max_output_tokens": max_output_tokens,
                "max_context_tokens": profile.max_context_tokens,
            },
        )
    millicents = (
        prompt_tokens * profile.input_cost_per_1k_millicents
        + max_output_tokens * profile.output_cost_per_1k_millicents
    ) // 1000
    return CostEstimate(
        prompt_tokens=prompt_tokens, max_output_tokens=max_output_tokens, millicents=millicents
    )


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    breached_scope: BudgetScope | None = None
    remaining: Mapping[str, int] = field(default_factory=dict)
    reason_code: str | None = None


def check_budget(
    limits: BudgetLimits,
    usage: BudgetUsage,
    estimate: CostEstimate,
    *,
    require_all_scopes: bool = True,
) -> BudgetDecision:
    """Decide whether a request fits, in every scope, before it is sent.

    Scopes are evaluated in a fixed order (conversation, user, global) so the
    reported breach is deterministic and support can answer "which limit did I
    hit" the same way twice.
    """

    if require_all_scopes:
        missing = limits.unconfigured_scopes()
        if missing:
            return BudgetDecision(
                allowed=False,
                breached_scope=missing[0],
                reason_code="AI_BUDGET_NOT_CONFIGURED",
            )
    remaining: dict[str, int] = {}
    breach: BudgetScope | None = None
    for scope in (BudgetScope.CONVERSATION, BudgetScope.USER_DAILY, BudgetScope.GLOBAL_MONTHLY):
        limit = limits.limit_for(scope)
        if limit is None:
            continue
        left = limit - usage.used_for(scope)
        remaining[scope.value] = max(0, left)
        if breach is None and estimate.cost_for(scope) > left:
            breach = scope
    if breach is not None:
        return BudgetDecision(
            allowed=False,
            breached_scope=breach,
            remaining=remaining,
            reason_code="AI_BUDGET_EXCEEDED",
        )
    return BudgetDecision(allowed=True, remaining=remaining)


def ensure_within_budget(decision: BudgetDecision) -> None:
    if decision.allowed:
        return
    raise AiRuleError(
        decision.reason_code or "AI_BUDGET_EXCEEDED",
        "This request would exceed a configured AI budget and was refused before "
        "any provider was called.",
        details={
            "scope": decision.breached_scope.value if decision.breached_scope else None,
            "remaining": dict(decision.remaining),
        },
    )


def reconcile_usage(estimate: CostEstimate, *, actual_output_tokens: int) -> CostEstimate:
    """Replace the worst-case output count with what actually came back."""

    if actual_output_tokens < 0:
        raise AiRuleError("AI_TOKEN_COUNT_INVALID", "Token counts cannot be negative.")
    if estimate.max_output_tokens == 0:
        return CostEstimate(estimate.prompt_tokens, 0, estimate.millicents)
    output_share = estimate.millicents * actual_output_tokens // max(1, estimate.max_output_tokens)
    return CostEstimate(
        prompt_tokens=estimate.prompt_tokens,
        max_output_tokens=actual_output_tokens,
        millicents=min(estimate.millicents, output_share) if actual_output_tokens else 0,
    )


def usage_idempotency_key(conversation_id: UUID, request_id: str) -> str:
    """One usage row per request, however many times the write is retried."""

    return f"ai-usage:{conversation_id}:{request_id}"


# ---------------------------------------------------------------------------
# Content policy filtering with audit
# ---------------------------------------------------------------------------


class PolicyAction(StrEnum):
    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"
    ESCALATE = "escalate"


#: Severity ordering. The most severe matched action wins, so a rule set can
#: never be made permissive by adding an ``allow`` rule after a ``block`` one.
_ACTION_SEVERITY: Mapping[PolicyAction, int] = {
    PolicyAction.ALLOW: 0,
    PolicyAction.FLAG: 1,
    PolicyAction.BLOCK: 2,
    PolicyAction.ESCALATE: 3,
}


class PolicySurface(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True)
class PolicyRule:
    """One operator-authored rule.

    The platform ships **no** rules: :data:`DEFAULT_POLICY_RULES` is empty on
    purpose. Content-policy wording is a legal and clinical decision, not a
    developer's guess, so it is filled in by an operator through the admin API.
    """

    rule_code: str
    category: str
    #: ``keyword`` = case-insensitive substring; ``exact`` = whole trimmed text.
    match_kind: str
    pattern: str
    action: PolicyAction
    severity: int = 1
    surface: PolicySurface = PolicySurface.INPUT
    locale: str | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if self.match_kind not in ("keyword", "exact"):
            raise AiRuleError(
                "AI_POLICY_MATCH_KIND_UNKNOWN",
                "A policy rule must match by keyword or exact text.",
                details={"rule_code": self.rule_code, "match_kind": self.match_kind},
            )
        if not self.pattern.strip():
            raise AiRuleError(
                "AI_POLICY_PATTERN_EMPTY",
                "A policy rule needs a non-empty pattern.",
                details={"rule_code": self.rule_code},
            )


#: Deliberately empty. See :class:`PolicyRule`.
DEFAULT_POLICY_RULES: tuple[PolicyRule, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    matched_rule_codes: tuple[str, ...]
    highest_severity: int
    surface: PolicySurface
    #: Always populated, including for a clean pass. An audit trail with holes
    #: in it cannot answer "was this message ever screened".
    audit: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.action in (PolicyAction.BLOCK, PolicyAction.ESCALATE)


def evaluate_policies(
    rules: Sequence[PolicyRule],
    text: str,
    *,
    surface: PolicySurface = PolicySurface.INPUT,
    locale: str | None = None,
    now: datetime,
    evaluated_rule_set_version: str = "unversioned",
) -> PolicyDecision:
    """Screen one piece of text and always produce an audit record."""

    _require_aware(now=now)
    haystack = text.lower()
    trimmed = text.strip().lower()
    matched: list[PolicyRule] = []
    considered = 0
    for rule in rules:
        if not rule.is_active or rule.surface is not surface:
            continue
        if rule.locale is not None and locale is not None and rule.locale != locale:
            continue
        considered += 1
        needle = rule.pattern.strip().lower()
        hit = needle in haystack if rule.match_kind == "keyword" else trimmed == needle
        if hit:
            matched.append(rule)
    action = PolicyAction.ALLOW
    for rule in matched:
        if _ACTION_SEVERITY[rule.action] > _ACTION_SEVERITY[action]:
            action = rule.action
    return PolicyDecision(
        action=action,
        matched_rule_codes=tuple(sorted(rule.rule_code for rule in matched)),
        highest_severity=max((rule.severity for rule in matched), default=0),
        surface=surface,
        audit={
            "evaluated_at": now.isoformat(),
            "surface": surface.value,
            "locale": locale,
            "rules_considered": considered,
            "rules_matched": len(matched),
            "rule_set_version": evaluated_rule_set_version,
            "action": action.value,
        },
    )


# ---------------------------------------------------------------------------
# Crisis routing (fails closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrisisResource:
    """An operator-verified crisis resource for one geography.

    The platform ships none of these. A wrong hotline number in a crisis is
    worse than no number, so the code refuses to invent one and escalates to a
    human instead.
    """

    resource_code: str
    geography_code: str
    locale: str
    is_active: bool = True
    verified_at: datetime | None = None

    @property
    def is_usable(self) -> bool:
        return self.is_active and self.verified_at is not None


@dataclass(frozen=True)
class CrisisRouting:
    resource_codes: tuple[str, ...]
    escalate_to_human: bool
    reason_code: str
    geography_code: str | None


def route_crisis(
    resources: Sequence[CrisisResource],
    *,
    geography_code: str | None,
    locale: str | None = None,
    now: datetime,
) -> CrisisRouting:
    """Select crisis resources for a member, failing closed when there are none.

    Three fail-closed cases, all of which end in a human:

    * the member's geography is unknown - we cannot guess a jurisdiction
    * no resource is configured for that geography
    * resources exist but none is both active and operator-verified

    A locale mismatch does *not* fail closed: an active verified resource in
    the wrong language is still a real phone number, so it is returned and the
    reason code records the mismatch.
    """

    _require_aware(now=now)
    if not geography_code:
        return CrisisRouting(
            resource_codes=(),
            escalate_to_human=True,
            reason_code="CRISIS_GEOGRAPHY_UNKNOWN",
            geography_code=None,
        )
    in_geography = [
        resource
        for resource in resources
        if resource.geography_code == geography_code and resource.is_usable
    ]
    if not in_geography:
        return CrisisRouting(
            resource_codes=(),
            escalate_to_human=True,
            reason_code="CRISIS_NO_RESOURCE_CONFIGURED",
            geography_code=geography_code,
        )
    localized = [
        resource for resource in in_geography if locale is None or resource.locale == locale
    ]
    chosen = localized or in_geography
    return CrisisRouting(
        resource_codes=tuple(sorted(resource.resource_code for resource in chosen)),
        # A crisis always reaches a human as well; the resources are what the
        # member gets in the meantime, not a substitute for the escalation.
        escalate_to_human=True,
        reason_code="CRISIS_RESOURCES_AVAILABLE" if localized else "CRISIS_LOCALE_FALLBACK",
        geography_code=geography_code,
    )


# ---------------------------------------------------------------------------
# Human escalation
# ---------------------------------------------------------------------------


class EscalationStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


_ESCALATION_TRANSITIONS: Mapping[EscalationStatus, frozenset[EscalationStatus]] = {
    EscalationStatus.OPEN: frozenset({EscalationStatus.ACKNOWLEDGED, EscalationStatus.CANCELLED}),
    EscalationStatus.ACKNOWLEDGED: frozenset({EscalationStatus.RESOLVED}),
    EscalationStatus.RESOLVED: frozenset(),
    EscalationStatus.CANCELLED: frozenset(),
}


def validate_escalation_transition(current: str, target: str) -> None:
    """An open escalation cannot jump straight to resolved.

    Somebody has to acknowledge it first, which is what turns "a ticket was
    closed" into "a named human looked at it".
    """

    try:
        current_status = EscalationStatus(current)
        target_status = EscalationStatus(target)
    except ValueError as exc:
        raise AiRuleError("AI_ESCALATION_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _ESCALATION_TRANSITIONS[current_status]:
        raise AiRuleError(
            "AI_ESCALATION_TRANSITION_INVALID",
            f"Cannot move escalation from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


@dataclass(frozen=True)
class EscalationPlan:
    required: bool
    reason_code: str | None = None
    severity: int = 0
    dedupe_key: str | None = None


def plan_escalation(
    *,
    policy_decision: PolicyDecision | None = None,
    crisis: CrisisRouting | None = None,
    provider_outage: bool = False,
    member_requested: bool = False,
    conversation_id: UUID | None = None,
) -> EscalationPlan:
    """Decide whether a human must be involved, in priority order.

    A crisis outranks everything else. A member asking for a human is honoured
    unconditionally - it is never treated as a case the model can handle.
    """

    reason: str | None = None
    severity = 0
    if crisis is not None and crisis.escalate_to_human:
        reason, severity = f"crisis:{crisis.reason_code}", 9
    elif policy_decision is not None and policy_decision.action is PolicyAction.ESCALATE:
        reason, severity = "policy_escalate", max(5, policy_decision.highest_severity)
    elif member_requested:
        reason, severity = "member_requested", 4
    elif provider_outage:
        # An outage is not itself a safety event, but a member left without an
        # answer must have a way through, so a low-severity referral is opened.
        reason, severity = "provider_outage", 2
    if reason is None:
        return EscalationPlan(required=False)
    dedupe = f"ai-escalation:{conversation_id}:{reason}" if conversation_id else None
    return EscalationPlan(required=True, reason_code=reason, severity=severity, dedupe_key=dedupe)


def escalation_is_overdue(
    *, opened_at: datetime, acknowledged_at: datetime | None, now: datetime, target: timedelta
) -> bool:
    _require_aware(opened_at=opened_at, acknowledged_at=acknowledged_at, now=now)
    if acknowledged_at is not None:
        return acknowledged_at - opened_at > target
    return now - opened_at > target


# ---------------------------------------------------------------------------
# Response payloads: limitation labelling and fail-safe refusals
# ---------------------------------------------------------------------------

#: A label *code*, not copy. The frontend localizes it; the backend ships no
#: user-facing wording about what the model can and cannot do.
LIMITATION_LABEL_CODE = "ai_limitation_notice"


@dataclass(frozen=True)
class AiResponsePayload:
    """Either an answer or a refusal - never both, never neither.

    ``answer`` is ``None`` for every refusal, and the constructor enforces that
    a refusal carries a reason. That is the whole "no silently fabricated
    answer on outage" guarantee: there is no way to build a payload that looks
    like an answer without provider text behind it.
    """

    answer: str | None
    refusal_code: str | None
    provider_code: str | None
    model_code: str | None
    limitation_label_code: str
    limitation_label_version: str
    escalation_reason_code: str | None = None
    crisis_resource_codes: tuple[str, ...] = ()
    policy_action: PolicyAction = PolicyAction.ALLOW
    usage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.answer is None) == (self.refusal_code is None):
            raise AiRuleError(
                "AI_RESPONSE_SHAPE_INVALID",
                "A response payload carries exactly one of an answer or a refusal code.",
            )
        if self.answer is not None and not self.provider_code:
            raise AiRuleError(
                "AI_RESPONSE_PROVENANCE_MISSING",
                "An answer must name the provider that produced it.",
            )
        if not self.limitation_label_code:
            raise AiRuleError(
                "AI_LIMITATION_LABEL_MISSING",
                "Every AI response must carry an AI-limitation label.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "refusal_code": self.refusal_code,
            "provider_code": self.provider_code,
            "model_code": self.model_code,
            "ai_limitation": {
                "label_code": self.limitation_label_code,
                "label_version": self.limitation_label_version,
                "human_review_available": True,
            },
            "escalation_reason_code": self.escalation_reason_code,
            "crisis_resource_codes": list(self.crisis_resource_codes),
            "policy_action": self.policy_action.value,
            "usage": dict(self.usage),
        }


def build_answer(
    *,
    answer: str,
    profile: ProviderProfile,
    label_version: str,
    label_code: str = LIMITATION_LABEL_CODE,
    policy_action: PolicyAction = PolicyAction.ALLOW,
    escalation_reason_code: str | None = None,
    usage: Mapping[str, int] | None = None,
) -> AiResponsePayload:
    if not answer.strip():
        raise AiRuleError(
            "AI_ANSWER_EMPTY",
            "An empty provider answer is an outage, not an answer; refuse instead.",
        )
    return AiResponsePayload(
        answer=answer,
        refusal_code=None,
        provider_code=profile.provider_code,
        model_code=profile.model_code,
        limitation_label_code=label_code,
        limitation_label_version=label_version,
        policy_action=policy_action,
        escalation_reason_code=escalation_reason_code,
        usage=dict(usage or {}),
    )


def build_refusal(
    *,
    refusal_code: str,
    label_version: str,
    label_code: str = LIMITATION_LABEL_CODE,
    policy_action: PolicyAction = PolicyAction.ALLOW,
    escalation_reason_code: str | None = None,
    crisis_resource_codes: Sequence[str] = (),
    provider_code: str | None = None,
) -> AiResponsePayload:
    """The only way an AI turn can end without provider text."""

    if not refusal_code:
        raise AiRuleError("AI_REFUSAL_CODE_REQUIRED", "A refusal must carry a machine code.")
    return AiResponsePayload(
        answer=None,
        refusal_code=refusal_code,
        provider_code=provider_code,
        model_code=None,
        limitation_label_code=label_code,
        limitation_label_version=label_version,
        policy_action=policy_action,
        escalation_reason_code=escalation_reason_code,
        crisis_resource_codes=tuple(crisis_resource_codes),
    )


def ensure_limitation_labelled(payload: AiResponsePayload) -> None:
    if not payload.limitation_label_code or not payload.limitation_label_version:
        raise AiRuleError(
            "AI_LIMITATION_LABEL_MISSING",
            "Every AI response must carry an AI-limitation label and version.",
        )


# ---------------------------------------------------------------------------
# Request planning: budget first, provider second
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestPlan:
    profile: ProviderProfile
    estimate: CostEstimate
    budget: BudgetDecision
    policy: PolicyDecision
    escalation: EscalationPlan


def plan_request(
    *,
    rules: Sequence[PolicyRule],
    prompt: str,
    profiles: Sequence[ProviderProfile],
    health: Mapping[str, ProviderHealth] | None = None,
    limits: BudgetLimits,
    usage: BudgetUsage,
    prompt_tokens: int,
    max_output_tokens: int,
    now: datetime,
    locale: str | None = None,
    capability: str | None = None,
    require_all_scopes: bool = True,
    member_requested_human: bool = False,
    conversation_id: UUID | None = None,
) -> RequestPlan:
    """Everything that must happen before a provider is contacted.

    The order is the requirement, and it is enforced by control flow:

    1. screen the prompt against the policy rules (and audit the screening)
    2. refuse if the policy blocks, before any spend at all
    3. price the request against the *cheapest admissible* provider and check
       every budget scope - a refusal here costs nothing
    4. only then select the provider that will actually be called

    Because step 3 precedes step 4, an over-budget request is refused even when
    a provider is sitting there healthy and ready, and the caller receives
    ``AI_BUDGET_EXCEEDED`` rather than a provider error.
    """

    policy = evaluate_policies(rules, prompt, surface=PolicySurface.INPUT, locale=locale, now=now)
    escalation = plan_escalation(
        policy_decision=policy,
        member_requested=member_requested_human,
        conversation_id=conversation_id,
    )
    if policy.blocks:
        raise AiRuleError(
            "AI_POLICY_BLOCKED",
            "The request was blocked by content policy before any provider was called.",
            details={
                "action": policy.action.value,
                "matched_rule_codes": list(policy.matched_rule_codes),
            },
        )
    if not profiles:
        raise AiRuleError(
            "AI_PROVIDER_UNAVAILABLE", "No AI provider profile is configured.", details={}
        )
    # Pricing uses the cheapest configured profile that could serve the request,
    # so the budget check never depends on which provider happens to be healthy.
    pricing_profile = sorted(
        profiles,
        key=lambda item: (
            item.input_cost_per_1k_millicents + item.output_cost_per_1k_millicents,
            item.provider_code,
        ),
    )[0]
    estimate = estimate_cost(
        pricing_profile, prompt_tokens=prompt_tokens, max_output_tokens=max_output_tokens
    )
    budget = check_budget(limits, usage, estimate, require_all_scopes=require_all_scopes)
    ensure_within_budget(budget)
    profile = select_provider(
        profiles,
        health=health,
        capability=capability,
        required_output_tokens=max_output_tokens or 1,
    )
    return RequestPlan(
        profile=profile,
        estimate=estimate_cost(
            profile, prompt_tokens=prompt_tokens, max_output_tokens=max_output_tokens
        ),
        budget=budget,
        policy=policy,
        escalation=escalation,
    )


# ---------------------------------------------------------------------------
# Launch readiness
# ---------------------------------------------------------------------------


class LaunchGateCode(StrEnum):
    HUMAN_ESCALATION_RUNBOOK = "human_escalation_runbook"
    CRISIS_RESOURCES_CONFIGURED = "crisis_resources_configured"
    CONTENT_POLICY_CONFIGURED = "content_policy_configured"
    BUDGET_LIMITS_CONFIGURED = "budget_limits_configured"
    PROVIDER_FALLBACK_CONFIGURED = "provider_fallback_configured"
    LIMITATION_LABEL_CONFIGURED = "limitation_label_configured"


REQUIRED_LAUNCH_GATES: frozenset[LaunchGateCode] = frozenset(LaunchGateCode)


@dataclass(frozen=True)
class LaunchGate:
    gate_code: str
    is_met: bool
    evidence_ref: str | None = None
    checked_at: datetime | None = None


@dataclass(frozen=True)
class LaunchReadiness:
    ready: bool
    unmet: tuple[str, ...]
    #: Gates for which no record exists at all. Reported separately from
    #: recorded-and-failing so an operator can tell "we tried" from "nobody
    #: looked".
    unrecorded: tuple[str, ...]
    stale: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "unmet": list(self.unmet),
            "unrecorded": list(self.unrecorded),
            "stale": list(self.stale),
        }


def evaluate_launch_readiness(
    gates: Iterable[LaunchGate],
    *,
    now: datetime,
    required: Iterable[str] | None = None,
    max_age: timedelta | None = None,
) -> LaunchReadiness:
    """Report which launch gates are unmet. Absence is never a pass.

    "No AI launch claim without a human escalation runbook" is modelled here
    rather than written in a document: ``human_escalation_runbook`` is a
    required gate, so a deployment with no runbook row can never report ready,
    whatever else is green.

    A gate with evidence older than ``max_age`` is treated as unmet and listed
    in ``stale`` - a review from a year ago is not a current attestation.
    """

    _require_aware(now=now)
    required_codes = {str(code) for code in (required or [gate.value for gate in LaunchGateCode])}
    recorded = {gate.gate_code: gate for gate in gates}
    unmet: list[str] = []
    unrecorded: list[str] = []
    stale: list[str] = []
    for code in sorted(required_codes):
        gate = recorded.get(code)
        if gate is None:
            unrecorded.append(code)
            unmet.append(code)
            continue
        if not gate.is_met or not gate.evidence_ref:
            unmet.append(code)
            continue
        if max_age is not None:
            if gate.checked_at is None:
                stale.append(code)
                unmet.append(code)
                continue
            _require_aware(checked_at=gate.checked_at)
            if now - gate.checked_at > max_age:
                stale.append(code)
                unmet.append(code)
    return LaunchReadiness(
        ready=not unmet,
        unmet=tuple(sorted(set(unmet))),
        unrecorded=tuple(unrecorded),
        stale=tuple(stale),
    )
