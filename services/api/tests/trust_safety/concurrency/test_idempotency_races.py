import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.trust_safety import service
from vav.modules.trust_safety.schemas import ReportCreateRequest


async def _member() -> UUID:
    async with session_factory() as session:
        email = f"safety-race-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("SafetyFixture!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_duplicate_report_race_has_one_report_and_case() -> None:
    reporter, subject = await _member(), await _member()
    payload = ReportCreateRequest(
        target_type="user",
        reported_user_id=subject,
        category="harassment",
        idempotency_key=f"race-{uuid4()}",
    )

    async def submit() -> dict[str, object]:
        async with session_factory() as session:
            return await service.create_report(session, reporter=reporter, payload=payload)

    first, second = await asyncio.gather(submit(), submit())
    assert first["id"] == second["id"]
    async with session_factory() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM safety_reports WHERE reporter_user_id=:reporter "
                    "AND idempotency_key=:key"
                ),
                {"reporter": reporter, "key": payload.idempotency_key},
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM safety_case_reports cr "
                    "JOIN safety_reports r ON r.id=cr.report_id "
                    "WHERE r.reporter_user_id=:reporter AND r.idempotency_key=:key"
                ),
                {"reporter": reporter, "key": payload.idempotency_key},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_simultaneous_block_is_singleton_and_pair_version_is_stable() -> None:
    blocker, blocked = await _member(), await _member()

    async def block() -> dict[str, object]:
        async with session_factory() as session:
            return await service.create_block(session, blocker=blocker, blocked=blocked)

    first, second = await asyncio.gather(block(), block())
    assert first["id"] == second["id"]
    assert first["restriction_version"] == second["restriction_version"]
    async with session_factory() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM user_blocks WHERE blocker_user_id=:blocker "
                    "AND blocked_user_id=:blocked AND status='active'"
                ),
                {"blocker": blocker, "blocked": blocked},
            )
            == 1
        )
