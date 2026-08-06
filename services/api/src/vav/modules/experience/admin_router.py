# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.experience import service
from vav.modules.experience.schemas import (
    ClosureCertification,
    ClosureEvaluation,
    DeadEndResolution,
    DeepLinkCreate,
    JourneyReconcile,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin/experience")


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


SECTION_PERMISSIONS = {
    "ia": "experience.ia.read",
    "routes": "experience.routes.read",
    "tasks": "experience.tasks.read",
    "journeys": "experience.journeys.read",
    "handoffs": "experience.handoffs.read",
    "search-governance": "experience.search.read",
    "help": "experience.help.read",
    "support": "experience.support.read",
    "dead-ends": "experience.dead_ends.read",
    "evidence": "experience.closure.read",
}


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("experience.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.admin_dashboard(session), request)


@router.get("/navigation")
async def admin_navigation(
    request: Request,
    locale: str = Query(default="zh-CN", pattern=r"^(zh-CN|zh-TW|en)$"),
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.navigation.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.navigation(
            session,
            application_code="admin-web",
            authenticated=True,
            permissions=set(principal.permissions),
            locale=locale,
        ),
        request,
    )


@router.get("/analytics")
async def analytics(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("experience.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.analytics(session), request)


@router.get("/audit")
async def audit(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("experience.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.audit_log(session), request)


@router.get("/{section}")
async def section(
    section: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission = SECTION_PERMISSIONS.get(section)
    if permission is None:
        raise VavError(
            "EXPERIENCE_SECTION_NOT_FOUND", "The experience section was not found.", status_code=404
        )
    principal.require(permission)
    return _ok(await service.admin_list(session, section), request)


@router.post("/dead-ends/scan")
async def dead_end_scan(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.dead_ends.scan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.scan_dead_ends(session, principal.user.id), request)


@router.post("/dead-ends/{finding_id}/resolve")
async def resolve_dead_end(
    finding_id: UUID,
    payload: DeadEndResolution,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.dead_ends.resolve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE experience_dead_end_findings SET status=:status,resolved_at=now(),resolved_by=:actor,evidence=evidence || CAST(:evidence AS jsonb) WHERE id=:id AND status IN ('open','acknowledged') RETURNING *"
            ),
            {
                "status": payload.resolution,
                "actor": principal.user.id,
                "evidence": service._json({"resolution_reason": payload.reason}),
                "id": finding_id,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "EXPERIENCE_DEAD_END_NOT_RESOLVABLE",
            "The finding is not open for resolution.",
            status_code=409,
        )
    await session.commit()
    return _ok(service._row(row), request)


@router.post("/journeys/{journey_id}/reconcile")
async def reconcile_journey(
    journey_id: UUID,
    payload: JourneyReconcile,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("experience.journeys.reconcile")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.reconcile_journey(session, principal.user.id, journey_id, payload), request
    )


@router.post("/deep-links")
async def create_deep_link(
    payload: DeepLinkCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.handoffs.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_deep_link(session, principal.user.id, payload), request)


@router.get("/search/query")
async def admin_search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.search.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.search(
            session,
            query=q,
            user_id=principal.user.id,
            permissions=set(principal.permissions),
            admin=True,
        ),
        request,
    )


@router.post("/closure/evaluate")
async def evaluate_closure(
    payload: ClosureEvaluation,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.closure.evaluate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_closure(session, principal.user.id, payload), request)


@router.post("/closure/{closure_id}/certify")
async def certify_closure(
    closure_id: UUID,
    payload: ClosureCertification,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("experience.closure.certify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.certify_closure(
            session,
            principal.user.id,
            closure_id,
            payload.decision,
            payload.reason,
            payload.evidence_manifest,
        ),
        request,
    )
