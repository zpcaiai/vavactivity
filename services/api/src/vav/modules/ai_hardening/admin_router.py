"""Administrative AI hardening API (B19 part 1).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.

Two permissions are separated on purpose: ``ai.crisis_resources.manage`` writes
a resource, and ``ai.crisis_resources.verify`` is what makes it live. A wrong
hotline number is the most damaging row in this schema, so authoring it and
attesting to it are different acts by different named people.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.ai_hardening import service
from vav.modules.ai_hardening.schemas import (
    BudgetPolicyRequest,
    CrisisResourceRequest,
    CrisisResourceVerifyRequest,
    EscalationDecisionRequest,
    EscalationRunbookRequest,
    LaunchGateRequest,
    PolicyRuleRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


# --- budgets ----------------------------------------------------------------


@router.put("/ai/budgets")
async def set_budget_policy(
    payload: BudgetPolicyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.budgets.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_budget_policy(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


# --- content policy ---------------------------------------------------------


@router.put("/ai/policy-rules")
async def set_policy_rule(
    payload: PolicyRuleRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.policies.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Author a content-policy rule. The platform ships none."""

    return success(
        await service.upsert_policy_rule(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/ai/policy-decisions")
async def policy_decisions(
    request: Request,
    action: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _principal: AuthenticatedPrincipal = Depends(require_permission("ai.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_policy_decisions(session, action=action, limit=limit, offset=offset),
        request_id_from_request(request),
    )


# --- crisis resources -------------------------------------------------------


@router.put("/ai/crisis-resources")
async def set_crisis_resource(
    payload: CrisisResourceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.crisis_resources.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Write a crisis resource. It is inactive until separately verified."""

    return success(
        await service.upsert_crisis_resource(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/ai/crisis-resources/{resource_id}/verification")
async def verify_crisis_resource(
    resource_id: UUID,
    payload: CrisisResourceVerifyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.crisis_resources.verify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.verify_crisis_resource(
            session,
            resource_id=resource_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- human escalation -------------------------------------------------------


@router.put("/ai/runbooks")
async def set_runbook(
    payload: EscalationRunbookRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.runbooks.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_runbook(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/ai/escalations")
async def escalations(
    request: Request,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _principal: AuthenticatedPrincipal = Depends(require_permission("ai.escalations.handle")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_escalations(session, status=status, limit=limit, offset=offset),
        request_id_from_request(request),
    )


@router.post("/ai/escalations/{escalation_id}/decision")
async def decide_escalation(
    escalation_id: UUID,
    payload: EscalationDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.escalations.handle")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_escalation(
            session,
            escalation_id=escalation_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- launch readiness -------------------------------------------------------


@router.get("/ai/launch-readiness")
async def launch_readiness(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("ai.launch_gates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Report which gates are unmet. Never reports ready by default."""

    return success(await service.get_launch_readiness(session), request_id_from_request(request))


@router.put("/ai/launch-gates")
async def record_launch_gate(
    payload: LaunchGateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.launch_gates.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_launch_gate(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )
