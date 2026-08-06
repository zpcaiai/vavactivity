"""Member and internal Trust & Safety APIs."""

# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.trust_safety import service
from vav.modules.trust_safety.schemas import (
    AppealCreateRequest,
    BlockCreateRequest,
    DecisionRequest,
    ModerationCreateRequest,
    ReportCreateRequest,
    UserEvidenceUploadRequest,
)

router = APIRouter()


@router.post("/safety/reports")
async def submit_report(
    payload: ReportCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_report(session, reporter=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.get("/account/safety/reports")
async def my_reports(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_reports(session, principal.user.id), request_id_from_request(request)
    )


@router.get("/account/safety/reports/{report_id}")
async def my_report(
    report_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_report(session, principal.user.id, report_id),
        request_id_from_request(request),
    )


@router.post("/account/safety/reports/{report_id}/withdraw")
async def withdraw_report(
    report_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.withdraw_report(session, principal.user.id, report_id),
        request_id_from_request(request),
    )


@router.post("/account/safety/reports/{report_id}/evidence")
async def upload_report_evidence(
    report_id: UUID,
    payload: UserEvidenceUploadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upload_report_evidence(
            session, reporter=principal.user.id, report_id=report_id, payload=payload
        ),
        request_id_from_request(request),
    )


@router.post("/safety/blocks/{user_id}")
async def block_user(
    user_id: UUID,
    payload: BlockCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_block(
            session,
            blocker=principal.user.id,
            blocked=user_id,
            reason_code=payload.reason_code,
            private_reason=payload.private_reason,
        ),
        request_id_from_request(request),
    )


@router.delete("/safety/blocks/{user_id}")
async def unblock_user(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.lift_block(session, blocker=principal.user.id, blocked=user_id),
        request_id_from_request(request),
    )


@router.get("/account/safety/blocks")
async def my_blocks(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_blocks(session, principal.user.id), request_id_from_request(request)
    )


@router.get("/account/safety/restrictions")
async def my_restrictions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.restriction_summary(session, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/account/safety/appeals")
async def submit_appeal(
    payload: AppealCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_appeal(session, appellant=principal.user.id, payload=payload),
        request_id_from_request(request),
    )


@router.get("/account/safety/appeals")
async def my_appeals(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_appeals(session, principal.user.id), request_id_from_request(request)
    )


@router.post("/internal/trust-safety/decisions/{decision_context}")
async def safety_decision(
    decision_context: str,
    payload: DecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if principal.user.id != payload.subject_user_id:
        raise VavError(
            "SAFETY_SUBJECT_MISMATCH",
            "A member may request only their own safety decision.",
            status_code=403,
        )
    return success(
        await service.decide(
            session,
            decision_context=decision_context,
            subject_user_id=payload.subject_user_id,
            counterpart_user_id=payload.counterpart_user_id,
            target_type=payload.target_type,
            target_reference_id=payload.target_reference_id,
            context=payload.context,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/trust-safety/moderation-tasks")
async def moderation_task(
    payload: ModerationCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_moderation_task(session, payload=payload),
        request_id_from_request(request),
    )
