# ruff: noqa: B008, E501

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
from vav.modules.quality import design_service
from vav.modules.quality.design_schemas import (
    AuditReview,
    AuditRunCreate,
    BaselineCreate,
    BaselineDecision,
    ComponentDeprecate,
    ComponentUpsert,
    PatternUpsert,
    ReleaseEvidence,
    TokenReleaseCreate,
)

router = APIRouter(prefix="/admin/design-system")


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


@router.get("/dashboard")
async def dashboard(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.analytics.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.dashboard(session), request)


@router.get("/tokens")
async def tokens(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.tokens.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_tokens(session), request)


@router.post("/tokens")
async def create_tokens(payload: TokenReleaseCreate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.tokens.manage")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.create_token_release(session, principal.user.id, payload), request)


@router.post("/tokens/{release_id}/approve")
async def approve_tokens(release_id: UUID, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.tokens.approve")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.approve_token_release(session, principal.user.id, release_id), request)


@router.post("/tokens/{release_id}/release")
async def release_tokens(release_id: UUID, payload: ReleaseEvidence, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.tokens.release")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.release_tokens(session, principal.user.id, release_id, payload.evidence_manifest), request)


@router.get("/components")
async def components(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.components.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_components(session), request)


@router.post("/components")
async def upsert_component(payload: ComponentUpsert, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.components.manage")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.upsert_component(session, principal.user.id, payload), request)


@router.post("/components/{component_id}/deprecate")
async def deprecate_component(component_id: UUID, payload: ComponentDeprecate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.components.deprecate")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.deprecate_component(session, principal.user.id, component_id, payload.reason, payload.replacement_component_code), request)


@router.get("/patterns")
async def patterns(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.patterns.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_patterns(session), request)


@router.post("/patterns")
async def upsert_pattern(payload: PatternUpsert, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.patterns.manage")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.upsert_pattern(session, principal.user.id, payload), request)


@router.get("/pages")
async def pages(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_pages(session), request)


@router.get("/accessibility")
async def accessibility(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.accessibility.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_audits(session, "accessibility"), request)


@router.post("/accessibility")
async def create_accessibility_audit(payload: AuditRunCreate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.run")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    if payload.audit_type != "accessibility":
        payload = payload.model_copy(update={"audit_type": "accessibility", "manual_review_required": True})
    elif not payload.manual_review_required:
        payload = payload.model_copy(update={"manual_review_required": True})
    return _ok(await design_service.create_audit(session, principal.user.id, payload), request)


@router.post("/accessibility/{audit_id}/review")
async def review_accessibility(audit_id: UUID, payload: AuditReview, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.accessibility.review")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.review_audit(session, principal.user.id, audit_id, payload.decision, payload.reason), request)


@router.get("/responsive-audits")
async def responsive_audits(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_audits(session, "responsive"), request)


@router.post("/responsive-audits")
async def create_responsive_audit(payload: AuditRunCreate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.run")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.create_audit(session, principal.user.id, payload.model_copy(update={"audit_type": "responsive"})), request)


@router.get("/visual-regression")
async def visual_regression(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok({"runs": await design_service.list_audits(session, "visual"), "differences": await design_service.list_visual_differences(session)}, request)


@router.post("/visual-regression")
async def create_visual_audit(payload: AuditRunCreate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.run")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.create_audit(session, principal.user.id, payload.model_copy(update={"audit_type": "visual", "manual_review_required": True})), request)


@router.post("/audits/{audit_id}/review")
async def review_audit(audit_id: UUID, payload: AuditReview, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.audits.review")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.review_audit(session, principal.user.id, audit_id, payload.decision, payload.reason), request)


@router.get("/baselines")
async def baselines(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.baselines.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_baselines(session), request)


@router.post("/baselines")
async def create_baseline(payload: BaselineCreate, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.baselines.review")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.create_baseline(session, principal.user.id, payload), request)


@router.post("/baselines/{baseline_id}/decision")
async def decide_baseline(baseline_id: UUID, payload: BaselineDecision, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.baselines.approve")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.decide_baseline(session, principal.user.id, baseline_id, payload.decision, payload.reason), request)


@router.get("/evidence")
async def evidence(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.evidence.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_evidence(session), request)


@router.get("/releases")
async def releases(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.tokens.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_tokens(session), request)


@router.post("/evidence/{evidence_id}/accept")
async def accept_evidence(evidence_id: UUID, request: Request, principal: AuthenticatedPrincipal = Depends(require_permission("design.evidence.accept")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.accept_evidence(session, principal.user.id, evidence_id), request)


@router.get("/audit")
async def audit(request: Request, _principal: AuthenticatedPrincipal = Depends(require_permission("design.audit.read")), session: AsyncSession = Depends(get_database_session)) -> dict[str, Any]:
    return _ok(await design_service.list_design_audit(session), request)
