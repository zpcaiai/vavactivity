"""Concurrent identical feedback is stored once."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, feedback

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_concurrent_feedback_events_deduplicate() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        item = items[0]

    async def send():
        async with session_factory() as session:
            try:
                await feedback.ingest(
                    session,
                    viewer_user_id=viewer.id,
                    recommended_user_id=item["recommended_user_id"],
                    feedback_type="profile_opened",
                    recommendation_item_id=item["id"],
                    from_member=True,
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(send(), send(), send())

    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_feedback_events WHERE viewer_user_id=:viewer "
                "AND recommendation_item_id=:item AND feedback_type='profile_opened'"
            ),
            {"viewer": viewer.id, "item": item["id"]},
        )
        assert int(count or 0) == 1
