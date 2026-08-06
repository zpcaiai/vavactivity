# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.admin_platform import service
from vav.modules.admin_platform.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    BulkPlan,
    CertificationDecision,
    CertificationEvaluate,
    ConfigurationAction,
    ConfigurationCreate,
    MaskRequest,
    RevealCreate,
    SavedViewCreate,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin/platform")


def _ok(value: Any, request: Request) -> dict[str, Any]:
    return success(value, request_id_from_request(request))


class Assignment(BaseModel):
    assigned_to: UUID | None = None


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("admin.workbench.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.dashboard(session), request)


@router.post("/workbench/sync")
async def sync_workbench(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("admin.workbench.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.sync_exception_work_items(session), request)


@router.post("/workbench/{item_id}/assign")
async def assign_work_item(
    item_id: UUID,
    payload: Assignment,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.workbench.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.assign_work_item(session, principal.user.id, item_id, payload.assigned_to),
        request,
    )


@router.get("/entities/{entity_type}/{entity_id}")
async def entity_view(
    entity_type: str,
    entity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.entities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.entity_view(session, entity_type, entity_id, set(principal.permissions)),
        request,
    )


@router.post("/saved-views")
async def create_saved_view(
    payload: SavedViewCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.saved_views.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.visibility != "private":
        principal.require("admin.saved_views.share")
    return _ok(await service.create_saved_view(session, principal.user.id, payload), request)


@router.post("/bulk-jobs")
async def plan_bulk(
    payload: BulkPlan,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.bulk.plan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.plan_bulk(session, principal.user.id, payload), request)


@router.post("/approvals")
async def create_approval(
    payload: ApprovalCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.approvals.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_approval(session, principal.user.id, payload), request)


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecision,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.approvals.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require(
        "admin.approvals.approve" if payload.decision == "approved" else "admin.approvals.reject"
    )
    return _ok(
        await service.decide_approval(session, principal.user.id, approval_id, payload), request
    )


@router.post("/configurations")
async def create_configuration(
    payload: ConfigurationCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.configurations.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_configuration(session, principal.user.id, payload), request)


@router.post("/configurations/{version_id}/action")
async def act_configuration(
    version_id: UUID,
    payload: ConfigurationAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.configurations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require(f"admin.configurations.{payload.action}")
    return _ok(
        await service.act_configuration(session, principal.user.id, version_id, payload), request
    )


@router.post("/field-access/reveal")
async def create_reveal(
    payload: RevealCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.fields.reveal")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_reveal(session, principal.user.id, payload), request)


@router.post("/field-access/mask")
async def apply_masking(
    payload: MaskRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.entities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.apply_masking(session, principal.user.id, payload), request)


@router.post("/certifications/evaluate")
async def evaluate_certification(
    payload: CertificationEvaluate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.certifications.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_certification(session, principal.user.id, payload), request)


@router.post("/certifications/{certification_id}/decide")
async def decide_certification(
    certification_id: UUID,
    payload: CertificationDecision,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admin.certifications.certify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.decide_certification(
            session, principal.user.id, certification_id, payload.decision
        ),
        request,
    )


SECTION_PERMISSIONS = {
    "capabilities": "admin.capabilities.read",
    "work-items": "admin.workbench.read",
    "saved-views": "admin.saved_views.read",
    "bulk-jobs": "admin.bulk.read",
    "approvals": "admin.approvals.read",
    "exceptions": "admin.exceptions.read",
    "configurations": "admin.configurations.read",
    "field-access": "admin.fields.policies.read",
    "reveal-history": "admin.fields.policies.read",
    "certifications": "admin.certifications.read",
    "releases": "admin.certifications.read",
    "audit": "admin.audit.read",
}


@router.get("/{section}")
async def section(
    section: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require(SECTION_PERMISSIONS.get(section, "admin.capabilities.read"))
    return _ok(await service.list_section(session, section), request)
