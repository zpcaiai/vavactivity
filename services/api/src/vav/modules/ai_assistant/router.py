# ruff: noqa: B008
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.models.ai_assistant import AiHumanReferral, AiMessage
from vav.modules.ai_assistant.crypto import content_hash, decrypt_ai_data, encrypt_ai_data
from vav.modules.ai_assistant.schemas import (
    CreateConversationRequest,
    ExecuteConfirmedToolRequest,
    FeedbackRequest,
    MemoryConsentRequest,
    SendMessageRequest,
    ToolConfirmationRequest,
)
from vav.modules.ai_assistant.service import (
    conversation_messages,
    create_conversation,
    delete_conversation,
    list_owned_conversations,
    owned_conversation,
    send_message,
    set_memory_consent,
)
from vav.modules.ai_assistant.tooling import (
    TOOL_REGISTRY,
    WRITE_TOOLS,
    execute_confirmed_write_tool,
    validate_arguments,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.identity.service import roles_for_user

router = APIRouter()


def _enabled() -> None:
    if not get_settings().ai_enabled:
        raise VavError("AI_ASSISTANT_DISABLED", "The AI assistant is not enabled.", status_code=503)


@router.post("/ai/conversations", status_code=201)
async def start_conversation(
    payload: CreateConversationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    value = await create_conversation(
        session,
        user_id=principal.user.id,
        locale=payload.locale,
        timezone=payload.user_timezone,
        consent_version=payload.consent_version,
        accept_ai_disclosure=payload.accept_ai_disclosure,
        memory_opt_in=payload.memory_opt_in,
    )
    return success(
        {
            "id": str(value.id),
            "conversation_number": value.conversation_number,
            "status": value.status,
            "locale": value.locale,
            "memory_consent_status": value.memory_consent_status,
            "consent_version": value.consent_version,
        },
        request_id_from_request(request),
    )


@router.get("/ai/conversations")
async def conversations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    values = await list_owned_conversations(session, principal.user.id)
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "conversation_number": item.conversation_number,
                    "status": item.status,
                    "locale": item.locale,
                    "relationship_stage": item.relationship_stage,
                    "primary_topic": item.primary_topic,
                    "latest_risk_level": item.latest_risk_level,
                    "memory_consent_status": item.memory_consent_status,
                    "last_message_at": item.last_message_at,
                    "created_at": item.created_at,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.get("/ai/conversations/{conversation_id}")
async def conversation_detail(
    conversation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    value = await owned_conversation(session, conversation_id, principal.user.id)
    messages = await conversation_messages(session, conversation_id, principal.user.id)
    return success(
        {
            "id": str(value.id),
            "conversation_number": value.conversation_number,
            "status": value.status,
            "locale": value.locale,
            "memory_consent_status": value.memory_consent_status,
            "messages": messages,
        },
        request_id_from_request(request),
    )


@router.post("/ai/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> Any:
    _enabled()
    roles = await roles_for_user(session, principal.user.id)
    result = await send_message(
        session,
        conversation_id=conversation_id,
        user_id=principal.user.id,
        client_message_id=payload.client_message_id,
        content=payload.content,
        locale=payload.locale,
        user_roles=sorted(roles),
    )
    request_id = request_id_from_request(request)
    if "text/event-stream" not in request.headers.get("accept", ""):
        return success(result, request_id)

    async def approved_events() -> Any:
        events: list[tuple[str, dict[str, Any]]] = [
            ("turn.started", {"turn_id": result["turn_id"], "duplicate": result["duplicate"]})
        ]
        if result.get("referral"):
            events.append(("referral.created", result["referral"]))
        for citation in result.get("citations", []):
            events.append(("citation.added", citation))
        events.extend(
            (
                ("response.delta", {"text": result["message"]}),
                (
                    "turn.completed",
                    {
                        "turn_id": result["turn_id"],
                        "message_id": result.get("message_id"),
                        "status": result["status"],
                        "request_id": request_id,
                    },
                ),
            )
        )
        for event, data in events:
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        approved_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.patch("/ai/conversations/{conversation_id}/memory-consent")
async def memory_consent(
    conversation_id: UUID,
    payload: MemoryConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    value = await set_memory_consent(
        session,
        conversation_id=conversation_id,
        user_id=principal.user.id,
        enabled=payload.enabled,
    )
    return success(
        {"id": str(value.id), "memory_consent_status": value.memory_consent_status},
        request_id_from_request(request),
    )


@router.post("/ai/conversations/{conversation_id}/tool-confirmations", status_code=201)
async def create_tool_confirmation(
    conversation_id: UUID,
    payload: ToolConfirmationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    await owned_conversation(session, conversation_id, principal.user.id)
    definition = TOOL_REGISTRY.get(payload.tool_code)
    if definition is None or payload.tool_code not in WRITE_TOOLS:
        raise VavError(
            "AI_WRITE_TOOL_NOT_REGISTERED", "Write tool is not available.", status_code=400
        )
    validated = validate_arguments(
        definition,
        {**payload.arguments, "confirmation_token": "confirmation-preview"},
        current_user_id=principal.user.id,
    )
    canonical_arguments = validated.model_dump(
        mode="json", exclude={"confirmation_token"}, exclude_none=True
    )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    confirmation_id = await session.scalar(
        text(
            "INSERT INTO ai_tool_confirmations "
            "(conversation_id,user_id,tool_code,input_hash,token_hash,status,expires_at,"
            "confirmed_at) VALUES (:conversation,:user,:tool,:input_hash,:token_hash,"
            "'confirmed',:expires,:confirmed) RETURNING id"
        ),
        {
            "conversation": conversation_id,
            "user": principal.user.id,
            "tool": payload.tool_code,
            "input_hash": content_hash(
                json.dumps(canonical_arguments, ensure_ascii=False, sort_keys=True)
            ),
            "token_hash": content_hash(token),
            "expires": expires_at,
            "confirmed": datetime.now(UTC),
        },
    )
    await session.commit()
    return success(
        {
            "id": str(confirmation_id),
            "tool_code": payload.tool_code,
            "confirmation_token": token,
            "expires_at": expires_at,
        },
        request_id_from_request(request),
    )


@router.post("/ai/conversations/{conversation_id}/tools/{tool_code}/execute")
async def execute_confirmed_tool(
    conversation_id: UUID,
    tool_code: str,
    payload: ExecuteConfirmedToolRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    await owned_conversation(session, conversation_id, principal.user.id, lock=True)
    definition = TOOL_REGISTRY.get(tool_code)
    if definition is None or tool_code not in WRITE_TOOLS:
        raise VavError(
            "AI_WRITE_TOOL_NOT_REGISTERED", "Write tool is not available.", status_code=400
        )
    validated = validate_arguments(
        definition,
        {**payload.arguments, "confirmation_token": payload.confirmation_token},
        current_user_id=principal.user.id,
    )
    canonical_arguments = validated.model_dump(
        mode="json", exclude={"confirmation_token"}, exclude_none=True
    )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT output_encrypted,status FROM ai_tool_executions "
                    "WHERE conversation_id=:conversation AND idempotency_key=:key"
                ),
                {"conversation": conversation_id, "key": payload.idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        output = decrypt_ai_data(existing["output_encrypted"]).get("output")
        return success(
            {"status": existing["status"], "output": output, "duplicate": True},
            request_id_from_request(request),
        )
    confirmation = (
        (
            await session.execute(
                text(
                    "SELECT id,input_hash,status,expires_at FROM ai_tool_confirmations "
                    "WHERE conversation_id=:conversation AND user_id=:user AND tool_code=:tool "
                    "AND token_hash=:token FOR UPDATE"
                ),
                {
                    "conversation": conversation_id,
                    "user": principal.user.id,
                    "tool": tool_code,
                    "token": content_hash(payload.confirmation_token),
                },
            )
        )
        .mappings()
        .first()
    )
    expected_hash = content_hash(
        json.dumps(canonical_arguments, ensure_ascii=False, sort_keys=True)
    )
    if (
        confirmation is None
        or confirmation["status"] != "confirmed"
        or confirmation["expires_at"] <= datetime.now(UTC)
        or confirmation["input_hash"] != expected_hash
    ):
        raise VavError(
            "AI_TOOL_CONFIRMATION_INVALID",
            "Tool confirmation is missing, expired, consumed, or does not match the input.",
            status_code=409,
        )
    turn_id = await session.scalar(
        text(
            "SELECT id FROM ai_agent_turns WHERE conversation_id=:conversation "
            "ORDER BY turn_number DESC LIMIT 1"
        ),
        {"conversation": conversation_id},
    )
    if turn_id is None:
        raise VavError(
            "AI_TOOL_TURN_REQUIRED", "A completed conversation turn is required.", status_code=409
        )
    sequence = await session.scalar(
        text(
            "SELECT COALESCE(MAX(call_sequence),0)+1 FROM ai_tool_executions "
            "WHERE agent_turn_id=:turn"
        ),
        {"turn": turn_id},
    )
    output = await execute_confirmed_write_tool(
        session,
        tool_code=tool_code,
        arguments={**canonical_arguments, "confirmation_token": payload.confirmation_token},
        current_user_id=principal.user.id,
        conversation_id=conversation_id,
    )
    await session.execute(
        text(
            "INSERT INTO ai_tool_executions "
            "(conversation_id,agent_turn_id,tool_code,tool_version,call_sequence,input_encrypted,"
            "input_hash,status,confirmation_status,confirmed_by_user_at,output_encrypted,"
            "output_summary,idempotency_key,started_at,completed_at) "
            "VALUES (:conversation,:turn,:tool,:version,:sequence,:input,:input_hash,'completed',"
            "'confirmed',:confirmed,:output,CAST(:summary AS jsonb),:key,:started,:completed)"
        ),
        {
            "conversation": conversation_id,
            "turn": turn_id,
            "tool": tool_code,
            "version": definition.version,
            "sequence": int(sequence or 1),
            "input": encrypt_ai_data({"arguments": canonical_arguments}),
            "input_hash": expected_hash,
            "confirmed": datetime.now(UTC),
            "output": encrypt_ai_data({"output": output}),
            "summary": json.dumps({"status": output.get("status")}),
            "key": payload.idempotency_key,
            "started": datetime.now(UTC),
            "completed": datetime.now(UTC),
        },
    )
    await session.execute(
        text("UPDATE ai_tool_confirmations SET status='consumed',consumed_at=now() WHERE id=:id"),
        {"id": confirmation["id"]},
    )
    await session.commit()
    return success(
        {"status": "completed", "output": output, "duplicate": False},
        request_id_from_request(request),
    )


@router.get("/ai/referrals")
async def user_referrals(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    values = list(
        (
            await session.scalars(
                select(AiHumanReferral)
                .where(AiHumanReferral.user_id == principal.user.id)
                .order_by(AiHumanReferral.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "referral_number": item.referral_number,
                    "referral_type": item.referral_type,
                    "priority": item.priority,
                    "status": item.status,
                    "summary": decrypt_ai_data(item.user_visible_summary_encrypted).get("summary")
                    if item.user_visible_summary_encrypted
                    else None,
                    "created_at": item.created_at,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/ai/messages/{message_id}/feedback")
async def message_feedback(
    message_id: UUID,
    payload: FeedbackRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    message = await session.scalar(select(AiMessage).where(AiMessage.id == message_id))
    if message is None:
        raise VavError("AI_MESSAGE_NOT_FOUND", "AI message was not found.", status_code=404)
    await owned_conversation(session, message.conversation_id, principal.user.id)
    await session.execute(
        text(
            "INSERT INTO ai_message_feedback "
            "(message_id,user_id,rating,reported,reason_encrypted,status) "
            "VALUES (:message,:user,:rating,:reported,:reason,'open') "
            "ON CONFLICT (message_id,user_id) DO UPDATE SET rating=EXCLUDED.rating,"
            "reported=EXCLUDED.reported,reason_encrypted=EXCLUDED.reason_encrypted"
        ),
        {
            "message": message_id,
            "user": principal.user.id,
            "rating": payload.rating,
            "reported": payload.reported,
            "reason": encrypt_ai_data({"reason": payload.reason}) if payload.reason else None,
        },
    )
    await session.commit()
    return success({"message_id": str(message_id), "saved": True}, request_id_from_request(request))


@router.delete("/ai/conversations/{conversation_id}")
async def remove_conversation(
    conversation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    await delete_conversation(session, conversation_id=conversation_id, user_id=principal.user.id)
    return success(
        {"id": str(conversation_id), "status": "deleted"}, request_id_from_request(request)
    )
