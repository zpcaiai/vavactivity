# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission
from vav.modules.usability import service
from vav.modules.usability.schemas import (
    CertificationEvaluate,
    DraftSave,
    ImportPreview,
    UatRunComplete,
    UatRunCreate,
)

router = APIRouter(prefix="/admin/usability")


def _ok(value: Any, request: Request) -> dict[str, Any]:
    return success(value, request_id_from_request(request))


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("usability.dashboard.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.dashboard(session), request)


@router.post("/uat/runs")
async def start_uat(
    payload: UatRunCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("uat.runs.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.start_uat(session, principal.user.id, payload), request)


@router.post("/uat/runs/{run_id}/complete")
async def complete_uat(
    run_id: UUID,
    payload: UatRunComplete,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("uat.runs.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.complete_uat(session, run_id, payload), request)


@router.post("/drafts")
async def save_draft(
    payload: DraftSave,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("usability.drafts.write")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.save_draft(session, principal.user.id, payload), request)


@router.post("/imports/preview")
async def preview_import(
    payload: ImportPreview,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("usability.imports.preview")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.preview_import(session, principal.user.id, payload), request)


@router.post("/certifications/evaluate")
async def evaluate_certification(
    payload: CertificationEvaluate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("usability.certifications.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_certification(session, principal.user.id, payload), request)


PERMISSIONS = {
    "scenarios": "uat.scenarios.read",
    "runs": "uat.runs.read",
    "synthetic-data": "usability.synthetic.read",
    "demo": "usability.demo.read",
    "compatibility": "usability.compatibility.read",
    "localization": "usability.localization.read",
    "drafts": "usability.drafts.read",
    "notifications": "usability.notifications.read",
    "imports": "usability.imports.read",
    "studies": "usability.studies.read",
    "support": "usability.support.read",
    "certifications": "usability.certifications.read",
    "release": "usability.certifications.read",
}


@router.get("/{section}")
async def section(
    section: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require(PERMISSIONS.get(section, "usability.dashboard.read"))
    return _ok(await service.list_section(session, section), request)
