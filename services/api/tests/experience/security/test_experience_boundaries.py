from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.experience import service
from vav.modules.experience.schemas import HandoffCreate
from vav.modules.identity.security import PasswordHasher


async def _user() -> User:
    async with session_factory() as session:
        email = f"experience-security-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("ExperienceSecurity!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.expunge(user)
        return user


@pytest.mark.asyncio
async def test_cross_user_handoff_is_indistinguishable_from_missing() -> None:
    owner, attacker = await _user(), await _user()
    source_id = uuid4()
    async with session_factory() as session:
        handoff = await service.create_handoff(
            session,
            owner.id,
            HandoffCreate(
                handoff_code="activity-to-matchmaking",
                source_entity_type="activity",
                source_entity_id=source_id,
                user_intent="continue.profile",
                context={"activity_id": str(source_id)},
                source_route_code="user.activities",
            ),
        )
        with pytest.raises(VavError) as error:
            await service.accept_handoff(session, attacker.id, handoff["id"], set())
        assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_search_never_returns_disallowed_sensitive_projection_types() -> None:
    user = await _user()
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO experience_search_documents "
                    "(document_code,source_module,source_entity_type,title,summary,locale,"
                    "visibility,owner_user_id,route_code,source_version) VALUES "
                    "(:code,'matchmaking','one_sided_like','hidden','hidden','en','personal',"
                    ":owner,'user.matchmaking','1')"
                ),
                {"code": f"forbidden:{uuid4()}", "owner": user.id},
            )
            await session.commit()
        await session.rollback()
