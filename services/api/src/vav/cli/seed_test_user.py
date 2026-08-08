from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.identity import Role, User, UserRole
from vav.modules.identity.domain import UserStatus
from vav.modules.identity.security import PasswordHasher

TEST_USER_EMAIL = "test@example.com"
LEGACY_TEST_USER_EMAIL = "test@vav.local"
TEST_USER_PASSWORD = "test"
PROTECTED_ENVIRONMENTS = frozenset({"production", "dr"})


async def seed_test_user() -> bool:
    """Create the non-privileged frontend test user once without rotating it later."""
    environment = get_settings().environment
    if environment in PROTECTED_ENVIRONMENTS:
        raise RuntimeError(
            "Refusing to create or preserve the insecure test/test account "
            f"in protected environment: {environment}."
        )

    async with session_factory() as session:
        existing = await session.scalar(
            select(User).where(User.email == TEST_USER_EMAIL).with_for_update()
        )
        if existing is not None:
            return False

        legacy = await session.scalar(
            select(User).where(User.email == LEGACY_TEST_USER_EMAIL).with_for_update()
        )
        if legacy is not None:
            legacy.email = TEST_USER_EMAIL
            legacy.display_email = "test"
            await session.commit()
            return False

        now = datetime.now(UTC)
        user = User(
            email=TEST_USER_EMAIL,
            display_email="test",
            password_hash=PasswordHasher().hash(TEST_USER_PASSWORD),
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
            password_changed_at=now,
            terms_version="test-account-v1",
            terms_accepted_at=now,
            privacy_version="test-account-v1",
            privacy_accepted_at=now,
        )
        session.add(user)
        await session.flush()

        member_role = await session.scalar(select(Role).where(Role.code == "member"))
        if member_role is None:
            raise RuntimeError("Run the permission seed before creating the test user.")
        session.add(
            UserRole(
                user_id=user.id,
                role_id=member_role.id,
                granted_by=user.id,
                grant_reason="Explicit insecure frontend test-account bootstrap",
            )
        )
        await session.commit()
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-insecure-test-account",
        action="store_true",
        help="Acknowledge that this creates the intentionally weak test/test login.",
    )
    args = parser.parse_args()
    if not args.confirm_insecure_test_account:
        raise SystemExit("Refusing to create test/test without explicit confirmation.")

    created = asyncio.run(seed_test_user())
    state = "created" if created else "ready; existing credentials preserved"
    print(f"Frontend test account {state}: {TEST_USER_EMAIL}")


if __name__ == "__main__":
    main()
