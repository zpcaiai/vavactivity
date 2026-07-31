from __future__ import annotations

import asyncio

from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.identity import Permission, Role, RolePermission
from vav.modules.identity.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS


async def seed_permissions() -> None:
    async with session_factory() as session:
        permissions_by_code: dict[str, Permission] = {}
        for code in sorted(ALL_PERMISSIONS):
            permission = await session.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                resource, _, action = code.partition(".")
                permission = Permission(
                    code=code,
                    resource=resource,
                    action=action,
                    description=f"Allow {code}",
                    risk_level=(
                        "high"
                        if any(
                            marker in code
                            for marker in (
                                "publish",
                                "adjust",
                                "assign",
                                "disable",
                                "export",
                                "activate",
                            )
                        )
                        else "standard"
                    ),
                )
                session.add(permission)
                await session.flush()
            permissions_by_code[code] = permission

        for role_code, permission_codes in ROLE_PERMISSIONS.items():
            role = await session.scalar(select(Role).where(Role.code == role_code))
            if role is None:
                role = Role(
                    code=role_code,
                    name=role_code.replace("_", " ").title(),
                    description=f"System role: {role_code}",
                    is_system=True,
                    is_active=True,
                )
                session.add(role)
                await session.flush()
            for permission_code in sorted(permission_codes):
                permission = permissions_by_code[permission_code]
                existing = await session.get(RolePermission, (role.id, permission.id))
                if existing is None:
                    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        await session.commit()
    print(
        f"Permission seed complete: {len(ALL_PERMISSIONS)} permissions, "
        f"{len(ROLE_PERMISSIONS)} roles"
    )


if __name__ == "__main__":
    asyncio.run(seed_permissions())
