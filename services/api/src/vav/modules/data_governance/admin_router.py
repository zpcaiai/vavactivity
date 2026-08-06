# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.data_governance import service
from vav.modules.data_governance.schemas import (
    BackfillAction,
    BackfillStart,
    ErasurePlanCreate,
    ErasureTaskComplete,
    EventEnvelope,
    ExternalIdentifierCreate,
    InboxApply,
    IntegrityDecision,
    IntegrityEvaluate,
    ProjectionRebuild,
    QualityEvaluationCreate,
    ReconciliationRun,
    RepairRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin/data-governance")


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("data.dashboard.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.dashboard(session), request)


@router.post("/external-identifiers")
async def register_external_identifier(
    payload: ExternalIdentifierCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.assets.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.register_external_identifier(session, principal.user.id, payload), request
    )


@router.post("/quality/evaluate")
async def evaluate_quality(
    payload: QualityEvaluationCreate,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("data.quality.evaluate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_quality(session, payload), request)


@router.post("/repairs")
async def request_repair(
    payload: RepairRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.repairs.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.request_repair(session, principal.user.id, payload), request)


@router.post("/events/outbox")
async def enqueue_event(
    payload: EventEnvelope,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("data.events.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await service.enqueue_outbox(session, payload)
    await session.commit()
    return _ok(result, request)


@router.post("/events/inbox")
async def apply_event(
    payload: InboxApply,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("data.events.consume")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.apply_inbox(session, payload), request)


@router.post("/reconciliations/run")
async def run_reconciliation(
    payload: ReconciliationRun,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.reconciliations.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.run_reconciliation(session, principal.user.id, payload), request)


@router.post("/backfills")
async def start_backfill(
    payload: BackfillStart,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.backfills.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.start_backfill(session, principal.user.id, payload), request)


@router.post("/backfills/{run_id}/action")
async def act_backfill(
    run_id: UUID,
    payload: BackfillAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.backfills.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.action == "approve":
        principal.require("data.backfills.approve")
    return _ok(await service.act_backfill(session, principal.user.id, run_id, payload), request)


@router.post("/projections/rebuild")
async def rebuild_projection(
    payload: ProjectionRebuild,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.projections.rebuild")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.request_projection_rebuild(session, principal.user.id, payload), request
    )


@router.post("/erasures/plans")
async def create_erasure_plan(
    payload: ErasurePlanCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.erasures.plan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_erasure_plan(session, principal.user.id, payload), request)


@router.post("/erasures/tasks/{task_id}/complete")
async def complete_erasure_task(
    task_id: UUID,
    payload: ErasureTaskComplete,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.erasures.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.complete_erasure_task(session, principal.user.id, task_id, payload), request
    )


@router.post("/erasures/plans/{plan_id}/certificate")
async def issue_erasure_certificate(
    plan_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.erasures.certify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.issue_erasure_certificate(session, principal.user.id, plan_id), request
    )


@router.post("/certifications/evaluate")
async def evaluate_integrity(
    payload: IntegrityEvaluate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.certifications.evaluate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_integrity(session, principal.user.id, payload), request)


@router.post("/certifications/{certification_id}/decide")
async def decide_integrity(
    certification_id: UUID,
    payload: IntegrityDecision,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("data.certifications.certify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.decide_integrity(
            session, principal.user.id, certification_id, payload.decision, payload.reason
        ),
        request,
    )


SECTION_PERMISSIONS = {
    "assets": "data.assets.read",
    "contracts": "data.contracts.read",
    "lineage": "data.lineage.read",
    "events": "data.events.read",
    "event-gaps": "data.events.read",
    "dead-letters": "data.dead_letters.read",
    "quality": "data.quality.read",
    "reconciliations": "data.reconciliations.read",
    "differences": "data.reconciliations.read",
    "backfills": "data.backfills.read",
    "repairs": "data.repairs.read",
    "projections": "data.projections.read",
    "erasures": "data.erasures.read",
    "certifications": "data.certifications.read",
    "release": "data.release.read",
}


@router.get("/{section}")
async def section(
    section: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require(SECTION_PERMISSIONS.get(section, "data.assets.read"))
    return _ok(await service.list_section(session, section), request)
