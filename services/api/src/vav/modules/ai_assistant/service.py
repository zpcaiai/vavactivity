from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.ai_assistant import (
    AiAgentTurn,
    AiConversation,
    AiGraphCheckpoint,
    AiHumanReferral,
    AiMessage,
    AiModelProfile,
    AiModelRoute,
    AiPromptRelease,
)
from vav.models.system import OutboxEvent
from vav.modules.ai_assistant.crypto import content_hash, decrypt_ai_data, encrypt_ai_data
from vav.modules.ai_assistant.graph import (
    GRAPH_VERSION,
    STATE_SCHEMA_VERSION,
    GraphDependencies,
    build_hanna_graph,
)
from vav.modules.ai_assistant.providers import deterministic_provider
from vav.modules.ai_assistant.schemas import GeneratedAgentResponse, HannaAgentState
from vav.modules.ai_assistant.tooling import registry_version


def _conversation_number() -> str:
    return f"AIC-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}"


def _referral_number() -> str:
    return f"AIR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}"


async def _active_release(session: AsyncSession) -> AiPromptRelease | None:
    return cast(
        AiPromptRelease | None,
        await session.scalar(
            select(AiPromptRelease)
            .where(AiPromptRelease.status == "active")
            .order_by(AiPromptRelease.approved_at.desc().nullslast())
        ),
    )


async def _active_route(session: AsyncSession) -> AiModelRoute | None:
    return cast(
        AiModelRoute | None,
        await session.scalar(
            select(AiModelRoute)
            .where(AiModelRoute.task_type == "response_generation", AiModelRoute.status == "active")
            .order_by(AiModelRoute.updated_at.desc())
        ),
    )


async def create_conversation(
    session: AsyncSession,
    *,
    user_id: UUID,
    locale: str,
    timezone: str,
    consent_version: str,
    accept_ai_disclosure: bool,
    memory_opt_in: bool,
) -> AiConversation:
    if not accept_ai_disclosure:
        raise VavError(
            "AI_CONSENT_REQUIRED",
            "Explicit AI service consent is required before starting a conversation.",
            status_code=422,
        )
    settings = get_settings()
    release = await _active_release(session)
    route = await _active_route(session)
    value = AiConversation(
        conversation_number=_conversation_number(),
        user_id=user_id,
        status="active",
        assistant_profile=settings.ai_agent_profile,
        locale=locale,
        user_timezone=timezone,
        consent_version=consent_version,
        consented_at=datetime.now(UTC),
        memory_consent_status="granted" if memory_opt_in else "not_granted",
        active_graph_version=GRAPH_VERSION,
        active_prompt_release_id=release.id if release else None,
        active_model_route_id=route.id if route else None,
        retention_expires_at=datetime.now(UTC)
        + timedelta(days=settings.ai_conversation_retention_days),
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def owned_conversation(
    session: AsyncSession, conversation_id: UUID, user_id: UUID, *, lock: bool = False
) -> AiConversation:
    query = select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.user_id == user_id,
        AiConversation.deleted_at.is_(None),
    )
    value = await session.scalar(query.with_for_update() if lock else query)
    if value is None:
        raise VavError(
            "AI_CONVERSATION_NOT_FOUND", "AI conversation was not found.", status_code=404
        )
    return value


async def list_owned_conversations(session: AsyncSession, user_id: UUID) -> list[AiConversation]:
    return list(
        (
            await session.scalars(
                select(AiConversation)
                .where(AiConversation.user_id == user_id, AiConversation.deleted_at.is_(None))
                .order_by(
                    AiConversation.last_message_at.desc().nullslast(),
                    AiConversation.created_at.desc(),
                )
            )
        ).all()
    )


async def conversation_messages(
    session: AsyncSession, conversation_id: UUID, user_id: UUID
) -> list[dict[str, Any]]:
    await owned_conversation(session, conversation_id, user_id)
    values = list(
        (
            await session.scalars(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.turn_number, AiMessage.created_at)
            )
        ).all()
    )
    return [
        {
            "id": str(item.id),
            "turn_number": item.turn_number,
            "role": item.role,
            "message_type": item.message_type,
            "content": decrypt_ai_data(item.content_encrypted)["content"],
            "status": item.status,
            "created_at": item.created_at.isoformat(),
        }
        for item in values
    ]


async def _checkpoint(
    session: AsyncSession,
    *,
    conversation: AiConversation,
    turn: AiAgentTurn,
    node_name: str,
    sequence: int,
    state: dict[str, Any],
) -> AiGraphCheckpoint:
    serialized = state
    canonical_state = json.dumps(serialized, ensure_ascii=False, sort_keys=True, default=str)
    state_hash = hashlib.sha256(canonical_state.encode()).hexdigest()
    value = AiGraphCheckpoint(
        conversation_id=conversation.id,
        agent_turn_id=turn.id,
        thread_id=str(conversation.id),
        graph_version=turn.graph_version,
        state_schema_version=turn.state_schema_version,
        node_name=node_name,
        state_hash=state_hash,
        encrypted_state=encrypt_ai_data(serialized),
        sequence_number=sequence,
    )
    session.add(value)
    await session.flush()
    session.add(
        OutboxEvent(
            topic="ai.referral.created",
            aggregate_type="ai_referral",
            aggregate_id=str(value.id),
            payload={"referral_id": str(value.id), "user_id": str(conversation.user_id)},
        )
    )
    return value


async def _run_graph_with_checkpoints(
    session: AsyncSession,
    *,
    conversation: AiConversation,
    turn: AiAgentTurn,
    state: HannaAgentState,
    user_roles: list[str],
) -> HannaAgentState:
    graph = build_hanna_graph(
        GraphDependencies(
            session=session,
            provider=deterministic_provider,
            current_user_id=conversation.user_id,
            user_roles=user_roles,
        )
    )
    current: dict[str, Any] = dict(state)
    sequence = 0
    async for update in graph.astream(state, stream_mode="updates"):
        for node_name, delta in cast(dict[str, dict[str, Any]], update).items():
            current.update(delta)
            sequence += 1
            checkpoint = await _checkpoint(
                session,
                conversation=conversation,
                turn=turn,
                node_name=node_name,
                sequence=sequence,
                state=current,
            )
            turn.checkpoint_reference = str(checkpoint.id)
            await session.execute(
                text(
                    "INSERT INTO ai_node_traces "
                    "(agent_turn_id,node_name,attempt,status,input_hash,output_summary,latency_ms) "
                    "VALUES (:turn,:node,1,'completed',:hash,CAST(:summary AS jsonb),0)"
                ),
                {
                    "turn": turn.id,
                    "node": node_name,
                    "hash": checkpoint.state_hash,
                    "summary": json.dumps(
                        {"updated_fields": sorted(delta), "sequence": sequence},
                        ensure_ascii=False,
                    ),
                },
            )
    return cast(HannaAgentState, current)


async def _persist_referral(
    session: AsyncSession,
    *,
    conversation: AiConversation,
    turn: AiAgentTurn,
    draft: dict[str, Any],
) -> AiHumanReferral:
    key = f"safety:{conversation.id}:{turn.turn_number}"
    existing = await session.scalar(
        select(AiHumanReferral).where(AiHumanReferral.idempotency_key == key)
    )
    if existing is not None:
        return existing
    value = AiHumanReferral(
        referral_number=_referral_number(),
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        source_turn_id=turn.id,
        referral_type=str(draft["type"]),
        priority=str(draft["priority"]),
        risk_category=str(draft["risk_category"]),
        risk_level=str(draft["risk_level"]),
        status="pending_assignment",
        user_visible_summary_encrypted=encrypt_ai_data(
            {"summary": "Safety or professional-support review requested."}
        ),
        internal_context_encrypted=encrypt_ai_data(draft),
        assigned_team="ai_safety",
        consent_status=str(draft["consent_status"]),
        idempotency_key=key,
    )
    session.add(value)
    await session.flush()
    return value


async def _persist_turn_artifacts(
    session: AsyncSession,
    *,
    conversation: AiConversation,
    turn: AiAgentTurn,
    assistant: AiMessage,
    user_content: str,
    final_state: HannaAgentState,
    response: GeneratedAgentResponse,
) -> None:
    planned_calls = final_state.get("planned_tool_calls", [])
    for sequence, result in enumerate(final_state.get("tool_results", []), 1):
        planned = planned_calls[sequence - 1] if sequence <= len(planned_calls) else {}
        tool_code = str(result.get("tool_code", planned.get("tool_code", "unknown")))
        arguments = planned.get("arguments", {})
        output = result.get("output")
        await session.execute(
            text(
                "INSERT INTO ai_tool_executions "
                "(conversation_id,agent_turn_id,tool_code,tool_version,call_sequence,"
                "input_encrypted,input_hash,status,confirmation_status,output_encrypted,"
                "output_summary,started_at,completed_at,error_code,error_message_safe) "
                "VALUES (:conversation,:turn,:tool,'1.0.0',:sequence,:input,:input_hash,"
                ":status,'not_required',:output,CAST(:summary AS jsonb),:started,:completed,"
                ":error,:error_message)"
            ),
            {
                "conversation": conversation.id,
                "turn": turn.id,
                "tool": tool_code,
                "sequence": sequence,
                "input": encrypt_ai_data({"arguments": arguments}),
                "input_hash": content_hash(
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
                ),
                "status": result.get("status", "failed"),
                "output": encrypt_ai_data({"output": output}) if output is not None else None,
                "summary": json.dumps(
                    {"item_count": len((output or {}).get("items", []))}
                    if isinstance(output, dict)
                    else {},
                    ensure_ascii=False,
                ),
                "started": turn.started_at,
                "completed": datetime.now(UTC),
                "error": result.get("error"),
                "error_message": "Controlled tool execution failed."
                if result.get("status") == "failed"
                else None,
            },
        )
    for rank, recommendation in enumerate(response.service_recommendations, 1):
        resource_id = recommendation.get("resource_id")
        try:
            parsed_resource_id = UUID(str(resource_id))
        except (TypeError, ValueError):
            continue
        await session.execute(
            text(
                "INSERT INTO ai_service_recommendations "
                "(conversation_id,agent_turn_id,recommendation_type,resource_id,"
                "recommendation_reason_encrypted,availability_snapshot,price_snapshot,"
                "rank_position,confidence_basis_points) "
                "VALUES (:conversation,:turn,:type,:resource,:reason,CAST(:availability AS jsonb),"
                "NULL,:rank,8000)"
            ),
            {
                "conversation": conversation.id,
                "turn": turn.id,
                "type": str(recommendation.get("type", "service"))[:32],
                "resource": parsed_resource_id,
                "reason": encrypt_ai_data({"reason": recommendation.get("reason")}),
                "availability": json.dumps(
                    {"status": recommendation.get("availability", "unknown")}
                ),
                "rank": rank,
            },
        )
    for claim in response.claims:
        for citation_id in claim.citation_ids:
            await session.execute(
                text(
                    "INSERT INTO ai_response_citations "
                    "(agent_turn_id,message_id,claim_id,claim_text_hash,knowledge_citation_id,"
                    "support_level,validation_status) "
                    "VALUES (:turn,:message,:claim,:hash,:citation,:support,'validated')"
                ),
                {
                    "turn": turn.id,
                    "message": assistant.id,
                    "claim": claim.claim_id,
                    "hash": content_hash(claim.claim_text),
                    "citation": citation_id,
                    "support": claim.support_level,
                },
            )
    tasks = ["risk_classification", "message_classification", "response_generation"]
    if planned_calls:
        tasks.insert(2, "tool_planning")
    for task in tasks:
        profile = await session.scalar(
            select(AiModelProfile).where(
                AiModelProfile.task_type == task,
                AiModelProfile.status == "active",
            )
        )
        if profile is None:
            continue
        await session.execute(
            text(
                "INSERT INTO ai_model_invocations "
                "(conversation_id,agent_turn_id,task_type,model_profile_id,prompt_release_id,"
                "input_hash,input_tokens,output_tokens,latency_ms,cost_minor,cost_currency,status,"
                "fallback_used) VALUES (:conversation,:turn,:task,:profile,:prompt,:hash,"
                ":input_tokens,:output_tokens,0,0,'USD','completed',false)"
            ),
            {
                "conversation": conversation.id,
                "turn": turn.id,
                "task": task,
                "profile": profile.id,
                "prompt": conversation.active_prompt_release_id,
                "hash": content_hash(user_content),
                "input_tokens": max(1, len(user_content) // 4),
                "output_tokens": max(1, len(response.final_text) // 4)
                if task == "response_generation"
                else 1,
            },
        )


async def _persist_conversation_summary(
    session: AsyncSession,
    *,
    conversation: AiConversation,
    turn_number: int,
    messages: list[dict[str, Any]],
    risk_snapshot: dict[str, Any] | None,
) -> None:
    settings = get_settings()
    if (
        conversation.active_prompt_release_id is None
        or turn_number - conversation.summarized_through_turn
        < settings.ai_agent_summary_trigger_turns
    ):
        return
    latest_version = await session.scalar(
        text(
            "SELECT COALESCE(MAX(summary_version),0) FROM ai_conversation_summaries "
            "WHERE conversation_id=:conversation"
        ),
        {"conversation": conversation.id},
    )
    facts = [
        {
            "turn_number": item["turn_number"],
            "role": item["role"],
            "content": item["content"],
        }
        for item in messages[-24:]
    ]
    await session.execute(
        text(
            "INSERT INTO ai_conversation_summaries "
            "(conversation_id,summary_version,summarized_through_turn,factual_summary_encrypted,"
            "unresolved_questions_encrypted,user_goals_encrypted,event_timeline_encrypted,"
            "risk_summary_encrypted,inferred_items_encrypted,model_provider,model_name,"
            "prompt_release_id) VALUES (:conversation,:version,:turn,:facts,:questions,:goals,"
            ":timeline,:risk,:inferred,:provider,:model,:prompt)"
        ),
        {
            "conversation": conversation.id,
            "version": int(latest_version or 0) + 1,
            "turn": turn_number,
            "facts": encrypt_ai_data({"direct_message_facts": facts}),
            "questions": encrypt_ai_data({"unresolved_questions": []}),
            "goals": encrypt_ai_data({"user_goals": []}),
            "timeline": encrypt_ai_data(
                {"turn_numbers": [item["turn_number"] for item in messages[-24:]]}
            ),
            "risk": encrypt_ai_data(risk_snapshot) if risk_snapshot else None,
            "inferred": encrypt_ai_data(
                {"items": [], "policy": "no_inference_promoted_to_user_fact"}
            ),
            "provider": deterministic_provider.provider_code,
            "model": deterministic_provider.model_name,
            "prompt": conversation.active_prompt_release_id,
        },
    )
    conversation.summarized_through_turn = turn_number


async def send_message(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    client_message_id: str,
    content: str,
    locale: str,
    user_roles: list[str],
) -> dict[str, Any]:
    conversation = await owned_conversation(session, conversation_id, user_id, lock=True)
    if conversation.status in {"closed", "deletion_pending", "deleted"}:
        raise VavError(
            "AI_CONVERSATION_CLOSED", "This conversation is not writable.", status_code=409
        )
    if conversation.status == "safety_paused":
        raise VavError(
            "AI_CONVERSATION_SAFETY_PAUSED",
            "Ordinary advice is paused while a safety or professional-support review is pending.",
            status_code=409,
        )
    existing = await session.scalar(
        select(AiMessage).where(
            AiMessage.conversation_id == conversation.id,
            AiMessage.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        assistant = await session.scalar(
            select(AiMessage).where(
                AiMessage.conversation_id == conversation.id,
                AiMessage.turn_number == existing.turn_number,
                AiMessage.role == "assistant",
            )
        )
        turn_id = await session.scalar(
            select(AiAgentTurn.id).where(
                AiAgentTurn.conversation_id == conversation.id,
                AiAgentTurn.turn_number == existing.turn_number,
            )
        )
        decrypted = decrypt_ai_data(assistant.content_encrypted) if assistant else {}
        return {
            "turn_id": str(turn_id or ""),
            "turn_number": existing.turn_number,
            "duplicate": True,
            "message_id": str(assistant.id) if assistant else None,
            "message": decrypted.get("content"),
            "structured": decrypted.get("structured"),
            "citations": [],
            "referral": None,
            "status": conversation.status,
        }
    latest_turn = await session.scalar(
        select(func.coalesce(func.max(AiAgentTurn.turn_number), 0)).where(
            AiAgentTurn.conversation_id == conversation.id
        )
    )
    turn_number = int(latest_turn or 0) + 1
    user_message = AiMessage(
        conversation_id=conversation.id,
        turn_number=turn_number,
        role="user",
        message_type="text",
        client_message_id=client_message_id,
        content_encrypted=encrypt_ai_data({"content": content}),
        content_hash=content_hash(content),
        locale=locale,
        status="accepted",
    )
    session.add(user_message)
    await session.flush()
    turn = AiAgentTurn(
        conversation_id=conversation.id,
        turn_number=turn_number,
        user_message_id=user_message.id,
        status="running",
        graph_version=conversation.active_graph_version,
        state_schema_version=STATE_SCHEMA_VERSION,
        prompt_release_manifest={"release_id": str(conversation.active_prompt_release_id)},
        model_route_manifest={
            "route_id": str(conversation.active_model_route_id),
            "provider": deterministic_provider.provider_code,
            "model": deterministic_provider.model_name,
            "revision": deterministic_provider.model_revision,
        },
        tool_registry_version=registry_version(),
        safety_policy_version=get_settings().ai_safety_policy_version,
        knowledge_index_manifest={"selection": "active_authorized_per_space"},
    )
    session.add(turn)
    await session.flush()
    recent = await conversation_messages(session, conversation.id, user_id)
    initial: HannaAgentState = {
        "conversation_id": str(conversation.id),
        "turn_id": str(turn.id),
        "user_id": str(user_id),
        "locale": locale,
        "consented": bool(conversation.consented_at),
        "user_message": content,
        "recent_messages": recent[-24:],
        "conversation_summary": None,
        "planned_tool_calls": [],
        "tool_results": [],
        "citations": [],
        "warnings": [],
        "visited_nodes": [],
        "retry_count": 0,
    }
    final_state = await _run_graph_with_checkpoints(
        session,
        conversation=conversation,
        turn=turn,
        state=initial,
        user_roles=user_roles,
    )
    response = GeneratedAgentResponse.model_validate(final_state["generated_response"])
    assistant = AiMessage(
        conversation_id=conversation.id,
        turn_number=turn_number,
        role="assistant",
        message_type="safety_response"
        if final_state.get("next_action") == "safety_paused"
        else "text",
        content_encrypted=encrypt_ai_data(
            {"content": response.final_text, "structured": response.model_dump(mode="json")}
        ),
        content_hash=content_hash(response.final_text),
        locale=locale,
        model_provider=deterministic_provider.provider_code,
        model_name=deterministic_provider.model_name,
        model_revision=deterministic_provider.model_revision,
        input_tokens=max(1, len(content) // 4),
        output_tokens=max(1, len(response.final_text) // 4),
        latency_ms=0,
        cost_minor=0,
        cost_currency="USD",
        status="approved",
    )
    session.add(assistant)
    await session.flush()
    await _persist_turn_artifacts(
        session,
        conversation=conversation,
        turn=turn,
        assistant=assistant,
        user_content=content,
        final_state=final_state,
        response=response,
    )
    if final_state.get("referral"):
        await _persist_referral(
            session,
            conversation=conversation,
            turn=turn,
            draft=cast(dict[str, Any], final_state["referral"]),
        )
    turn.assistant_message_id = assistant.id
    turn.status = "completed"
    turn.completed_at = datetime.now(UTC)
    turn.classification_snapshot = final_state.get("classification")
    turn.risk_snapshot = final_state.get("risk_assessment")
    turn.response_plan_snapshot = final_state.get("response_plan")
    turn.context_snapshot_encrypted = encrypt_ai_data(
        {"recent_count": len(recent), "visited_nodes": final_state.get("visited_nodes", [])}
    )
    conversation.relationship_stage = (final_state.get("classification") or {}).get(
        "relationship_stage"
    )
    conversation.primary_topic = (final_state.get("classification") or {}).get("primary_topic")
    conversation.latest_risk_level = (final_state.get("risk_assessment") or {}).get("level")
    conversation.status = (
        "safety_paused" if final_state.get("next_action") == "safety_paused" else "waiting_for_user"
    )
    conversation.last_message_at = datetime.now(UTC)
    conversation.updated_at = datetime.now(UTC)
    await _persist_conversation_summary(
        session,
        conversation=conversation,
        turn_number=turn_number,
        messages=[
            *recent,
            {
                "id": str(assistant.id),
                "turn_number": turn_number,
                "role": "assistant",
                "message_type": assistant.message_type,
                "content": response.final_text,
                "status": assistant.status,
                "created_at": datetime.now(UTC).isoformat(),
            },
        ],
        risk_snapshot=final_state.get("risk_assessment"),
    )
    await session.commit()
    return {
        "turn_id": str(turn.id),
        "turn_number": turn_number,
        "duplicate": False,
        "message_id": str(assistant.id),
        "message": response.final_text,
        "structured": response.model_dump(mode="json"),
        "citations": final_state.get("citations", []),
        "referral": final_state.get("referral"),
        "status": conversation.status,
    }


async def set_memory_consent(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    enabled: bool,
) -> AiConversation:
    value = await owned_conversation(session, conversation_id, user_id, lock=True)
    value.memory_consent_status = "granted" if enabled else "revoked"
    value.updated_at = datetime.now(UTC)
    await session.commit()
    return value


async def delete_conversation(
    session: AsyncSession, *, conversation_id: UUID, user_id: UUID
) -> None:
    value = await owned_conversation(session, conversation_id, user_id, lock=True)
    messages = list(
        (
            await session.scalars(
                select(AiMessage).where(AiMessage.conversation_id == conversation_id)
            )
        ).all()
    )
    tombstone = encrypt_ai_data({"content": "[deleted by user]"})
    for message in messages:
        message.content_encrypted = tombstone
        message.content_hash = content_hash("[deleted by user]")
        message.status = "deleted"
    value.status = "deleted"
    value.memory_consent_status = "revoked"
    value.deleted_at = datetime.now(UTC)
    await session.commit()
