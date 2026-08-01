from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher

TEST_PASSWORD = "VavPrivacy!2026_Secure#"


async def create_privacy_user(session: AsyncSession) -> User:
    email = f"privacy-{uuid4()}@example.com"
    user = User(
        email=email,
        display_email=email,
        password_hash=PasswordHasher().hash(TEST_PASSWORD),
        status="active",
        email_verified_at=datetime.now(UTC),
        preferred_locale="zh-CN",
        timezone="Asia/Shanghai",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
