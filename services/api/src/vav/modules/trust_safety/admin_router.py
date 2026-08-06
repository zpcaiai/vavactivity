"""Least-privilege Trust & Safety operations APIs."""

# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.trust_safety import service
from vav.modules.trust_safety.schemas import (
    AdminReasonRequest,
    AppealDecisionRequest,
    BehaviorAggregateRequest,
    CaseAssignmentRequest,
    CaseDecisionRequest,
    CaseTransitionRequest,
    EvidenceAccessRequest,
    FraudSignalRequest,
    ModerationDecisionRequest,
    RedTeamRunCompleteRequest,
    RedTeamRunCreateRequest,
    RestrictionCreateRequest,
    RuleCreateRequest,
)

router = APIRouter(prefix="/admin/trust-safety")


@router.get("/reports")
async def report_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.reports.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "reports"), request_id_from_request(request))


@router.get("/cases")
async def case_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.cases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "cases"), request_id_from_request(request))


@router.get("/cases/{case_id}")
async def case_detail(
    case_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.cases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_case_detail(session, case_id=case_id), request_id_from_request(request)
    )


@router.post("/cases/{case_id}/assign")
async def assign_case(
    case_id: UUID,
    payload: CaseAssignmentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.cases.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.assign_case(
            session, case_id=case_id, actor=principal.user.id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.post("/cases/{case_id}/decisions")
async def create_case_decision(
    case_id: UUID,
    payload: CaseDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.cases.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_case_decision(
            session, case_id=case_id, actor=principal.user.id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.post("/cases/{case_id}/decisions/{decision_id}/approve")
async def approve_case_decision(
    case_id: UUID,
    decision_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("safety.cases.approve_high_impact")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_case_decision(
            session, case_id=case_id, decision_id=decision_id, approver=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/evidence/{evidence_id}/access")
async def access_evidence(
    evidence_id: UUID,
    payload: EvidenceAccessRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.evidence.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission_code = (
        "safety.evidence.highly_restricted.read"
        if "safety.evidence.highly_restricted.read" in principal.permissions
        else "safety.evidence.read"
    )
    return success(
        await service.access_evidence(
            session,
            evidence_id=evidence_id,
            actor=principal.user.id,
            permission_code=permission_code,
            payload=payload,
        ),
        request_id_from_request(request),
    )


@router.post("/cases/{case_id}/transition")
async def transition_case(
    case_id: UUID,
    payload: CaseTransitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.cases.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.transition_case(
            session, case_id=case_id, actor=principal.user.id, target_status=payload.target_status
        ),
        request_id_from_request(request),
    )


@router.get("/moderation")
async def moderation_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.moderation.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_queue(session, "moderation"), request_id_from_request(request)
    )


@router.post("/moderation/{task_id}/decisions")
async def decide_moderation(
    task_id: UUID,
    payload: ModerationDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.moderation.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_moderation(
            session, task_id=task_id, actor=principal.user.id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.get("/restrictions")
async def restriction_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.restrictions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_queue(session, "restrictions"), request_id_from_request(request)
    )


@router.post("/restrictions")
async def create_restriction(
    payload: RestrictionCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.restrictions.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_restriction(session, actor=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.post("/restrictions/{restriction_id}/approve")
async def approve_restriction(
    restriction_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("safety.restrictions.high_impact.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_restriction(
            session, restriction_id=restriction_id, approver=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/restrictions/{restriction_id}/lift")
async def lift_restriction(
    restriction_id: UUID,
    payload: AdminReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.restrictions.lift")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.lift_restriction(
            session, restriction_id=restriction_id, actor=principal.user.id, reason=payload.reason
        ),
        request_id_from_request(request),
    )


@router.get("/appeals")
async def appeal_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.appeals.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "appeals"), request_id_from_request(request))


@router.post("/appeals/{appeal_id}/decision")
async def decide_appeal(
    appeal_id: UUID,
    payload: AppealDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.appeals.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_appeal(
            session, appeal_id=appeal_id, reviewer=principal.user.id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.get("/rules")
async def rule_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.rules.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "rules"), request_id_from_request(request))


@router.post("/rules")
async def create_rule(
    payload: RuleCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.rules.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_rule(session, actor=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.post("/rules/{rule_id}/activate")
async def activate_rule(
    rule_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.rules.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_and_activate_rule(
            session, rule_id=rule_id, approver=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/rules/{rule_id}/rollback")
async def rollback_rule(
    rule_id: UUID,
    payload: AdminReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.rules.rollback")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.rollback_rule(
            session, rule_id=rule_id, actor=principal.user.id, reason=payload.reason
        ),
        request_id_from_request(request),
    )


@router.get("/harassment")
async def harassment_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_queue(session, "harassment"), request_id_from_request(request)
    )


@router.post("/harassment/aggregates")
async def upsert_behavior_aggregate(
    payload: BehaviorAggregateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.cases.investigate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_behavior_aggregate(session, actor=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.get("/fraud")
async def fraud_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "fraud"), request_id_from_request(request))


@router.post("/fraud/signals")
async def create_fraud_signal(
    payload: FraudSignalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.cases.investigate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_fraud_signal(session, actor=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.get("/red-team")
async def red_team_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.red_team.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "red-team"), request_id_from_request(request))


@router.post("/red-team/runs")
async def create_red_team_run(
    payload: RedTeamRunCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.red_team.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_red_team_run(session, actor=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.post("/red-team/runs/{run_id}/complete")
async def complete_red_team_run(
    run_id: UUID,
    payload: RedTeamRunCompleteRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.red_team.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.complete_red_team_run(
            session, run_id=run_id, actor=principal.user.id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.post("/red-team/runs/{run_id}/approve")
async def approve_red_team_run(
    run_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("safety.red_team.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_red_team_run(session, run_id=run_id, approver=principal.user.id),
        request_id_from_request(request),
    )


@router.get("/audit")
async def audit_queue(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("safety.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_queue(session, "audit"), request_id_from_request(request))
