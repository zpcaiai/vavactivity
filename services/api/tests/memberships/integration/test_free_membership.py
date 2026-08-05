import json
from datetime import UTC, datetime

# ruff: noqa: E501
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.memberships import projection, service


async def _free_fixture() -> tuple[UUID, str]:
    async with session_factory() as session:
        email = f"membership-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("MembershipFixture!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        code = f"free-test-{uuid4()}"
        plan = (
            await session.execute(
                text(
                    "INSERT INTO membership_plans "
                    "(plan_code,internal_name,plan_type,status,default_locale,display_order,created_by,updated_by) "
                    "VALUES (:code,'Test Free','free','active','en',-1000,:actor,:actor) RETURNING id"
                ),
                {"code": code, "actor": user.id},
            )
        ).scalar_one()
        version = (
            await session.execute(
                text(
                    "INSERT INTO membership_plan_versions "
                    "(membership_plan_id,version_number,semantic_version,status,valid_from,created_by,activated_at) "
                    "VALUES (:plan,1,'1.0.0','active',now(),:actor,now()) RETURNING id"
                ),
                {"plan": plan, "actor": user.id},
            )
        ).scalar_one()
        await session.execute(
            text("UPDATE membership_plans SET current_version_id=:version WHERE id=:plan"),
            {"version": version, "plan": plan},
        )
        definition = (
            await session.execute(
                text(
                    "INSERT INTO membership_benefit_definitions "
                    "(benefit_code,semantic_version,benefit_type,value_schema,owning_module,status) "
                    "VALUES ('platform.basic_access',:semantic,'capability','{}'::jsonb,'platform','active') RETURNING id"
                ),
                {"semantic": str(uuid4())},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO membership_plan_benefits "
                "(membership_plan_version_id,benefit_definition_id,benefit_value) "
                "VALUES (:version,:definition,CAST(:benefit_value AS jsonb))"
            ),
            {
                "version": version,
                "definition": definition,
                "benefit_value": json.dumps({"enabled": True}),
            },
        )
        user_id = user.id
        await session.commit()
        return user_id, code


@pytest.mark.asyncio
async def test_free_membership_is_idempotent_and_allows_registered_capability() -> None:
    user_id, code = await _free_fixture()
    async with session_factory() as session:
        first = await projection.ensure_free_membership(session, user_id)
        second = await projection.ensure_free_membership(session, user_id)
        assert first["id"] == second["id"]
        summary = await service.membership_summary(session, user_id)
        assert summary["plan_code"] == code
        decision = await service.decide_access(
            session,
            user_id=user_id,
            capability_code="platform.basic_access",
            resource_type=None,
            resource_id=None,
            requested_quantity=1,
        )
        assert decision["allowed"] is True
        assert decision["reason_code"] is None
