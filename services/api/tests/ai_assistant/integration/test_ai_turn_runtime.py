from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.ai_assistant import service as service_module
from vav.modules.ai_assistant.service import create_conversation, send_message


@pytest.mark.asyncio
async def test_service_turn_persists_graph_tool_model_and_response_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = service_module.get_settings()
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: settings.model_copy(update={"ai_agent_summary_trigger_turns": 1}),
    )
    async with session_factory() as session:
        conversation = await create_conversation(
            session,
            user_id=SYSTEM_USER_ID,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            consent_version="batch-10-runtime",
            accept_ai_disclosure=True,
            memory_opt_in=False,
        )
        client_message_id = f"runtime-{uuid4()}"
        result = await send_message(
            session,
            conversation_id=conversation.id,
            user_id=SYSTEM_USER_ID,
            client_message_id=client_message_id,
            content="平台现在有哪些课程？",
            locale="zh-CN",
            user_roles=["member"],
        )
        assert result["status"] == "waiting_for_user"
        assert result["message"]
        duplicate = await send_message(
            session,
            conversation_id=conversation.id,
            user_id=SYSTEM_USER_ID,
            client_message_id=client_message_id,
            content="平台现在有哪些课程？",
            locale="zh-CN",
            user_roles=["member"],
        )
        assert duplicate["duplicate"] is True
        assert duplicate["turn_id"] == result["turn_id"]
        assert duplicate["message_id"] == result["message_id"]
        counts = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM ai_graph_checkpoints WHERE agent_turn_id=:turn),"
                    "(SELECT count(*) FROM ai_node_traces WHERE agent_turn_id=:turn),"
                    "(SELECT count(*) FROM ai_tool_executions WHERE agent_turn_id=:turn),"
                    "(SELECT count(*) FROM ai_model_invocations WHERE agent_turn_id=:turn),"
                    "(SELECT count(*) FROM ai_conversation_summaries "
                    "WHERE conversation_id=:conversation)"
                ),
                {"turn": UUID(result["turn_id"]), "conversation": conversation.id},
            )
        ).one()
        assert counts[0] >= 8
        assert counts[1] == counts[0]
        assert counts[2] >= 1
        assert counts[3] >= 4
        assert counts[4] == 1


@pytest.mark.asyncio
async def test_high_risk_turn_creates_referral_and_pauses_followup_advice() -> None:
    async with session_factory() as session:
        conversation = await create_conversation(
            session,
            user_id=SYSTEM_USER_ID,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            consent_version="batch-10-runtime",
            accept_ai_disclosure=True,
            memory_opt_in=False,
        )
        result = await send_message(
            session,
            conversation_id=conversation.id,
            user_id=SYSTEM_USER_ID,
            client_message_id=f"safety-{uuid4()}",
            content="他正在追我，我现在有危险。",
            locale="zh-CN",
            user_roles=["member"],
        )
        assert result["status"] == "safety_paused"
        assert result["referral"]["risk_level"] == "immediate"
        with pytest.raises(VavError) as error:
            await send_message(
                session,
                conversation_id=conversation.id,
                user_id=SYSTEM_USER_ID,
                client_message_id=f"blocked-{uuid4()}",
                content="继续给我普通关系建议。",
                locale="zh-CN",
                user_roles=["member"],
            )
        assert error.value.code == "AI_CONVERSATION_SAFETY_PAUSED"
