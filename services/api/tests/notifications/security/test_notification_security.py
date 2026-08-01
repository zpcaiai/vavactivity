# ruff: noqa: E501
from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import select, text

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.cli.seed_test_user import TEST_USER_EMAIL, seed_test_user
from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import AuthSession, User
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.notifications.router import notification_detail


def request_fixture() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/account/notifications/x",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_notification() -> None:
    await seed_test_user()
    async with session_factory() as session:
        other = await session.scalar(select(User).where(User.email == TEST_USER_EMAIL))
        owner = await session.get(User, SYSTEM_USER_ID)
        assert other is not None and owner is not None
        intent_id = await session.scalar(
            text(
                "INSERT INTO notification_intents "
                "(notification_type,category,priority,recipient_type,recipient_reference_id,template_code,"
                "channel_policy,preference_policy,template_variables_encrypted,deduplication_key,status) "
                "VALUES ('security-test','security','high','user',:user_id,'password-changed',"
                "'{}'::jsonb,'mandatory_security','encrypted',:dedup,'created') RETURNING id"
            ),
            {"user_id": owner.id, "dedup": f"security-test:{uuid4()}"},
        )
        notification_id = await session.scalar(
            text(
                "INSERT INTO user_notifications "
                "(user_id,notification_intent_id,category,priority,title,body,status,rendering_snapshot) "
                "VALUES (:user_id,:intent_id,'security','high','Security','Safe summary','active','{}'::jsonb) "
                "RETURNING id"
            ),
            {"user_id": owner.id, "intent_id": intent_id},
        )
        await session.commit()
        principal = AuthenticatedPrincipal(
            user=other,
            session=cast(AuthSession, cast(Any, None)),
            audience="vav-user",
            permissions=frozenset(),
        )
        with pytest.raises(VavError) as error:
            await notification_detail(
                UUID(str(notification_id)), request_fixture(), principal, session
            )
        assert error.value.code == "NOTIFICATION_NOT_FOUND"


def test_provider_metadata_type_has_no_sensitive_content_fields() -> None:
    from vav.modules.notifications.providers import EmailSendRequest

    fields = set(EmailSendRequest.__dataclass_fields__)
    assert "counseling_content" not in fields
    assert "ai_conversation" not in fields
    assert "risk_record" not in fields
