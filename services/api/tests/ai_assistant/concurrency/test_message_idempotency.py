from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.core.database import session_factory
from vav.models.ai_assistant import AiMessage
from vav.modules.ai_assistant.crypto import content_hash, encrypt_ai_data
from vav.modules.ai_assistant.service import create_conversation


@pytest.mark.asyncio
async def test_client_message_id_is_unique_per_conversation() -> None:
    async with session_factory() as session:
        conversation = await create_conversation(
            session,
            user_id=SYSTEM_USER_ID,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            consent_version="batch-10-test",
            accept_ai_disclosure=True,
            memory_opt_in=False,
        )
        conversation_id = conversation.id
        client_message_id = f"concurrency-{uuid4()}"
        session.add(
            AiMessage(
                conversation_id=conversation_id,
                turn_number=1,
                role="user",
                message_type="text",
                client_message_id=client_message_id,
                content_encrypted=encrypt_ai_data({"content": "first"}),
                content_hash=content_hash("first"),
                locale="zh-CN",
                status="accepted",
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            AiMessage(
                conversation_id=conversation_id,
                turn_number=2,
                role="user",
                message_type="text",
                client_message_id=client_message_id,
                content_encrypted=encrypt_ai_data({"content": "duplicate"}),
                content_hash=content_hash("duplicate"),
                locale="zh-CN",
                status="accepted",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
