"""Suspended accounts and paused profiles leave the recommendation surface."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_a_suspended_account_disappears_from_generation_and_display() -> None:
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
        assert items
        suspended_id = items[0]["recommended_user_id"]

        await session.execute(
            text("UPDATE users SET status='suspended' WHERE id=:id"), {"id": suspended_id}
        )
        await session.commit()
        await service.rebuild_pool_entry(session, suspended_id)
        await session.commit()

        remaining = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert all(item["recommended_user_id"] != suspended_id for item in remaining)

        regenerated = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != suspended_id for item in regenerated["candidates"])
