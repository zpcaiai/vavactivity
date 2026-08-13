"""Member-facing AI assistance API (B19 part 1).

Every response from this router carries an ``ai_limitation`` block, including
refusals. There is no route that can return model text without one, because
the payload constructor in the domain layer requires the label.
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
from vav.modules.ai_hardening import service
from vav.modules.ai_hardening.schemas import AiTurnRequest, EscalationRequestPayload
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


@router.post("/ai/conversations/{conversation_id}/turns")
async def create_turn(
    conversation_id: UUID,
    payload: AiTurnRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Send one message.

    Returns 200 with either an answer or an explicit ``refusal_code``. A
    provider outage, a budget breach and a policy block are all refusals with a
    machine code - never a fabricated answer, and never a bare 5xx.
    """

    return success(
        await service.run_turn(
            session,
            user_id=principal.user.id,
            conversation_id=conversation_id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/ai/budget")
async def my_budget(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_budget(session, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/ai/conversations/{conversation_id}/escalations")
async def request_human(
    conversation_id: UUID,
    payload: EscalationRequestPayload,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Ask for a person. Always honoured; never routed back into the model."""

    return success(
        await service.request_human(
            session,
            user_id=principal.user.id,
            conversation_id=conversation_id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )
