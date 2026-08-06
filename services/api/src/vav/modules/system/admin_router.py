# ruff: noqa: B008

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.deployment_config import (
    configuration_fingerprint,
    diff_configuration,
    load_deployment_configuration,
)
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.system import service
from vav.modules.system.schemas import (
    BackupRecordRequest,
    CapacityBaselineRecordRequest,
    DeploymentEvidenceRequest,
    FeatureFlagCreateRequest,
    FeatureFlagUpdateRequest,
    MaintenanceChangeRequest,
    OperationalReasonRequest,
    ReleaseRecordCreateRequest,
    RestoreDrillRecordRequest,
)

router = APIRouter(prefix="/admin/system")
ROOT = Path(__file__).resolve().parents[6]


@router.get("/status")
async def status(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("system.status.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.system_status(session, get_settings().environment),
        request_id_from_request(request),
    )


def _list_route(section: str, permission: str) -> Any:
    async def route(
        request: Request,
        _principal: AuthenticatedPrincipal = Depends(require_permission(permission)),
        session: AsyncSession = Depends(get_database_session),
    ) -> dict[str, Any]:
        return success(await service.list_rows(session, section), request_id_from_request(request))

    return route


for _section, _permission in {
    "releases": "system.releases.read",
    "jobs": "system.jobs.read",
    "feature-flags": "system.feature_flags.read",
    "maintenance": "system.maintenance.read",
    "backups": "system.backups.read",
    "restore-drills": "system.restore_drills.read",
    "capacity-baselines": "system.capacity.read",
}.items():
    router.add_api_route(
        f"/{_section}",
        _list_route(_section, _permission),
        methods=["GET"],
        name=f"list-system-{_section}",
    )


@router.get("/integrations")
async def integrations(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("system.status.read")),
) -> dict[str, Any]:
    settings = get_settings()
    providers = [
        {"code": "payment", "configured": not settings.payment_test_fake_enabled},
        {
            "code": "email",
            "configured": settings.notification_email_provider not in {"fake", "mailpit"},
        },
        {"code": "ai", "configured": settings.ai_model_provider != "deterministic_local"},
        {"code": "object_storage", "configured": bool(settings.media_s3_endpoint)},
    ]
    return success(providers, request_id_from_request(request))


@router.get("/dead-letters")
async def dead_letters(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("system.dead_letters.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,source_type,source_id,error_code,status,created_at "
                "FROM notification_dead_letters ORDER BY created_at DESC LIMIT 200"
            )
        )
    ).mappings()
    return success([dict(row) for row in rows], request_id_from_request(request))


@router.post("/feature-flags")
async def create_flag(
    payload: FeatureFlagCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.feature_flags.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_feature_flag(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.patch("/feature-flags/{flag_id}")
async def update_flag(
    flag_id: UUID,
    payload: FeatureFlagUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.feature_flags.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.update_feature_flag(session, flag_id, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/feature-flags/{flag_id}/approve")
async def approve_flag(
    flag_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.feature_flags.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_feature_flag(session, flag_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/feature-flags/{flag_id}/activate")
async def activate_flag(
    flag_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.feature_flags.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.activate_feature_flag(session, flag_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/releases")
async def create_release(
    payload: ReleaseRecordCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.deploy")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_release_record(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/releases/{release_id}/approve")
async def approve_release(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_release(session, release_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/releases/{release_id}/deploy/{environment}")
async def record_release_deployment(
    release_id: UUID,
    environment: str,
    payload: DeploymentEvidenceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.deploy")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_release_deployment(
            session,
            release_id=release_id,
            actor_id=principal.user.id,
            environment=environment,
            payload=payload,
        ),
        request_id_from_request(request),
    )


@router.post("/releases/{release_id}/rollback")
async def rollback_release(
    release_id: UUID,
    payload: OperationalReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.rollback")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.rollback_release(session, release_id, principal.user.id, payload.reason_code),
        request_id_from_request(request),
    )


@router.post("/jobs/{job_id}/{operation}")
async def transition_job(
    job_id: UUID,
    operation: str,
    payload: OperationalReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.jobs.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    required = "system.jobs.cancel" if operation == "cancel" else "system.jobs.retry"
    principal.require(required)
    return success(
        await service.transition_backfill(
            session, job_id, principal.user.id, operation, payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.post("/dead-letters/{dead_letter_id}/replay")
async def replay_dead_letter(
    dead_letter_id: UUID,
    payload: OperationalReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.dead_letters.replay")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.replay_dead_letter(
            session, dead_letter_id, principal.user.id, payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.get("/configuration")
async def configuration(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("system.configuration.read")),
) -> dict[str, Any]:
    environment = get_settings().environment
    config = load_deployment_configuration(ROOT / f"config/env/{environment}.yaml")
    return success(configuration_fingerprint(config), request_id_from_request(request))


@router.get("/configuration/diff/{target_environment}")
async def configuration_diff(
    target_environment: str,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("system.configuration.diff")),
) -> dict[str, Any]:
    allowed = {"development", "test", "ci", "staging", "production", "dr"}
    if target_environment not in allowed:
        raise VavError("SYSTEM_ENVIRONMENT_INVALID", "Unknown environment.", status_code=404)
    current = load_deployment_configuration(ROOT / f"config/env/{get_settings().environment}.yaml")
    target = load_deployment_configuration(ROOT / f"config/env/{target_environment}.yaml")
    return success(diff_configuration(current, target), request_id_from_request(request))


@router.post("/backups")
async def record_backup(
    payload: BackupRecordRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.deploy")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_backup(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/restore-drills")
async def record_restore_drill(
    payload: RestoreDrillRecordRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.deploy")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_restore_drill(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/capacity-baselines")
async def record_capacity_baseline(
    payload: CapacityBaselineRecordRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.releases.deploy")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_capacity_baseline(session, principal.user.id, payload),
        request_id_from_request(request),
    )


async def _maintenance(
    enabled: bool,
    payload: MaintenanceChangeRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    return success(
        await service.set_maintenance(
            session,
            environment=get_settings().environment,
            enabled=enabled,
            actor_id=principal.user.id,
            payload=payload,
        ),
        request_id_from_request(request),
    )


@router.post("/maintenance/enable")
async def enable_maintenance(
    payload: MaintenanceChangeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.maintenance.enable")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _maintenance(True, payload, request, principal, session)


@router.post("/maintenance/disable")
async def disable_maintenance(
    payload: MaintenanceChangeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("system.maintenance.disable")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _maintenance(False, payload, request, principal, session)
