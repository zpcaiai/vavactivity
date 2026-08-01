from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from starlette.requests import Request

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import AuthSession, User
from vav.modules.ai_assistant.router import create_tool_confirmation, execute_confirmed_tool
from vav.modules.ai_assistant.schemas import ExecuteConfirmedToolRequest, ToolConfirmationRequest
from vav.modules.ai_assistant.service import create_conversation, send_message
from vav.modules.identity.dependencies import AuthenticatedPrincipal


def request_fixture() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


@pytest.mark.asyncio
async def test_write_tool_requires_matching_single_use_user_confirmation() -> None:
    async with session_factory() as session:
        user = await session.get(User, SYSTEM_USER_ID)
        assert user is not None
        principal = AuthenticatedPrincipal(
            user=user,
            session=cast(AuthSession, cast(Any, None)),
            audience="vav-user",
            permissions=frozenset(),
        )
        conversation = await create_conversation(
            session,
            user_id=user.id,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            consent_version="batch-10-confirmation",
            accept_ai_disclosure=True,
            memory_opt_in=False,
        )
        await send_message(
            session,
            conversation_id=conversation.id,
            user_id=user.id,
            client_message_id=f"confirmation-turn-{uuid4()}",
            content="请帮我整理一个行动项。",
            locale="zh-CN",
            user_roles=["member"],
        )
        arguments = {"content": "下一次沟通前写下观察、感受、需要和请求。"}
        confirmation = await create_tool_confirmation(
            conversation.id,
            ToolConfirmationRequest(tool_code="create_user_action_item", arguments=arguments),
            request_fixture(),
            principal,
            session,
        )
        token = confirmation["data"]["confirmation_token"]
        idempotency_key = f"confirmed-action-{uuid4()}"
        completed = await execute_confirmed_tool(
            conversation.id,
            "create_user_action_item",
            ExecuteConfirmedToolRequest(
                confirmation_token=token,
                arguments=arguments,
                idempotency_key=idempotency_key,
            ),
            request_fixture(),
            principal,
            session,
        )
        assert completed["data"]["status"] == "completed"
        duplicate = await execute_confirmed_tool(
            conversation.id,
            "create_user_action_item",
            ExecuteConfirmedToolRequest(
                confirmation_token=token,
                arguments=arguments,
                idempotency_key=idempotency_key,
            ),
            request_fixture(),
            principal,
            session,
        )
        assert duplicate["data"]["duplicate"] is True
        with pytest.raises(VavError) as error:
            await execute_confirmed_tool(
                conversation.id,
                "create_user_action_item",
                ExecuteConfirmedToolRequest(
                    confirmation_token=token,
                    arguments=arguments,
                    idempotency_key=f"replay-{uuid4()}",
                ),
                request_fixture(),
                principal,
                session,
            )
        assert error.value.code == "AI_TOOL_CONFIRMATION_INVALID"
