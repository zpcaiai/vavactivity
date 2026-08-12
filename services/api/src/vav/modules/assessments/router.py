"""Member-facing paid assessment API (B17).

Every route resolves content through the version the member's entitlement names.
There is no "current version" lookup on any member path, which is what stops a
catalogue update from changing what somebody already paid for.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.assessments import service
from vav.modules.assessments.schemas import (
    AttemptAnswersRequest,
    PurchaseRequest,
    RefundRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


@router.get("/assessments/catalogue")
async def catalogue(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Published versions of active products only; drafts are invisible."""

    service.enabled()
    return success(
        {"items": await service.list_catalogue(session)},
        request_id_from_request(request),
    )


@router.post("/assessments/purchases")
async def purchase(
    payload: PurchaseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.purchase(session, user_id=principal.user.id, payload=payload.model_dump()),
        request_id_from_request(request),
    )


@router.post("/assessments/purchases/{purchase_id}/refund")
async def refund(
    purchase_id: UUID,
    payload: RefundRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Self-service refund, time-boxed and refused once a report was delivered."""

    return success(
        await service.refund_purchase(
            session,
            purchase_id=purchase_id,
            actor_id=principal.user.id,
            actor_kind="member",
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/assessments/entitlements")
async def entitlements(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_my_entitlements(session, principal.user.id)},
        request_id_from_request(request),
    )


@router.post("/assessments/entitlements/{entitlement_id}/attempts")
async def start_attempt(
    entitlement_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.start_attempt(
            session, entitlement_id=entitlement_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.get("/assessments/attempts/{attempt_id}")
async def attempt(
    attempt_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_attempt(session, attempt_id=attempt_id, user_id=principal.user.id),
        request_id_from_request(request),
    )


@router.put("/assessments/attempts/{attempt_id}/answers")
async def save_answers(
    attempt_id: UUID,
    payload: AttemptAnswersRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.save_attempt_answers(
            session,
            attempt_id=attempt_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/assessments/attempts/{attempt_id}/report")
async def report(
    attempt_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_report(session, attempt_id=attempt_id, user_id=principal.user.id),
        request_id_from_request(request),
    )
