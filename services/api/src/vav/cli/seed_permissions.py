from __future__ import annotations

import asyncio

from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.identity import Permission, Role, RolePermission
from vav.modules.identity.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS


async def seed_permissions() -> None:
    async with session_factory() as session:
        permissions_by_code = {
            permission.code: permission
            for permission in (
                await session.scalars(
                    select(Permission).where(Permission.code.in_(ALL_PERMISSIONS))
                )
            ).all()
        }
        for code in sorted(ALL_PERMISSIONS):
            permission = permissions_by_code.get(code)
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
                permissions_by_code[code] = permission
        await session.flush()

        roles_by_code = {
            role.code: role
            for role in (
                await session.scalars(select(Role).where(Role.code.in_(ROLE_PERMISSIONS)))
            ).all()
        }
        for role_code in ROLE_PERMISSIONS:
            role = roles_by_code.get(role_code)
            if role is None:
                role = Role(
                    code=role_code,
                    name=role_code.replace("_", " ").title(),
                    description=f"System role: {role_code}",
                    is_system=True,
                    is_active=True,
                )
                session.add(role)
                roles_by_code[role_code] = role
        await session.flush()

        role_ids = [role.id for role in roles_by_code.values()]
        existing_assignments = set(
            (
                await session.execute(
                    select(RolePermission.role_id, RolePermission.permission_id).where(
                        RolePermission.role_id.in_(role_ids)
                    )
                )
            )
            .tuples()
            .all()
        )
        for role_code, permission_codes in ROLE_PERMISSIONS.items():
            role = roles_by_code[role_code]
            for permission_code in sorted(permission_codes):
                permission = permissions_by_code[permission_code]
                if (role.id, permission.id) not in existing_assignments:
                    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        await session.commit()
    print(
        f"Permission seed complete: {len(ALL_PERMISSIONS)} permissions, "
        f"{len(ROLE_PERMISSIONS)} roles"
    )


if __name__ == "__main__":
    asyncio.run(seed_permissions())
