# ruff: noqa: B008

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission
from vav.modules.process_governance import service
from vav.modules.process_governance.schemas import (
    CancellationCreate,
    CertificationDecision,
    CertificationEvaluate,
    CompensationRequest,
    EventReceive,
    InterventionResolve,
    ProcessStart,
    SimulationRequest,
    StepBegin,
    StepComplete,
)

router = APIRouter(prefix="/admin/processes")
ROOT = Path(__file__).resolve().parents[6]


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("process.dashboard.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.dashboard(session), request)


@router.post("/state-machines/verify")
async def verify_state_machines(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("process.state_machines.verify")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.verify_machines(session, principal.user.id), request)


@router.post("/instances")
async def start_instance(
    payload: ProcessStart,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.instances.start")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.start_process(session, principal.user.id, payload), request)


@router.get("/instances/{instance_id}")
async def instance_detail(
    instance_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("process.instances.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.instance_detail(session, instance_id), request)


@router.post("/instances/{instance_id}/steps/begin")
async def begin_step(
    instance_id: UUID,
    payload: StepBegin,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.sagas.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.begin_step(session, principal.user.id, instance_id, payload), request)


@router.post("/instances/{instance_id}/steps/complete")
async def complete_step(
    instance_id: UUID,
    payload: StepComplete,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.sagas.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.complete_step(session, principal.user.id, instance_id, payload), request
    )


@router.post("/instances/{instance_id}/events")
async def receive_event(
    instance_id: UUID,
    payload: EventReceive,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("process.events.consume")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.receive_event(session, instance_id, payload), request)


@router.post("/instances/{instance_id}/cancel")
async def cancel_process(
    instance_id: UUID,
    payload: CancellationCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.instances.cancel")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.cancel(session, principal.user.id, instance_id, payload), request)


@router.post("/instances/{instance_id}/compensations")
async def request_compensation(
    instance_id: UUID,
    payload: CompensationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("process.compensations.execute")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.request_compensation(session, principal.user.id, instance_id, payload),
        request,
    )


@router.post("/stuck/scan")
async def scan_stuck(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.stuck.scan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.scan_stuck(session, principal.user.id), request)


@router.post("/interventions/{task_id}/resolve")
async def resolve_intervention(
    task_id: UUID,
    payload: InterventionResolve,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("process.interventions.execute")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.resolve_intervention(session, principal.user.id, task_id, payload), request
    )


@router.post("/simulations")
async def run_simulation(
    payload: SimulationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("process.simulations.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    manifest = yaml.safe_load(
        (ROOT / "config/process/simulations.yaml").read_text(encoding="utf-8")
    )
    return _ok(
        await service.run_simulation(session, principal.user.id, payload, manifest["scenarios"]),
        request,
    )


@router.post("/certifications/evaluate")
async def evaluate_certification(
    payload: CertificationEvaluate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("process.certifications.evaluate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.evaluate_certification(session, principal.user.id, payload), request)


@router.post("/certifications/{certification_id}/decide")
async def decide_certification(
    certification_id: UUID,
    payload: CertificationDecision,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("process.certifications.certify")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.decide_certification(
            session, principal.user.id, certification_id, payload.decision, payload.reason
        ),
        request,
    )


SECTION_PERMISSIONS = {
    "definitions": "process.definitions.read",
    "state-machines": "process.state_machines.read",
    "instances": "process.instances.read",
    "sagas": "process.sagas.read",
    "timeouts": "process.timeouts.read",
    "cancellations": "process.cancellations.read",
    "compensations": "process.compensations.read",
    "stuck": "process.stuck.read",
    "interventions": "process.interventions.read",
    "simulations": "process.simulations.read",
    "certifications": "process.certifications.read",
    "release": "process.release.read",
}


@router.get("/{section}")
async def section(
    section: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission = SECTION_PERMISSIONS.get(section)
    if not permission:
        principal.require("process.definitions.read")
    else:
        principal.require(permission)
    return _ok(await service.list_section(session, section), request)
