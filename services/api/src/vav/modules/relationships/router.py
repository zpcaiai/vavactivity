"""Member relationship journey API.

There is intentionally no admin-compatible decision endpoint: only one of the
two participants can propose/accept a stage or request/accept a resume.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.relationships import service
from vav.modules.relationships.schemas import (
    ActionItemRequest,
    CheckinRequest,
    EndingRequest,
    MilestoneRequest,
    MilestoneUpdateRequest,
    PauseRequest,
    ProposalDecisionRequest,
    ReflectionRequest,
    ReminderPlanRequest,
    ResumeRequest,
    StageProposalRequest,
)

router = APIRouter(prefix="/account")


def _key(value: str | None) -> str:
    return value.strip()[:128] if value and value.strip() else str(uuid4())


@router.get("/relationships")
async def journeys(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_journeys(session, principal.user.id), request_id_from_request(request)
    )


@router.get("/relationships/{journey_id}")
async def journey(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_journey(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/stage-proposals")
async def propose_stage(
    journey_id: UUID,
    payload: StageProposalRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await service.create_stage_proposal(
        session,
        journey_id=journey_id,
        actor_id=principal.user.id,
        to_stage=payload.to_stage_code,
        message=payload.message,
        idempotency_key=_key(idempotency_key),
    )
    return success(result, request_id_from_request(request))


@router.get("/relationships/{journey_id}/stage-proposals")
async def proposals(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_stage_proposals(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationship-stage-proposals/{proposal_id}/accept")
async def accept_stage(
    proposal_id: UUID,
    payload: ProposalDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_stage_proposal(
            session,
            proposal_id=proposal_id,
            actor_id=principal.user.id,
            accept=True,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-stage-proposals/{proposal_id}/decline")
async def decline_stage(
    proposal_id: UUID,
    payload: ProposalDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_stage_proposal(
            session,
            proposal_id=proposal_id,
            actor_id=principal.user.id,
            accept=False,
            expected_version=payload.expected_version,
            reason_code=payload.reason_code,
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-stage-proposals/{proposal_id}/cancel")
async def cancel_stage(
    proposal_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.cancel_stage_proposal(
            session, proposal_id=proposal_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/pause")
async def pause(
    journey_id: UUID,
    payload: PauseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.pause(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            private_reason=payload.private_reason,
            visible_message=payload.visible_message,
        ),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/resume-request")
async def resume_request(
    journey_id: UUID,
    _payload: ResumeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.request_resume(session, journey_id=journey_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationship-pauses/{pause_id}/accept-resume")
async def accept_resume(
    pause_id: UUID,
    payload: ResumeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_resume(
            session,
            pause_id=pause_id,
            actor_id=principal.user.id,
            accept=True,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-pauses/{pause_id}/decline-resume")
async def decline_resume(
    pause_id: UUID,
    payload: ResumeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_resume(
            session,
            pause_id=pause_id,
            actor_id=principal.user.id,
            accept=False,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/end")
async def end(
    journey_id: UUID,
    payload: EndingRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.end_journey(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            confirmed=payload.confirmed,
            reason_code=payload.reason_code,
            private_reason=payload.private_reason,
            visible_message=payload.visible_message,
        ),
        request_id_from_request(request),
    )


@router.get("/relationships/{journey_id}/timeline")
async def timeline(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.timeline(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.get("/relationships/{journey_id}/milestones")
async def milestones(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_milestones(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/milestones")
async def create_milestone(
    journey_id: UUID,
    payload: MilestoneRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_milestone(
            session, journey_id=journey_id, actor_id=principal.user.id, **payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.patch("/relationship-milestones/{milestone_id}")
async def update_milestone(
    milestone_id: UUID,
    payload: MilestoneUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.update_milestone(
            session,
            milestone_id=milestone_id,
            actor_id=principal.user.id,
            values=payload.model_dump(exclude_unset=True),
        ),
        request_id_from_request(request),
    )


@router.delete("/relationship-milestones/{milestone_id}")
async def delete_milestone(
    milestone_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.delete_milestone(
            session, milestone_id=milestone_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/checkins")
async def create_checkin(
    journey_id: UUID,
    payload: CheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_checkin(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            visibility=payload.visibility,
            responses=payload.responses,
        ),
        request_id_from_request(request),
    )


@router.get("/relationships/{journey_id}/reflections")
async def reflections(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_reflections(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/reflections")
async def create_reflection(
    journey_id: UUID,
    payload: ReflectionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_reflection(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            reflection=payload.reflection,
            ai_processing_consent_id=payload.ai_processing_consent_id,
        ),
        request_id_from_request(request),
    )


@router.get("/relationships/{journey_id}/action-items")
async def action_items(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_action_items(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/action-items")
async def create_action_item(
    journey_id: UUID,
    payload: ActionItemRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_action_item(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            assigned_to_user_id=payload.assigned_to_user_id,
            title=payload.title,
            details=payload.details,
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-action-items/{action_item_id}/accept")
async def accept_action_item(
    action_item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_action_item(
            session, action_item_id=action_item_id, actor_id=principal.user.id, accept=True
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-action-items/{action_item_id}/decline")
async def decline_action_item(
    action_item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_action_item(
            session, action_item_id=action_item_id, actor_id=principal.user.id, accept=False
        ),
        request_id_from_request(request),
    )


@router.post("/relationship-action-items/{action_item_id}/complete")
async def complete_action_item(
    action_item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.complete_action_item(
            session, action_item_id=action_item_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.get("/relationships/{journey_id}/reminders")
async def reminder_plans(
    journey_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_reminder_plans(session, journey_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/relationships/{journey_id}/reminders")
async def create_reminder_plan(
    journey_id: UUID,
    payload: ReminderPlanRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_reminder_plan(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            reminder_type=payload.reminder_type,
            cadence_days=payload.cadence_days,
            opted_in=payload.opted_in,
        ),
        request_id_from_request(request),
    )


@router.delete("/relationship-reminders/{reminder_plan_id}")
async def cancel_reminder_plan(
    reminder_plan_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.cancel_reminder_plan(
            session, reminder_plan_id=reminder_plan_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )
