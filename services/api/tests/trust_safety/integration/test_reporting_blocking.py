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
        email = f"safety-{uuid4()}@example.com"
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
async def test_report_and_block_is_idempotent_and_propagates() -> None:
    reporter, reported = await _member(), await _member()
    payload = ReportCreateRequest(
        target_type="user",
        reported_user_id=reported,
        category="harassment",
        description="Repeated unwanted contact",
        block_user=True,
        immediate_danger=False,
        idempotency_key=f"report-{uuid4()}",
    )
    async with session_factory() as session:
        first = await service.create_report(session, reporter=reporter, payload=payload)
        second = await service.create_report(session, reporter=reporter, payload=payload)
        assert first["id"] == second["id"]
        assert await service.list_blocks(session, reporter)
        low, high = sorted((reporter, reported), key=str)
        exclusion = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_pair_exclusions WHERE user_low_id=:low "
                "AND user_high_id=:high AND exclusion_type='block' AND released_at IS NULL"
            ),
            {"low": low, "high": high},
        )
        assert exclusion == 1
        decision = await service.evaluate_gate(
            session,
            decision_context="recommendation",
            subject_user_id=reporter,
            counterpart_user_id=reported,
        )
        assert not decision.allowed
        assert decision.safe_reason_code == "pair_blocked"


@pytest.mark.asyncio
async def test_unblock_never_restores_historical_access() -> None:
    blocker, blocked = await _member(), await _member()
    async with session_factory() as session:
        await service.create_block(session, blocker=blocker, blocked=blocked)
        result = await service.lift_block(session, blocker=blocker, blocked=blocked)
        assert result["status"] == "lifted"
        assert not await service.list_blocks(session, blocker)
        active_exclusion = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_pair_exclusions WHERE exclusion_type='block' "
                "AND released_at IS NULL AND ((user_low_id=:a AND user_high_id=:b) "
                "OR (user_low_id=:b AND user_high_id=:a))"
            ),
            {"a": blocker, "b": blocked},
        )
        assert active_exclusion == 0
