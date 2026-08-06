from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.experience.service import sync_user_tasks
from vav.modules.identity.security import PasswordHasher


@pytest.mark.asyncio
async def test_concurrent_task_sync_keeps_one_deduplication_key() -> None:
    async with session_factory() as session:
        email = f"experience-concurrency-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("ExperienceUser!2026"),
            status="active",
            email_verified_at=None,
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    async def sync() -> None:
        async with session_factory() as session:
            await sync_user_tasks(session, user_id)

    await asyncio.gather(sync(), sync(), sync())
    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM experience_user_tasks WHERE user_id=:user "
                "AND deduplication_key='identity.verify-email'"
            ),
            {"user": user_id},
        )
        assert count == 1
