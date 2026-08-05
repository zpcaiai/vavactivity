"""Daily budgets hold under concurrent reservation."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_concurrent_reservations_never_exceed_the_daily_limit() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(session, reviewer)
        await service.update_user_settings(session, viewer.id, {"daily_received_limit": 5})
        await session.commit()
        today = service.utcnow().date()
        await batches.budget_row(session, viewer.id, today)
        await session.commit()

    async def reserve() -> int:
        async with session_factory() as session:
            granted = await batches._reserve_received_capacity(
                session, user_id=viewer.id, budget_date=today, requested=3
            )
            await session.commit()
            return granted

    granted = await asyncio.gather(*[reserve() for _ in range(6)])

    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT current_received_count, daily_received_limit FROM recommendation_exposure_budgets "
                        "WHERE user_id=:id AND budget_date=:date"
                    ),
                    {"id": viewer.id, "date": today},
                )
            )
            .mappings()
            .one()
        )
        assert int(row["current_received_count"]) == int(row["daily_received_limit"]) == 5
        assert sum(granted) == 5


@pytest.mark.asyncio
async def test_a_refresh_cannot_buy_extra_capacity() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(session, reviewer)
        await service.update_user_settings(session, viewer.id, {"daily_received_limit": 0})
        await session.commit()
        today = service.utcnow().date()
        await batches.budget_row(session, viewer.id, today)
        await session.commit()

        granted = await batches._reserve_received_capacity(
            session, user_id=viewer.id, budget_date=today, requested=10
        )
        await session.commit()
        assert granted == 0
