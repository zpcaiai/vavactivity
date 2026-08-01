# ruff: noqa: B008
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.models.ai_assistant import (
    AiConversation,
    AiEvaluationRun,
    AiHumanReferral,
    AiMessage,
    AiModelProfile,
    AiModelRoute,
    AiPromptDefinition,
    AiPromptRelease,
    AiToolDefinition,
)
from vav.modules.ai_assistant.crypto import decrypt_ai_data, encrypt_ai_data
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission

router = APIRouter()


class SensitiveConversationRequest(BaseModel):
    access_reason: str = Field(min_length=8, max_length=500)


class ReferralActionRequest(BaseModel):
    action: Literal["assign", "acknowledge", "resolve"]
    assigned_to: UUID | None = None
    resolution: str | None = Field(default=None, max_length=4000)


class RegistryStatusRequest(BaseModel):
    status: Literal["active", "disabled"]


@router.get("/admin/ai/conversations")
async def list_conversations(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.conversations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(AiConversation).order_by(AiConversation.created_at.desc()).limit(200)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "conversation_number": item.conversation_number,
                    "user_anonymous_id": f"user-{str(item.user_id)[:8]}",
                    "status": item.status,
                    "locale": item.locale,
                    "primary_topic": item.primary_topic,
                    "risk_level": item.latest_risk_level,
                    "last_message_at": item.last_message_at,
                    "created_at": item.created_at,
                }
                for item in values
            ],
            "content_redacted": True,
        },
        request_id_from_request(request),
    )


@router.post("/admin/ai/conversations/{conversation_id}/sensitive-view")
async def sensitive_conversation(
    conversation_id: UUID,
    payload: SensitiveConversationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("ai.conversations.sensitive.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    conversation = await session.get(AiConversation, conversation_id)
    if conversation is None:
        raise VavError(
            "AI_CONVERSATION_NOT_FOUND", "AI conversation was not found.", status_code=404
        )
    messages = list(
        (
            await session.scalars(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.turn_number, AiMessage.created_at)
            )
        ).all()
    )
    await session.execute(
        text(
            "INSERT INTO ai_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('sensitive_conversation_viewed',:actor,'conversation',"
            ":subject,:reason,:details)"
        ),
        {
            "actor": principal.user.id,
            "subject": conversation_id,
            "reason": payload.access_reason,
            "details": encrypt_ai_data({"message_count": len(messages)}),
        },
    )
    await session.commit()
    return success(
        {
            "id": str(conversation.id),
            "conversation_number": conversation.conversation_number,
            "messages": [
                {
                    "id": str(item.id),
                    "turn_number": item.turn_number,
                    "role": item.role,
                    "message_type": item.message_type,
                    "content": decrypt_ai_data(item.content_encrypted).get("content"),
                    "created_at": item.created_at,
                }
                for item in messages
            ],
            "access_audited": True,
        },
        request_id_from_request(request),
    )


@router.get("/admin/ai/referrals")
async def list_referrals(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.referrals.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(AiHumanReferral).order_by(AiHumanReferral.created_at.desc()).limit(200)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "referral_number": item.referral_number,
                    "priority": item.priority,
                    "risk_category": item.risk_category,
                    "risk_level": item.risk_level,
                    "status": item.status,
                    "assigned_team": item.assigned_team,
                    "assigned_to": str(item.assigned_to) if item.assigned_to else None,
                    "created_at": item.created_at,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/ai/referrals/{referral_id}/actions")
async def referral_action(
    referral_id: UUID,
    payload: ReferralActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(AiHumanReferral, referral_id, with_for_update=True)
    if value is None:
        raise VavError("AI_REFERRAL_NOT_FOUND", "AI referral was not found.", status_code=404)
    now = datetime.now(UTC)
    if payload.action == "assign":
        principal.require("ai.referrals.assign")
        if payload.assigned_to is None:
            raise VavError(
                "AI_REFERRAL_ASSIGNEE_REQUIRED", "An assignee is required.", status_code=422
            )
        value.assigned_to = payload.assigned_to
        value.assigned_at = now
        value.status = "assigned"
    elif payload.action == "acknowledge":
        principal.require("ai.referrals.assign")
        value.acknowledged_at = now
        value.status = "acknowledged"
    else:
        principal.require("ai.referrals.resolve")
        value.resolved_at = now
        value.status = "resolved"
        value.resolution_encrypted = encrypt_ai_data({"resolution": payload.resolution})
    await session.execute(
        text(
            "INSERT INTO ai_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES (:event,:actor,'referral',:subject,:reason,:details)"
        ),
        {
            "event": f"referral_{payload.action}",
            "actor": principal.user.id,
            "subject": value.id,
            "reason": payload.action,
            "details": encrypt_ai_data({"assigned_to": str(payload.assigned_to)}),
        },
    )
    await session.commit()
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.get("/admin/ai/prompts")
async def list_prompts(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.prompts.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(AiPromptDefinition, AiPromptRelease)
            .join(AiPromptRelease, AiPromptRelease.prompt_definition_id == AiPromptDefinition.id)
            .order_by(AiPromptDefinition.prompt_code, AiPromptRelease.created_at.desc())
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "definition_id": str(definition.id),
                    "release_id": str(release.id),
                    "prompt_code": definition.prompt_code,
                    "purpose": definition.purpose,
                    "semantic_version": release.semantic_version,
                    "locale": release.locale,
                    "status": release.status,
                    "safety_policy_version": release.safety_policy_version,
                    "tool_registry_version": release.tool_registry_version,
                    "checksum_sha256": release.checksum_sha256,
                }
                for definition, release in rows
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/ai/prompts/{release_id}/activate")
async def activate_prompt(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("ai.prompts.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(AiPromptRelease, release_id, with_for_update=True)
    if value is None:
        raise VavError(
            "AI_PROMPT_RELEASE_NOT_FOUND", "Prompt release was not found.", status_code=404
        )
    await session.execute(
        text(
            "UPDATE ai_prompt_releases SET status='superseded' "
            "WHERE prompt_definition_id=:definition AND locale IS NOT DISTINCT FROM :locale "
            "AND status='active' AND id<>:release"
        ),
        {"definition": value.prompt_definition_id, "locale": value.locale, "release": value.id},
    )
    value.status = "active"
    value.approved_by = principal.user.id
    value.approved_at = datetime.now(UTC)
    await session.commit()
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.get("/admin/ai/models")
async def list_models(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.models.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    profiles = list((await session.scalars(select(AiModelProfile))).all())
    routes = list((await session.scalars(select(AiModelRoute))).all())
    return success(
        {
            "profiles": [
                {
                    "id": str(item.id),
                    "profile_code": item.profile_code,
                    "provider": item.provider,
                    "model_name": item.model_name,
                    "model_revision": item.model_revision,
                    "task_type": item.task_type,
                    "status": item.status,
                }
                for item in profiles
            ],
            "routes": [
                {
                    "id": str(item.id),
                    "route_code": item.route_code,
                    "task_type": item.task_type,
                    "primary_model_profile_id": str(item.primary_model_profile_id),
                    "status": item.status,
                }
                for item in routes
            ],
        },
        request_id_from_request(request),
    )


@router.get("/admin/ai/tools")
async def list_tools(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.tools.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (await session.scalars(select(AiToolDefinition).order_by(AiToolDefinition.tool_code))).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "tool_code": item.tool_code,
                    "semantic_version": item.semantic_version,
                    "risk_level": item.risk_level,
                    "confirmation_required": item.user_confirmation_required,
                    "timeout_seconds": item.timeout_seconds,
                    "status": item.status,
                }
                for item in values
            ],
            "arbitrary_code_creation_allowed": False,
        },
        request_id_from_request(request),
    )


@router.patch("/admin/ai/tools/{tool_id}")
async def set_tool_status(
    tool_id: UUID,
    payload: RegistryStatusRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.tools.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(AiToolDefinition, tool_id, with_for_update=True)
    if value is None:
        raise VavError("AI_TOOL_NOT_FOUND", "AI tool was not found.", status_code=404)
    value.status = payload.status
    await session.commit()
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.get("/admin/ai/evaluation-runs")
async def list_evaluation_runs(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.evaluations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(AiEvaluationRun).order_by(AiEvaluationRun.started_at.desc()).limit(100)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "dataset_id": str(item.dataset_id),
                    "graph_version": item.graph_version,
                    "status": item.status,
                    "metrics": item.metrics,
                    "serious_failures": item.serious_failures,
                    "started_at": item.started_at,
                    "completed_at": item.completed_at,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/ai/feedback")
async def list_feedback(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.feedback.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,message_id,rating,reported,status,created_at "
                "FROM ai_message_feedback ORDER BY created_at DESC LIMIT 200"
            )
        )
    ).mappings()
    return success(
        {
            "items": [
                {
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in row.items()
                }
                for row in rows
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/ai/audit")
async def list_ai_audit(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("ai.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,event_type,actor_id,subject_type,subject_id,reason,created_at "
                "FROM ai_audit_events ORDER BY created_at DESC LIMIT 200"
            )
        )
    ).mappings()
    return success(
        {
            "items": [
                {
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in row.items()
                }
                for row in rows
            ]
        },
        request_id_from_request(request),
    )
