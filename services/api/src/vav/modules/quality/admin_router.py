# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.quality import service
from vav.modules.quality.schemas import (
    BusinessFlowCreate,
    CapabilityCreate,
    EvidenceRegister,
    ExceptionScenarioCreate,
    GapAssignment,
    GapResolution,
    GateDefinitionCreate,
    ReleaseCertificationRequest,
    ReleaseEvaluationRequest,
    RequirementCreate,
    RequirementTransition,
    RiskCreate,
    TraceLinkCreate,
    TraceNodeCreate,
    WaiverRequest,
)

router = APIRouter(prefix="/admin/quality")


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


@router.get("/dashboard")
async def quality_dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.dashboard(session), request)


@router.get("/requirements")
async def requirements(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.requirements.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_requirements(session), request)


@router.post("/requirements")
async def create_requirement(
    payload: RequirementCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.requirements.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_requirement(session, principal.user.id, payload), request)


@router.post("/requirements/{requirement_id}/transition")
async def transition_requirement(
    requirement_id: UUID,
    payload: RequirementTransition,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.requirements.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.target_status == "approved":
        principal.require("quality.requirements.approve")
    return _ok(
        await service.transition_requirement(
            session, requirement_id, principal.user.id, payload.target_status
        ),
        request,
    )


@router.get("/capabilities")
async def capabilities(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.capabilities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_capabilities(session), request)


@router.post("/capabilities")
async def upsert_capability(
    payload: CapabilityCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.capabilities.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.upsert_capability(session, principal.user.id, payload), request)


@router.get("/traceability")
async def traceability(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.traceability.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_traceability(session), request)


@router.post("/traceability/nodes")
async def create_trace_node(
    payload: TraceNodeCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.traceability.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_trace_node(session, principal.user.id, payload), request)


@router.post("/traceability/links")
async def create_trace_link(
    payload: TraceLinkCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.traceability.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_trace_link(session, principal.user.id, payload), request)


@router.post("/traceability/links/{link_id}/verify")
async def verify_trace_link(
    link_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.traceability.verify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.verify_trace_link(session, principal.user.id, link_id), request)


@router.get("/business-flows")
async def business_flows(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.business_flows.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_business_flows(session), request)


@router.post("/business-flows")
async def create_business_flow(
    payload: BusinessFlowCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("quality.business_flows.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_business_flow(session, principal.user.id, payload), request)


@router.post("/business-flows/{flow_id}/certify")
async def certify_business_flow(
    flow_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("quality.business_flows.certify")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.certify_business_flow(session, principal.user.id, flow_id), request)


@router.post("/exception-scenarios")
async def create_exception_scenario(
    payload: ExceptionScenarioCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("quality.business_flows.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.create_exception_scenario(session, principal.user.id, payload), request
    )


@router.get("/gaps")
async def gaps(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.gaps.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_gaps(session), request)


@router.post("/gaps/{gap_id}/assign")
async def assign_gap(
    gap_id: UUID,
    payload: GapAssignment,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gaps.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.assign_gap(
            session, principal.user.id, gap_id, payload.owner_team, payload.owner_user_id
        ),
        request,
    )


@router.post("/gaps/{gap_id}/resolve")
async def resolve_gap(
    gap_id: UUID,
    payload: GapResolution,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gaps.resolve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.resolve_gap(session, principal.user.id, gap_id, payload.resolution_summary),
        request,
    )


@router.get("/risks")
async def risks(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.risks.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_risks(session), request)


@router.post("/risks")
async def create_risk(
    payload: RiskCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.risks.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_risk(session, principal.user.id, payload), request)


@router.get("/waivers")
async def waivers(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.waivers.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_waivers(session), request)


@router.post("/waivers")
async def request_waiver(
    payload: WaiverRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.waivers.request")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.request_waiver(session, principal.user.id, payload), request)


@router.post("/waivers/{waiver_id}/approve")
async def approve_waiver(
    waiver_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.waivers.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.approve_waiver(session, principal.user.id, waiver_id), request)


@router.post("/waivers/{waiver_id}/revoke")
async def revoke_waiver(
    waiver_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.waivers.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.revoke_waiver(session, principal.user.id, waiver_id), request)


@router.get("/evidence")
async def evidence(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.evidence.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_evidence(session), request)


@router.post("/evidence")
async def register_evidence(
    payload: EvidenceRegister,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.evidence.register")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.register_evidence(session, principal.user.id, payload), request)


@router.post("/evidence/{evidence_id}/validate")
async def validate_evidence(
    evidence_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.evidence.validate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.transition_evidence(session, principal.user.id, evidence_id, "validated"),
        request,
    )


@router.post("/evidence/{evidence_id}/accept")
async def accept_evidence(
    evidence_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.evidence.accept")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.transition_evidence(session, principal.user.id, evidence_id, "accepted"),
        request,
    )


@router.get("/gates")
async def gates(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_gates(session), request)


@router.post("/gates")
async def create_gate(
    payload: GateDefinitionCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_gate(session, principal.user.id, payload), request)


@router.post("/gates/{gate_id}/approve")
async def approve_gate(
    gate_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.approve_gate(session, principal.user.id, gate_id), request)


@router.post("/gates/{_gate_id}/rerun")
async def rerun_gate(
    _gate_id: UUID,
    payload: ReleaseEvaluationRequest,
    request: Request,
    release_version: str = Query(min_length=1, max_length=64),
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.evaluate_release(session, principal.user.id, release_version, payload),
        request,
    )


@router.get("/gate-runs")
async def gate_runs(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_gate_runs(session), request)


@router.post("/releases/{release_version}/evaluate")
async def evaluate_release(
    release_version: str,
    payload: ReleaseEvaluationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.gates.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.evaluate_release(session, principal.user.id, release_version, payload),
        request,
    )


@router.get("/releases")
async def releases(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.releases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_releases(session), request)


@router.get("/releases/{release_version}")
async def release_detail(
    release_version: str,
    request: Request,
    environment: str = Query(default="production", pattern="^(test|ci|staging|production|dr)$"),
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.releases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.release_detail(session, release_version, environment), request)


@router.post("/releases/{release_version}/certify")
async def certify_release(
    release_version: str,
    payload: ReleaseCertificationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("quality.releases.certify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.certify_release(
            session,
            principal.user.id,
            release_version,
            payload.environment,
            payload.evidence_manifest,
        ),
        request,
    )


@router.get("/certifications")
async def certifications(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.releases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.list_certifications(session),
        request,
    )


@router.get("/audit")
async def quality_audit(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("quality.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_quality_audit(session), request)
