from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import vav.cli.seed_test_user as seed_test_user_module
from vav.cli.seed_permissions import seed_permissions
from vav.cli.seed_test_user import TEST_USER_EMAIL, TEST_USER_PASSWORD, seed_test_user
from vav.core.database import session_factory
from vav.main import app
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


@pytest.mark.parametrize("environment", ["production", "dr"])
@pytest.mark.asyncio
async def test_test_user_seed_rejects_protected_environment_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    database_accessed = False

    def forbidden_session_factory() -> None:
        nonlocal database_accessed
        database_accessed = True
        raise AssertionError("protected seed policy must run before database access")

    monkeypatch.setattr(
        seed_test_user_module,
        "get_settings",
        lambda: SimpleNamespace(environment=environment),
    )
    monkeypatch.setattr(
        seed_test_user_module,
        "session_factory",
        forbidden_session_factory,
    )

    with pytest.raises(RuntimeError, match=f"protected environment: {environment}"):
        await seed_test_user_module.seed_test_user()

    assert database_accessed is False


def test_cli_confirmation_cannot_override_production_seed_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        seed_test_user_module,
        "get_settings",
        lambda: SimpleNamespace(environment="production"),
    )
    monkeypatch.setattr(
        seed_test_user_module,
        "session_factory",
        lambda: pytest.fail("protected CLI must not access the database"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_test_user", "--confirm-insecure-test-account"],
    )

    with pytest.raises(RuntimeError, match="protected environment: production"):
        seed_test_user_module.main()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
                "device_name": "test-account-integration",
            },
        )
    assert response.status_code == 200, response.text
