"""Transactional AI hardening service (B19 part 1 / AI-001).

The order of operations in :func:`run_turn` is the requirement, so it is worth
stating plainly:

1. screen the prompt and write the policy audit row
2. read the budgets and the usage counters, then refuse if the request would
   exceed any of them - **before** a provider is chosen or contacted
3. reserve the estimated spend so two concurrent requests cannot both fit under
   the same remaining headroom
4. call the provider, and on any failure emit an explicit refusal, open a human
   referral and record the circuit-breaker failure
5. reconcile the reservation against actual usage

Nothing in this file can produce an answer that did not come from a provider:
the only response constructors are ``domain.build_answer`` (which requires
provider text and a profile) and ``domain.build_refusal`` (which produces no
answer at all).
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.ai_hardening.domain import (
    LIMITATION_LABEL_CODE,
    AiResponsePayload,
    AiRuleError,
    BudgetLimits,
    BudgetScope,
    BudgetUsage,
    CrisisResource,
    LaunchGate,
    PolicyAction,
    PolicyRule,
    PolicySurface,
    ProviderHealth,
    ProviderProfile,
    ProviderState,
    build_answer,
    build_refusal,
    circuit_state,
    ensure_limitation_labelled,
    evaluate_launch_readiness,
    plan_escalation,
    plan_request,
    reconcile_usage,
    route_crisis,
    usage_idempotency_key,
    validate_escalation_transition,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: AiRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def enabled() -> None:
    if not get_settings().ai_hardening_enabled:
        raise VavError("AI_HARDENING_DISABLED", "AI assistance is not enabled.", status_code=503)


async def _publish(
    session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'ai_conversation',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


class ProviderClient(Protocol):
    """The only surface an AI provider presents to this module.

    Injected rather than imported so the transport, the retries and the SDK all
    live outside the business rules - and so a test can supply a client that
    raises without touching a network.
    """

    async def complete(
        self, *, profile: ProviderProfile, prompt: str, max_output_tokens: int
    ) -> tuple[str, int]:
        """Return ``(answer_text, output_tokens)`` or raise."""


class _UnconfiguredProviderClient:
    """Stand-in used when no provider client has been registered.

    It raises, which routes the turn through the ordinary outage path: the
    member gets an explicit refusal and a human referral rather than an
    exception page. A misconfigured deployment behaves like a down provider,
    which is the safe interpretation.
    """

    async def complete(
        self, *, profile: ProviderProfile, prompt: str, max_output_tokens: int
    ) -> tuple[str, int]:
        raise RuntimeError("No AI provider client is registered for this deployment.")


_registered_client: ProviderClient | None = None


def register_provider_client(client: ProviderClient) -> None:
    """Wire the transport at application start-up."""

    global _registered_client
    _registered_client = client


def resolve_provider_client() -> ProviderClient:
    return _registered_client or _UnconfiguredProviderClient()


# ---------------------------------------------------------------------------
# Configuration loaders
# ---------------------------------------------------------------------------


async def _load_profiles(session: AsyncSession) -> list[ProviderProfile]:
    """Read the certified model catalogue.

    ``ai_model_profiles`` and ``ai_model_routes`` already exist; this module
    adds the cost and limit columns it needs through migration 0103 rather than
    keeping a second, divergent catalogue.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.provider_code,p.model_code,p.input_cost_per_1k_millicents,"
                    "p.output_cost_per_1k_millicents,p.max_context_tokens,p.max_output_tokens,"
                    "p.priority,p.is_enabled,p.capabilities "
                    "FROM ai_provider_profiles p WHERE p.is_enabled=true ORDER BY p.priority"
                )
            )
        )
        .mappings()
        .all()
    )
    return [
        ProviderProfile(
            provider_code=row["provider_code"],
            model_code=row["model_code"],
            input_cost_per_1k_millicents=int(row["input_cost_per_1k_millicents"]),
            output_cost_per_1k_millicents=int(row["output_cost_per_1k_millicents"]),
            max_context_tokens=int(row["max_context_tokens"]),
            max_output_tokens=int(row["max_output_tokens"]),
            priority=int(row["priority"]),
            is_enabled=bool(row["is_enabled"]),
            capabilities=frozenset(row["capabilities"] or []),
        )
        for row in rows
    ]


async def _load_health(session: AsyncSession, *, now: datetime) -> dict[str, ProviderHealth]:
    settings = get_settings()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT provider_code,status,consecutive_failures,circuit_opened_at "
                    "FROM ai_provider_health"
                )
            )
        )
        .mappings()
        .all()
    )
    health: dict[str, ProviderHealth] = {}
    for row in rows:
        state = ProviderState(
            provider_code=row["provider_code"],
            health=ProviderHealth(row["status"]),
            consecutive_failures=int(row["consecutive_failures"]),
            circuit_opened_at=row["circuit_opened_at"],
        )
        health[state.provider_code] = circuit_state(
            state,
            now=now,
            failure_threshold=settings.ai_provider_failure_threshold,
            open_for=timedelta(minutes=settings.ai_provider_circuit_open_minutes),
        )
    return health


async def _load_budget_limits(session: AsyncSession) -> BudgetLimits:
    """Read the three ceilings. An absent row means *not configured*.

    Not configured is not unlimited: ``domain.check_budget`` refuses when a
    required scope has no limit, so a fresh deployment cannot spend money
    before an operator has said how much.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT scope,limit_tokens,limit_millicents FROM ai_budget_policies "
                    "WHERE is_active=true"
                )
            )
        )
        .mappings()
        .all()
    )
    by_scope = {row["scope"]: row for row in rows}
    user_daily = by_scope.get(BudgetScope.USER_DAILY.value)
    conversation = by_scope.get(BudgetScope.CONVERSATION.value)
    monthly = by_scope.get(BudgetScope.GLOBAL_MONTHLY.value)
    return BudgetLimits(
        user_daily_tokens=int(user_daily["limit_tokens"])
        if user_daily and user_daily["limit_tokens"] is not None
        else None,
        conversation_tokens=int(conversation["limit_tokens"])
        if conversation and conversation["limit_tokens"] is not None
        else None,
        global_monthly_millicents=int(monthly["limit_millicents"])
        if monthly and monthly["limit_millicents"] is not None
        else None,
    )


async def _load_usage(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, now: datetime
) -> BudgetUsage:
    """Aggregate committed *and* reserved spend.

    Reservations are included so two requests in flight at the same time cannot
    both see the same headroom; the reservation is released or reconciled once
    the provider answers.
    """

    row = (
        (
            await session.execute(
                text(
                    "SELECT "
                    "COALESCE(SUM(total_tokens) FILTER (WHERE user_id=:user_id AND occurred_at >= date_trunc('day', :now)),0) AS user_daily_tokens,"
                    "COALESCE(SUM(total_tokens) FILTER (WHERE conversation_id=:conversation_id),0) AS conversation_tokens,"
                    "COALESCE(SUM(cost_millicents) FILTER (WHERE occurred_at >= date_trunc('month', :now)),0) AS global_monthly_millicents "
                    "FROM ai_usage_entries WHERE state IN ('reserved','committed')"
                ),
                {"user_id": str(user_id), "conversation_id": str(conversation_id), "now": now},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return BudgetUsage()
    return BudgetUsage(
        user_daily_tokens=int(row["user_daily_tokens"]),
        conversation_tokens=int(row["conversation_tokens"]),
        global_monthly_millicents=int(row["global_monthly_millicents"]),
    )


async def _load_policy_rules(session: AsyncSession) -> list[PolicyRule]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT rule_code,category,match_kind,pattern,action,severity,surface,locale,is_active "
                    "FROM ai_content_policy_rules WHERE is_active=true"
                )
            )
        )
        .mappings()
        .all()
    )
    return [
        PolicyRule(
            rule_code=row["rule_code"],
            category=row["category"],
            match_kind=row["match_kind"],
            pattern=row["pattern"],
            action=PolicyAction(row["action"]),
            severity=int(row["severity"]),
            surface=PolicySurface(row["surface"]),
            locale=row["locale"],
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]


async def _load_crisis_resources(
    session: AsyncSession, *, geography_code: str | None
) -> list[CrisisResource]:
    if not geography_code:
        return []
    rows = (
        (
            await session.execute(
                text(
                    "SELECT resource_code,geography_code,locale,is_active,verified_at "
                    "FROM ai_crisis_resources WHERE geography_code=:geography_code"
                ),
                {"geography_code": geography_code},
            )
        )
        .mappings()
        .all()
    )
    return [
        CrisisResource(
            resource_code=row["resource_code"],
            geography_code=row["geography_code"],
            locale=row["locale"],
            is_active=bool(row["is_active"]),
            verified_at=row["verified_at"],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Audit writers
# ---------------------------------------------------------------------------


async def _record_policy_decision(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    decision: Any,
) -> None:
    await session.execute(
        text(
            "INSERT INTO ai_policy_decisions "
            "(user_id,conversation_id,surface,action,matched_rule_codes,highest_severity,audit) "
            "VALUES (:user_id,:conversation_id,:surface,:action,CAST(:codes AS jsonb),:severity,CAST(:audit AS jsonb))"
        ),
        {
            "user_id": str(user_id),
            "conversation_id": str(conversation_id),
            "surface": decision.surface.value,
            "action": decision.action.value,
            "codes": _json(list(decision.matched_rule_codes)),
            "severity": decision.highest_severity,
            "audit": _json(dict(decision.audit)),
        },
    )


async def _reserve_usage(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    request_id: str,
    profile: ProviderProfile,
    estimate: Any,
) -> UUID:
    """Write the worst-case spend before the call, keyed for idempotency."""

    entry_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO ai_usage_entries "
                "(id,user_id,conversation_id,provider_code,model_code,prompt_tokens,completion_tokens,"
                "total_tokens,cost_millicents,state,idempotency_key,limitation_label_code,limitation_label_version) "
                "VALUES (:id,:user_id,:conversation_id,:provider,:model,:prompt_tokens,:completion_tokens,"
                ":total_tokens,:cost,'reserved',:key,:label_code,:label_version)"
            ),
            {
                "id": str(entry_id),
                "user_id": str(user_id),
                "conversation_id": str(conversation_id),
                "provider": profile.provider_code,
                "model": profile.model_code,
                "prompt_tokens": estimate.prompt_tokens,
                "completion_tokens": estimate.max_output_tokens,
                "total_tokens": estimate.total_tokens,
                "cost": estimate.millicents,
                "key": usage_idempotency_key(conversation_id, request_id),
                "label_code": LIMITATION_LABEL_CODE,
                "label_version": get_settings().ai_limitation_label_version,
            },
        )
    except IntegrityError as exc:
        # A retry of the same request: the reservation already exists and the
        # member is not charged twice.
        raise VavError(
            "AI_REQUEST_ALREADY_IN_FLIGHT",
            "This request has already been submitted.",
            status_code=409,
        ) from exc
    return entry_id


async def _record_refusal(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    request_id: str,
    refusal_code: str,
) -> None:
    """A refusal is a usage row with zero spend, so refusals are countable."""

    await session.execute(
        text(
            "INSERT INTO ai_usage_entries "
            "(user_id,conversation_id,prompt_tokens,completion_tokens,total_tokens,cost_millicents,"
            "state,refusal_code,idempotency_key,limitation_label_code,limitation_label_version) "
            "VALUES (:user_id,:conversation_id,0,0,0,0,'refused',:refusal_code,:key,:label_code,:label_version) "
            "ON CONFLICT (idempotency_key) DO NOTHING"
        ),
        {
            "user_id": str(user_id),
            "conversation_id": str(conversation_id),
            "refusal_code": refusal_code,
            "key": f"{usage_idempotency_key(conversation_id, request_id)}:refused",
            "label_code": LIMITATION_LABEL_CODE,
            "label_version": get_settings().ai_limitation_label_version,
        },
    )


async def _record_provider_result(
    session: AsyncSession, *, provider_code: str, succeeded: bool, now: datetime
) -> None:
    await session.execute(
        text(
            "INSERT INTO ai_provider_health (provider_code,status,consecutive_failures,last_success_at,last_failure_at,circuit_opened_at) "
            "VALUES (:provider,:status,:failures,:success_at,:failure_at,:opened_at) "
            "ON CONFLICT (provider_code) DO UPDATE SET "
            "consecutive_failures=CASE WHEN :succeeded THEN 0 ELSE ai_provider_health.consecutive_failures+1 END,"
            "status=CASE WHEN :succeeded THEN 'healthy' "
            "  WHEN ai_provider_health.consecutive_failures+1 >= :threshold THEN 'out_of_service' ELSE 'degraded' END,"
            "last_success_at=COALESCE(:success_at, ai_provider_health.last_success_at),"
            "last_failure_at=COALESCE(:failure_at, ai_provider_health.last_failure_at),"
            "circuit_opened_at=CASE WHEN :succeeded THEN NULL "
            "  WHEN ai_provider_health.consecutive_failures+1 >= :threshold THEN COALESCE(ai_provider_health.circuit_opened_at, :failure_at) "
            "  ELSE ai_provider_health.circuit_opened_at END,"
            "updated_at=now()"
        ),
        {
            "provider": provider_code,
            "status": "healthy" if succeeded else "degraded",
            "failures": 0 if succeeded else 1,
            "success_at": now if succeeded else None,
            "failure_at": None if succeeded else now,
            "opened_at": None,
            "succeeded": succeeded,
            "threshold": get_settings().ai_provider_failure_threshold,
        },
    )


async def _open_escalation(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    plan: Any,
    geography_code: str | None,
) -> UUID | None:
    """Open a human referral, de-duplicated per conversation and reason.

    The runbook is attached at creation time when one is configured. When none
    is, the escalation is still opened - the member's referral does not wait on
    the operator's paperwork - and the launch-readiness gate reports the gap.
    """

    if not plan.required:
        return None
    escalation_id = uuid4()
    result = await session.execute(
        text(
            # Files into the established referral queue, not a private one:
            # ai_assistant writes here, privacy reads here, and operators watch
            # here. Priority and risk_level are derived from severity so the
            # existing console can triage without knowing about this module.
            "INSERT INTO ai_human_referrals "
            "(id,referral_number,conversation_id,user_id,referral_type,priority,risk_category,"
            " risk_level,status,assigned_team,consent_status,idempotency_key,"
            " geography_code,runbook_id,severity) "
            "SELECT :id,'AIE-' || substr(replace(CAST(:id AS text),'-',''),1,16),"
            "  :conversation_id,:user_id,'ai_safety_escalation',"
            "  CASE WHEN :severity >= 3 THEN 'urgent' WHEN :severity = 2 THEN 'high' "
            "       ELSE 'normal' END,"
            "  :reason,"
            "  CASE WHEN :severity >= 3 THEN 'critical' WHEN :severity = 2 THEN 'high' "
            "       ELSE 'standard' END,"
            "  'pending_assignment','safety','system_initiated',:dedupe,:geography,"
            "  (SELECT id FROM ai_escalation_runbooks WHERE is_active=true "
            "     AND (geography_code=:geography OR geography_code IS NULL) "
            "   ORDER BY geography_code NULLS LAST LIMIT 1),:severity "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id"
        ),
        {
            "id": str(escalation_id),
            "user_id": str(user_id),
            "conversation_id": str(conversation_id),
            "reason": plan.reason_code,
            "severity": plan.severity,
            "geography": geography_code,
            "dedupe": plan.dedupe_key or f"ai-escalation:{conversation_id}:{plan.reason_code}",
        },
    )
    row = result.first()
    if row is None:
        return None
    await _publish(
        session,
        "ai.escalation.opened.v1",
        conversation_id,
        {"reason_code": plan.reason_code, "severity": plan.severity},
    )
    return escalation_id


# ---------------------------------------------------------------------------
# The turn
# ---------------------------------------------------------------------------


async def run_turn(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    payload: dict[str, Any],
    client: ProviderClient | None = None,
) -> dict[str, Any]:
    """Screen, budget, call, label - in that order, with refusals at every step."""

    enabled()
    client = client or resolve_provider_client()
    settings = get_settings()
    now = _now()
    label_version = settings.ai_limitation_label_version
    prompt = str(payload["prompt"])
    request_id = str(payload["request_id"])
    geography_code = payload.get("geography_code")
    locale = payload.get("locale")

    # --- crisis routing runs first and fails closed --------------------------
    crisis = None
    if settings.ai_crisis_routing_enabled and payload.get("crisis_suspected"):
        crisis = route_crisis(
            await _load_crisis_resources(session, geography_code=geography_code),
            geography_code=geography_code,
            locale=locale,
            now=now,
        )
        escalation_plan = plan_escalation(crisis=crisis, conversation_id=conversation_id)
        await _open_escalation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            plan=escalation_plan,
            geography_code=geography_code,
        )
        await _record_refusal(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            refusal_code="AI_CRISIS_ESCALATED",
        )
        response = build_refusal(
            refusal_code="AI_CRISIS_ESCALATED",
            label_version=label_version,
            escalation_reason_code=escalation_plan.reason_code,
            crisis_resource_codes=crisis.resource_codes,
        )
        ensure_limitation_labelled(response)
        return response.as_dict()

    rules = await _load_policy_rules(session)
    limits = await _load_budget_limits(session)
    usage = await _load_usage(session, user_id=user_id, conversation_id=conversation_id, now=now)
    profiles = await _load_profiles(session)
    health = await _load_health(session, now=now)

    prompt_tokens = estimate_prompt_tokens(prompt)
    max_output_tokens = int(payload.get("max_output_tokens") or 800)

    try:
        request_plan = plan_request(
            rules=rules,
            prompt=prompt,
            profiles=profiles,
            health=health,
            limits=limits,
            usage=usage,
            prompt_tokens=prompt_tokens,
            max_output_tokens=max_output_tokens,
            now=now,
            locale=locale,
            capability="chat",
            require_all_scopes=settings.ai_budget_require_all_scopes,
            member_requested_human=bool(payload.get("request_human")),
            conversation_id=conversation_id,
        )
    except AiRuleError as error:
        # Refused before any provider call: policy block, budget breach or no
        # healthy provider. All three produce an explicit refusal payload.
        await _record_refusal(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            refusal_code=error.code,
        )
        escalation = plan_escalation(
            provider_outage=error.code == "AI_PROVIDER_UNAVAILABLE",
            member_requested=bool(payload.get("request_human")),
            conversation_id=conversation_id,
        )
        await _open_escalation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            plan=escalation,
            geography_code=geography_code,
        )
        response = build_refusal(
            refusal_code=error.code,
            label_version=label_version,
            escalation_reason_code=escalation.reason_code,
        )
        ensure_limitation_labelled(response)
        return response.as_dict()

    await _record_policy_decision(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        decision=request_plan.policy,
    )
    entry_id = await _reserve_usage(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        profile=request_plan.profile,
        estimate=request_plan.estimate,
    )

    try:
        answer_text, output_tokens = await client.complete(
            profile=request_plan.profile,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
        )
        response = build_answer(
            answer=answer_text,
            profile=request_plan.profile,
            label_version=label_version,
            policy_action=request_plan.policy.action,
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": output_tokens},
        )
    except Exception as error:  # noqa: BLE001 - any provider failure fails safe
        await _record_provider_result(
            session,
            provider_code=request_plan.profile.provider_code,
            succeeded=False,
            now=now,
        )
        await session.execute(
            text("UPDATE ai_usage_entries SET state='released',refusal_code=:code WHERE id=:id"),
            {"id": str(entry_id), "code": "AI_PROVIDER_UNAVAILABLE"},
        )
        escalation = plan_escalation(provider_outage=True, conversation_id=conversation_id)
        await _open_escalation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            plan=escalation,
            geography_code=geography_code,
        )
        await _publish(
            session,
            "ai.provider.failed.v1",
            conversation_id,
            {
                "provider_code": request_plan.profile.provider_code,
                "error": type(error).__name__,
            },
        )
        # Never a fabricated answer: an outage produces a refusal, full stop.
        response = build_refusal(
            refusal_code="AI_PROVIDER_UNAVAILABLE",
            label_version=label_version,
            escalation_reason_code=escalation.reason_code,
            provider_code=request_plan.profile.provider_code,
        )
        ensure_limitation_labelled(response)
        return response.as_dict()

    actual = reconcile_usage(request_plan.estimate, actual_output_tokens=output_tokens)
    await session.execute(
        text(
            "UPDATE ai_usage_entries SET state='committed',completion_tokens=:completion,"
            "total_tokens=:total,cost_millicents=:cost WHERE id=:id"
        ),
        {
            "id": str(entry_id),
            "completion": actual.max_output_tokens,
            "total": actual.total_tokens,
            "cost": actual.millicents,
        },
    )
    await _record_provider_result(
        session,
        provider_code=request_plan.profile.provider_code,
        succeeded=True,
        now=now,
    )
    if request_plan.escalation.required:
        await _open_escalation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            plan=request_plan.escalation,
            geography_code=geography_code,
        )
    ensure_limitation_labelled(response)
    return response.as_dict()


def estimate_prompt_tokens(prompt: str) -> int:
    """A deliberately conservative local estimate.

    Four characters per token under-counts for Chinese text, so the estimate
    rounds up on character count instead. Over-estimating spends budget the
    request may not use; under-estimating spends money the budget did not
    approve. The first error is the recoverable one.
    """

    return max(1, len(prompt))


# ---------------------------------------------------------------------------
# Member-facing reads
# ---------------------------------------------------------------------------


async def get_my_budget(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """What the member has left today. Never another member's numbers."""

    enabled()
    now = _now()
    limits = await _load_budget_limits(session)
    row = (
        (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(total_tokens),0) AS tokens FROM ai_usage_entries "
                    "WHERE user_id=:user_id AND state IN ('reserved','committed') "
                    "AND occurred_at >= date_trunc('day', :now)"
                ),
                {"user_id": str(user_id), "now": now},
            )
        )
        .mappings()
        .first()
    )
    used = int(row["tokens"]) if row else 0
    limit = limits.user_daily_tokens
    return {
        "user_daily_token_limit": limit,
        "user_daily_tokens_used": used,
        "user_daily_tokens_remaining": None if limit is None else max(0, limit - used),
        "budget_configured": limit is not None,
    }


async def request_human(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """A member asking for a person. Always honoured, never triaged away."""

    enabled()
    plan = plan_escalation(member_requested=True, conversation_id=conversation_id)
    escalation_id = await _open_escalation(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        plan=plan,
        geography_code=None,
    )
    return {
        "escalation_opened": True,
        "escalation_id": str(escalation_id) if escalation_id else None,
        "reason_code": plan.reason_code,
    }


# ---------------------------------------------------------------------------
# Administrative writes
# ---------------------------------------------------------------------------


async def upsert_budget_policy(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    scope = payload["scope"]
    if scope == BudgetScope.GLOBAL_MONTHLY.value and payload.get("limit_millicents") is None:
        raise VavError(
            "AI_BUDGET_LIMIT_REQUIRED",
            "The global monthly budget is a cost limit and requires limit_millicents.",
            status_code=422,
        )
    if scope != BudgetScope.GLOBAL_MONTHLY.value and payload.get("limit_tokens") is None:
        raise VavError(
            "AI_BUDGET_LIMIT_REQUIRED",
            "A per-user or per-conversation budget is a token limit and requires limit_tokens.",
            status_code=422,
        )
    await session.execute(
        text(
            "INSERT INTO ai_budget_policies (scope,limit_tokens,limit_millicents,is_active,updated_by) "
            "VALUES (:scope,:limit_tokens,:limit_millicents,:is_active,:actor) "
            "ON CONFLICT (scope) DO UPDATE SET limit_tokens=EXCLUDED.limit_tokens,"
            "limit_millicents=EXCLUDED.limit_millicents,is_active=EXCLUDED.is_active,"
            "updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "scope": scope,
            "limit_tokens": payload.get("limit_tokens"),
            "limit_millicents": payload.get("limit_millicents"),
            "is_active": bool(payload["is_active"]),
            "actor": str(actor_id),
        },
    )
    return {"scope": scope, "is_active": bool(payload["is_active"])}


async def upsert_policy_rule(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    try:
        PolicyRule(
            rule_code=payload["rule_code"],
            category=payload["category"],
            match_kind=payload["match_kind"],
            pattern=payload["pattern"],
            action=PolicyAction(payload["action"]),
            severity=int(payload["severity"]),
            surface=PolicySurface(payload["surface"]),
            locale=payload.get("locale"),
            is_active=bool(payload["is_active"]),
        )
    except AiRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "INSERT INTO ai_content_policy_rules "
            "(rule_code,category,match_kind,pattern,action,severity,surface,locale,is_active,updated_by) "
            "VALUES (:rule_code,:category,:match_kind,:pattern,:action,:severity,:surface,:locale,:is_active,:actor) "
            "ON CONFLICT (rule_code) DO UPDATE SET category=EXCLUDED.category,"
            "match_kind=EXCLUDED.match_kind,pattern=EXCLUDED.pattern,action=EXCLUDED.action,"
            "severity=EXCLUDED.severity,surface=EXCLUDED.surface,locale=EXCLUDED.locale,"
            "is_active=EXCLUDED.is_active,updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "rule_code": payload["rule_code"],
            "category": payload["category"],
            "match_kind": payload["match_kind"],
            "pattern": payload["pattern"],
            "action": payload["action"],
            "severity": int(payload["severity"]),
            "surface": payload["surface"],
            "locale": payload.get("locale"),
            "is_active": bool(payload["is_active"]),
            "actor": str(actor_id),
        },
    )
    return {"rule_code": payload["rule_code"]}


async def upsert_crisis_resource(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create or update a crisis resource. It starts unverified and unusable.

    Activation is a separate, permissioned act (:func:`verify_crisis_resource`)
    because a wrong number here is the most damaging row in the database.
    """

    enabled()
    await session.execute(
        text(
            "INSERT INTO ai_crisis_resources "
            "(resource_code,geography_code,locale,contact_kind,contact_value,is_active,updated_by) "
            "VALUES (:resource_code,:geography_code,:locale,:contact_kind,:contact_value,false,:actor) "
            "ON CONFLICT (resource_code,geography_code,locale) DO UPDATE SET "
            "contact_kind=EXCLUDED.contact_kind,contact_value=EXCLUDED.contact_value,"
            # Any edit clears the verification: the number that was checked is
            # not necessarily the number that is stored now.
            "is_active=false,verified_by=NULL,verified_at=NULL,"
            "updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "resource_code": payload["resource_code"],
            "geography_code": payload["geography_code"],
            "locale": payload["locale"],
            "contact_kind": payload["contact_kind"],
            "contact_value": payload["contact_value"],
            "actor": str(actor_id),
        },
    )
    return {"resource_code": payload["resource_code"], "is_active": False, "verified": False}


async def verify_crisis_resource(
    session: AsyncSession, *, resource_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    await session.execute(
        text(
            "UPDATE ai_crisis_resources SET verified_by=:actor,verified_at=now(),"
            "verification_note=:note,is_active=:activate,updated_at=now() WHERE id=:id"
        ),
        {
            "id": str(resource_id),
            "actor": str(actor_id),
            "note": payload["verification_note"],
            "activate": bool(payload["activate"]),
        },
    )
    return {
        "resource_id": str(resource_id),
        "verified": True,
        "is_active": bool(payload["activate"]),
    }


async def upsert_runbook(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    await session.execute(
        text(
            "INSERT INTO ai_escalation_runbooks "
            "(runbook_code,geography_code,owner_role_code,document_reference,acknowledgement_target_minutes,is_active,approved_by,approved_at) "
            "VALUES (:runbook_code,:geography_code,:owner_role_code,:document_reference,:target,:is_active,:actor,now()) "
            "ON CONFLICT (runbook_code) DO UPDATE SET geography_code=EXCLUDED.geography_code,"
            "owner_role_code=EXCLUDED.owner_role_code,document_reference=EXCLUDED.document_reference,"
            "acknowledgement_target_minutes=EXCLUDED.acknowledgement_target_minutes,"
            "is_active=EXCLUDED.is_active,approved_by=EXCLUDED.approved_by,approved_at=now(),updated_at=now()"
        ),
        {
            "runbook_code": payload["runbook_code"],
            "geography_code": payload.get("geography_code"),
            "owner_role_code": payload["owner_role_code"],
            "document_reference": payload["document_reference"],
            "target": int(payload["acknowledgement_target_minutes"]),
            "is_active": bool(payload["is_active"]),
            "actor": str(actor_id),
        },
    )
    return {"runbook_code": payload["runbook_code"]}


async def decide_escalation(
    session: AsyncSession, *, escalation_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    row = (
        (
            await session.execute(
                text("SELECT status FROM ai_human_referrals WHERE id=:id FOR UPDATE"),
                {"id": str(escalation_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("AI_ESCALATION_NOT_FOUND", "Escalation not found.", status_code=404)
    try:
        validate_escalation_transition(row["status"], payload["status"])
    except AiRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "UPDATE ai_human_referrals SET status=:status,"
            "acknowledged_at=CASE WHEN :status='acknowledged' THEN now() ELSE acknowledged_at END,"
            "resolved_at=CASE WHEN :status IN ('resolved','cancelled') THEN now() ELSE resolved_at END,"
            "assigned_to=COALESCE(assigned_to, :actor),"
            "resolution_encrypted=COALESCE(:note, resolution_encrypted) WHERE id=:id"
        ),
        {
            "id": str(escalation_id),
            "status": payload["status"],
            "actor": str(actor_id),
            "note": payload.get("note"),
        },
    )
    return {"escalation_id": str(escalation_id), "status": payload["status"]}


async def record_launch_gate(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    await session.execute(
        text(
            "INSERT INTO ai_launch_gates (gate_code,is_met,evidence_ref,note,checked_by,checked_at) "
            "VALUES (:gate_code,:is_met,:evidence_ref,:note,:actor,COALESCE(:checked_at, now())) "
            "ON CONFLICT (gate_code) DO UPDATE SET is_met=EXCLUDED.is_met,"
            "evidence_ref=EXCLUDED.evidence_ref,note=EXCLUDED.note,checked_by=EXCLUDED.checked_by,"
            "checked_at=EXCLUDED.checked_at,updated_at=now()"
        ),
        {
            "gate_code": payload["gate_code"],
            "is_met": bool(payload["is_met"]),
            "evidence_ref": payload.get("evidence_ref"),
            "note": payload.get("note"),
            "actor": str(actor_id),
            "checked_at": payload.get("checked_at"),
        },
    )
    return {"gate_code": payload["gate_code"], "is_met": bool(payload["is_met"])}


async def get_launch_readiness(session: AsyncSession) -> dict[str, Any]:
    """Report which launch gates are unmet, deriving what it can from the data.

    Three gates are answered by the database rather than by an attestation, so
    an operator cannot tick a box the schema disagrees with: crisis resources,
    content policy rules and budget limits are each measured directly.
    """

    enabled()
    now = _now()
    settings = get_settings()
    rows = (
        (
            await session.execute(
                text("SELECT gate_code,is_met,evidence_ref,checked_at FROM ai_launch_gates")
            )
        )
        .mappings()
        .all()
    )
    gates = [
        LaunchGate(
            gate_code=row["gate_code"],
            is_met=bool(row["is_met"]),
            evidence_ref=row["evidence_ref"],
            checked_at=row["checked_at"],
        )
        for row in rows
    ]
    measured = await _measure_gates(session, now=now)
    by_code = {gate.gate_code: gate for gate in gates}
    by_code.update({gate.gate_code: gate for gate in measured})
    readiness = evaluate_launch_readiness(
        by_code.values(),
        now=now,
        max_age=timedelta(days=settings.ai_launch_gate_max_age_days),
    )
    return {
        **readiness.as_dict(),
        "gates": [
            {
                "gate_code": gate.gate_code,
                "is_met": gate.is_met,
                "evidence_ref": gate.evidence_ref,
                "checked_at": gate.checked_at.isoformat() if gate.checked_at else None,
            }
            for gate in sorted(by_code.values(), key=lambda item: item.gate_code)
        ],
    }


async def _measure_gates(session: AsyncSession, *, now: datetime) -> list[LaunchGate]:
    counts = (
        (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM ai_crisis_resources WHERE is_active=true AND verified_at IS NOT NULL) AS crisis,"
                    "(SELECT count(*) FROM ai_content_policy_rules WHERE is_active=true) AS policies,"
                    "(SELECT count(*) FROM ai_budget_policies WHERE is_active=true) AS budgets,"
                    "(SELECT count(*) FROM ai_escalation_runbooks WHERE is_active=true) AS runbooks,"
                    "(SELECT count(*) FROM ai_provider_profiles WHERE is_enabled=true) AS providers"
                )
            )
        )
        .mappings()
        .first()
    )
    if counts is None:
        return []
    return [
        LaunchGate(
            gate_code="crisis_resources_configured",
            is_met=int(counts["crisis"]) > 0,
            evidence_ref=f"ai_crisis_resources:{counts['crisis']}",
            checked_at=now,
        ),
        LaunchGate(
            gate_code="content_policy_configured",
            is_met=int(counts["policies"]) > 0,
            evidence_ref=f"ai_content_policy_rules:{counts['policies']}",
            checked_at=now,
        ),
        LaunchGate(
            gate_code="budget_limits_configured",
            is_met=int(counts["budgets"]) >= 3,
            evidence_ref=f"ai_budget_policies:{counts['budgets']}",
            checked_at=now,
        ),
        LaunchGate(
            gate_code="human_escalation_runbook",
            is_met=int(counts["runbooks"]) > 0,
            evidence_ref=f"ai_escalation_runbooks:{counts['runbooks']}",
            checked_at=now,
        ),
        LaunchGate(
            gate_code="provider_fallback_configured",
            is_met=int(counts["providers"]) >= 2,
            evidence_ref=f"ai_provider_profiles:{counts['providers']}",
            checked_at=now,
        ),
        LaunchGate(
            gate_code="limitation_label_configured",
            is_met=bool(get_settings().ai_limitation_label_version),
            evidence_ref=f"settings:{get_settings().ai_limitation_label_version}",
            checked_at=now,
        ),
    ]


async def list_escalations(
    session: AsyncSession, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,user_id,conversation_id,risk_category AS reason_code,severity,"
                    "status,created_at AS opened_at,acknowledged_at,resolved_at "
                    "FROM ai_human_referrals "
                    "WHERE referral_type='ai_safety_escalation' "
                    "  AND (:status IS NULL OR status=:status) "
                    "ORDER BY severity DESC, created_at LIMIT :limit OFFSET :offset"
                ),
                {"status": status, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
            for row in rows
        ]
    }


async def list_policy_decisions(
    session: AsyncSession, *, action: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """The policy audit trail. Contains rule codes and counts, never prompts."""

    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,conversation_id,surface,action,matched_rule_codes,highest_severity,"
                    "decided_at FROM ai_policy_decisions "
                    "WHERE (:action IS NULL OR action=:action) "
                    "ORDER BY decided_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"action": action, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
            for row in rows
        ]
    }


def build_outage_response(*, provider_code: str | None = None) -> AiResponsePayload:
    """Public helper so callers outside a turn refuse the same way it does."""

    return build_refusal(
        refusal_code="AI_PROVIDER_UNAVAILABLE",
        label_version=get_settings().ai_limitation_label_version,
        escalation_reason_code="provider_outage",
        provider_code=provider_code,
    )
