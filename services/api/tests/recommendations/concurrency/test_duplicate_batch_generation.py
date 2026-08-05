"""Concurrent batch generation stays idempotent."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_two_workers_produce_one_daily_batch() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )

    async def generate():
        async with session_factory() as session:
            try:
                await batches.generate_batch(session, viewer.id)
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(generate(), generate(), generate())

    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_batches WHERE user_id=:id AND batch_type='daily'"
            ),
            {"id": viewer.id},
        )
        assert int(count or 0) == 1
