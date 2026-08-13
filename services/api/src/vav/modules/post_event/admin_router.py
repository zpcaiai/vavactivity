"""Administrative post-event closure API.

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.
"""

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
from vav.modules.post_event import service
from vav.modules.post_event.schemas import (
    ExcludeCandidateRequest,
    FreezeCandidatesRequest,
    LetterGenerateRequest,
    LetterPublishRequest,
    LetterReviewRequest,
    LetterRevokeRequest,
    LetterTemplateRequest,
    PassReasonOptionRequest,
    RestoreCandidateRequest,
    SelectionPolicyRequest,
    SurveyAssignmentRequest,
    SurveyDefinitionRequest,
    SurveyReopenRequest,
)

router = APIRouter(prefix="/admin")


# --- B09 candidate freeze ---------------------------------------------------


@router.put("/activities/{activity_id}/selection-policy")
async def set_selection_policy(
    activity_id: UUID,
    payload: SelectionPolicyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.selection_policy.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_selection_policy(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.put("/activities/{activity_id}/pass-reasons")
async def set_pass_reason(
    activity_id: UUID,
    payload: PassReasonOptionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.selection_policy.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_pass_reason(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/pass-reasons")
async def list_pass_reasons(
    activity_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.selection_policy.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_pass_reasons(session, activity_id)},
        request_id_from_request(request),
    )


@router.post("/activities/{activity_id}/candidate-snapshots")
async def freeze_candidates(
    activity_id: UUID,
    payload: FreezeCandidatesRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.candidates.freeze")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.freeze_candidates(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/candidate-snapshots/{snapshot_id}")
async def snapshot_detail(
    snapshot_id: UUID,
    request: Request,
    include_excluded: bool = Query(default=True),
    _principal: AuthenticatedPrincipal = Depends(require_permission("activities.post_event.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    snapshot = await service.get_snapshot(session, snapshot_id)
    entries = await service.list_snapshot_entries(
        session, snapshot_id, include_excluded=include_excluded
    )
    return success({**snapshot, "entries": entries}, request_id_from_request(request))


@router.post("/candidate-snapshots/{snapshot_id}/exclusions")
async def exclude_candidate(
    snapshot_id: UUID,
    payload: ExcludeCandidateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.candidates.exclude")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.exclude_candidate(
            session,
            snapshot_id=snapshot_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/candidate-snapshots/{snapshot_id}/restorations")
async def restore_candidate(
    snapshot_id: UUID,
    payload: RestoreCandidateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.candidates.exclude")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.restore_candidate(
            session,
            snapshot_id=snapshot_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/candidate-snapshots/{snapshot_id}/matches")
async def snapshot_matches(
    snapshot_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.post_event.sensitive.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    pairs = await service.compute_matches(session, snapshot_id)
    return success(
        {"pairs": [[str(first), str(second)] for first, second in pairs], "count": len(pairs)},
        request_id_from_request(request),
    )


# --- B10 survey -------------------------------------------------------------


@router.post("/surveys/definitions")
async def create_survey_definition(
    payload: SurveyDefinitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("surveys.definitions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_survey_definition(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/surveys/definitions/{definition_id}")
async def survey_definition(
    definition_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("surveys.definitions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_survey_definition(session, definition_id),
        request_id_from_request(request),
    )


@router.post("/surveys/definitions/{definition_id}/publish")
async def publish_survey_definition(
    definition_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("surveys.definitions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_survey_definition(
            session, definition_id=definition_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/activities/{activity_id}/survey-assignments")
async def assign_survey(
    activity_id: UUID,
    payload: SurveyAssignmentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("surveys.assignments.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.assign_survey(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/survey-assignments/{assignment_id}/tasks")
async def regenerate_survey_tasks(
    assignment_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("surveys.assignments.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    created = await service.generate_survey_tasks(session, assignment_id=assignment_id)
    return success({"created": created}, request_id_from_request(request))


@router.post("/survey-assignments/{assignment_id}/reminders")
async def schedule_reminders(
    assignment_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("surveys.assignments.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    scheduled = await service.schedule_survey_reminders(session, assignment_id)
    return success({"scheduled": scheduled}, request_id_from_request(request))


@router.get("/survey-assignments/{assignment_id}/aggregate")
async def survey_aggregate(
    assignment_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("surveys.responses.read_aggregate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.survey_aggregate(session, assignment_id),
        request_id_from_request(request),
    )


@router.post("/survey-assignments/{assignment_id}/responses/{user_id}/reopen")
async def reopen_response(
    assignment_id: UUID,
    user_id: UUID,
    payload: SurveyReopenRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("surveys.responses.override")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.reopen_survey_response(
            session,
            assignment_id=assignment_id,
            user_id=user_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- B11 result letters -----------------------------------------------------


@router.put("/result-letters/templates")
async def upsert_template(
    payload: LetterTemplateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.generate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_letter_template(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/result-letters/templates/{template_id}/publish")
async def publish_template(
    template_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_letter_template(
            session, template_id=template_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/activities/{activity_id}/result-letters")
async def generate_letters(
    activity_id: UUID,
    payload: LetterGenerateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.generate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.generate_letters(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/result-letters")
async def list_letters(
    activity_id: UUID,
    request: Request,
    status: str | None = Query(default=None),
    _principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {
            "items": await service.list_letters_for_review(
                session, activity_id=activity_id, status=status
            )
        },
        request_id_from_request(request),
    )


@router.get("/result-letters/{letter_id}")
async def letter_detail(
    letter_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_letter_for_review(session, letter_id),
        request_id_from_request(request),
    )


@router.post("/result-letters/{letter_id}/submit")
async def submit_for_review(
    letter_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.generate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.submit_letter_for_review(
            session, letter_id=letter_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.post("/result-letters/{letter_id}/review")
async def review_letter(
    letter_id: UUID,
    payload: LetterReviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.review_letter(
            session,
            letter_id=letter_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/result-letters/{letter_id}/publish")
async def publish_letter(
    letter_id: UUID,
    payload: LetterPublishRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_letter(
            session,
            letter_id=letter_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/result-letters/{letter_id}/revoke")
async def revoke_letter(
    letter_id: UUID,
    payload: LetterRevokeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("result_letters.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.revoke_letter(
            session,
            letter_id=letter_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )
