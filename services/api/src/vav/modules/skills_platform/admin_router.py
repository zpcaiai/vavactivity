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
from vav.modules.skills_platform import service
from vav.modules.skills_platform.schemas import (
    CreateInstallationRequest,
    InstallationReasonRequest,
    InstallPlanRequest,
    MarketplaceListingRequest,
    ReviewDecisionRequest,
    UpgradeInstallationRequest,
)

router = APIRouter(prefix="/admin")


@router.post("/skill-installations/plans")
async def install_plan(
    payload: InstallPlanRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.plan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_install_plan(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/skill-installations")
async def install(
    payload: CreateInstallationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.install")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_installation(
            session,
            principal.user.id,
            payload.plan_id,
            payload.expected_plan_checksum,
            payload.configuration,
        ),
        request_id_from_request(request),
    )


@router.get("/skill-installations")
async def installations(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_installations(session), request_id_from_request(request))


@router.get("/skill-installations/{installation_id}")
async def installation(
    installation_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.installation_detail(session, installation_id),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/approve")
async def approve(
    installation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.approve_installation(session, installation_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/activate")
async def activate(
    installation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("skills.installations.activate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.activate_installation(session, installation_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/disable")
async def disable(
    installation_id: UUID,
    payload: InstallationReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.disable")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.transition_installation(
            session, installation_id, principal.user.id, "disable", payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/upgrade")
async def upgrade(
    installation_id: UUID,
    payload: UpgradeInstallationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.installations.upgrade")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upgrade_installation(session, installation_id, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/rollback")
async def rollback(
    installation_id: UUID,
    payload: InstallationReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("skills.installations.rollback")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.rollback_installation(
            session, installation_id, principal.user.id, payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.post("/skill-installations/{installation_id}/uninstall")
async def uninstall(
    installation_id: UUID,
    payload: InstallationReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("skills.installations.uninstall")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.transition_installation(
            session, installation_id, principal.user.id, "uninstall", payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.get("/skill-executions")
async def executions(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("skills.executions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_executions(session), request_id_from_request(request))


@router.get("/skill-executions/{execution_id}")
async def execution(
    execution_id: UUID,
    request: Request,
    include_sensitive: bool = False,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.executions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if include_sensitive:
        principal.require("skills.executions.sensitive.read")
    return success(
        await service.execution_detail(session, execution_id, include_sensitive=include_sensitive),
        request_id_from_request(request),
    )


@router.post("/skill-executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.executions.cancel")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.cancel_execution(session, execution_id, principal.user.id),
        request_id_from_request(request),
    )


@router.get("/skills/marketplace")
async def marketplace(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("skills.marketplace.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_marketplace(session), request_id_from_request(request))


@router.post("/skills/marketplace")
async def submit_marketplace(
    payload: MarketplaceListingRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.marketplace.submit")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.submit_listing(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/skills/marketplace/{listing_id}/review")
async def review_marketplace(
    listing_id: UUID,
    payload: ReviewDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.marketplace.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_listing(session, listing_id, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.post("/skills/marketplace/{listing_id}/publish")
async def publish_marketplace(
    listing_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.marketplace.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_listing(session, listing_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/skills/marketplace/{listing_id}/suspend")
async def suspend_marketplace(
    listing_id: UUID,
    payload: InstallationReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.marketplace.suspend")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.suspend_listing(session, listing_id, principal.user.id, payload.reason_code),
        request_id_from_request(request),
    )
