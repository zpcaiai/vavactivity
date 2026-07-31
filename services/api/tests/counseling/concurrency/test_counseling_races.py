import asyncio
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.counseling import (
    CounselingMentor,
    CounselingServiceDefinition,
    CounselingSlotHold,
)
from vav.models.identity import User
from vav.modules.counseling.service import availability_service


@pytest.mark.asyncio
async def test_two_users_cannot_hold_the_same_slot() -> None:
    async with session_factory() as session:
        mentor = await session.scalar(
            select(CounselingMentor).where(CounselingMentor.mentor_code == "counseling-e2e-mentor")
        )
        service = await session.scalar(
            select(CounselingServiceDefinition).where(
                CounselingServiceDefinition.service_code == "counseling-e2e-growth-session"
            )
        )
        assert mentor is not None and service is not None
        users = [
            User(
                email=f"counseling-race-{uuid4().hex}@example.com",
                display_email=f"counseling-race-{uuid4().hex}@example.com",
                status="active",
            )
            for _ in range(2)
        ]
        session.add_all(users)
        await session.commit()
        slots = await availability_service.slots(
            session,
            mentor_id=mentor.id,
            service_id=service.id,
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=8),
        )
        assert slots
        starts_at = slots[-1]["starts_at"]
        mentor_id, service_id = mentor.id, service.id
        user_ids = [item.id for item in users]

    async def hold(user_id, suffix: str):
        async with session_factory() as session:
            from datetime import datetime

            return await availability_service.hold(
                session,
                mentor_id=mentor_id,
                service_id=service_id,
                user_id=user_id,
                starts_at=datetime.fromisoformat(starts_at),
                idempotency_key=f"race-{suffix}-{uuid4().hex}",
            )

    results = await asyncio.gather(
        hold(user_ids[0], "a"), hold(user_ids[1], "b"), return_exceptions=True
    )
    successes = [item for item in results if isinstance(item, CounselingSlotHold)]
    conflicts = [item for item in results if isinstance(item, VavError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "COUNSELING_SLOT_UNAVAILABLE"
    async with session_factory() as session:
        active = await session.scalar(
            select(func.count(CounselingSlotHold.id)).where(
                CounselingSlotHold.mentor_id == mentor_id,
                CounselingSlotHold.starts_at == successes[0].starts_at,
                CounselingSlotHold.status == "active",
            )
        )
    assert active == 1


@pytest.mark.asyncio
async def test_same_hold_idempotency_key_returns_one_record() -> None:
    async with session_factory() as session:
        mentor = await session.scalar(select(CounselingMentor).limit(1))
        service = await session.scalar(select(CounselingServiceDefinition).limit(1))
        assert mentor is not None and service is not None
        user = User(
            email=f"counseling-idempotent-{uuid4().hex}@example.com",
            display_email=f"counseling-idempotent-{uuid4().hex}@example.com",
            status="active",
        )
        session.add(user)
        await session.commit()
        slots = await availability_service.slots(
            session,
            mentor_id=mentor.id,
            service_id=service.id,
            start_date=date.today() + timedelta(days=9),
            end_date=date.today() + timedelta(days=16),
        )
        assert slots
        from datetime import datetime

        starts_at = datetime.fromisoformat(slots[-1]["starts_at"])
        key = f"same-{uuid4().hex}"
        first = await availability_service.hold(
            session,
            mentor_id=mentor.id,
            service_id=service.id,
            user_id=user.id,
            starts_at=starts_at,
            idempotency_key=key,
        )
        second = await availability_service.hold(
            session,
            mentor_id=mentor.id,
            service_id=service.id,
            user_id=user.id,
            starts_at=starts_at,
            idempotency_key=key,
        )
        assert first.id == second.id
