from __future__ import annotations

import argparse
import asyncio
import getpass
from datetime import UTC, datetime
from uuid import uuid4

from email_validator import validate_email
from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.identity import Role, User, UserRole
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.domain import UserStatus
from vav.modules.identity.security import PasswordHasher, PasswordPolicy


async def create_super_admin(email: str, password: str) -> None:
    normalized = validate_email(email, check_deliverability=False).normalized.casefold()
    policy = PasswordPolicy()
    policy.validate(password, normalized)
    hasher = PasswordHasher()
    now = datetime.now(UTC)
    async with session_factory() as session:
        role = await session.scalar(select(Role).where(Role.code == "super_admin"))
        if role is None:
            raise RuntimeError("Run `make auth-seed` before creating a super administrator.")
        user = await session.scalar(select(User).where(User.email == normalized).with_for_update())
        if user is None:
            user = User(
                id=uuid4(),
                email=normalized,
                display_email=email.strip(),
                password_hash=hasher.hash(password),
                status=UserStatus.ACTIVE,
                email_verified_at=now,
                preferred_locale="zh-CN",
                timezone="UTC",
                password_changed_at=now,
            )
            session.add(user)
            await session.flush()
        else:
            user.password_hash = hasher.hash(password)
            user.status = UserStatus.ACTIVE
            user.email_verified_at = user.email_verified_at or now
            user.auth_version += 1
        assignment = await session.get(UserRole, (user.id, role.id))
        if assignment is None:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    granted_by=user.id,
                    grant_reason="Secure interactive bootstrap",
                )
            )
        else:
            assignment.revoked_at = None
            assignment.revoked_by = None
            assignment.revoke_reason = None
        user.rbac_version += 1
        record_security_event(
            session,
            event_type="admin.bootstrap.created",
            severity="warning",
            actor_type="bootstrap",
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
            reason="Secure interactive bootstrap",
        )
        await session.commit()
    print(f"Super administrator ready: {normalized}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email")
    args = parser.parse_args()
    email = args.email or input("Administrator email: ").strip()
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    asyncio.run(create_super_admin(email, password))


if __name__ == "__main__":
    main()
