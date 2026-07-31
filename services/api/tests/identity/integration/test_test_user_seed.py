from __future__ import annotations

import pytest
from sqlalchemy import select

from vav.cli.seed_permissions import seed_permissions
from vav.cli.seed_test_user import TEST_USER_EMAIL, TEST_USER_PASSWORD, seed_test_user
from vav.core.database import session_factory
from vav.models.identity import Role, User, UserRole
from vav.modules.identity.domain import UserStatus
from vav.modules.identity.security import PasswordHasher


@pytest.mark.asyncio
async def test_test_user_seed_is_login_ready_and_does_not_rotate_credentials() -> None:
    await seed_permissions()
    await seed_test_user()

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == TEST_USER_EMAIL))
        assert user is not None
        original_id = user.id
        original_password_hash = user.password_hash

    assert await seed_test_user() is False

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == TEST_USER_EMAIL))
        assert user is not None
        assert user.id == original_id
        assert user.password_hash == original_password_hash
        assert user.status == UserStatus.ACTIVE
        assert user.email_verified_at is not None
        assert PasswordHasher().verify(user.password_hash, TEST_USER_PASSWORD)
        member_role = await session.scalar(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id, Role.code == "member")
        )
        assert member_role is not None
