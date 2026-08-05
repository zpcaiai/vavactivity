"""Only approved, active profiles can be recommended."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.recommendations import service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_a_draft_profile_never_enters_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, profile = await create_eligible_member(session, reviewer)

        await session.execute(
            text(
                "UPDATE dating_profiles SET status='draft', approved_version_number=NULL WHERE id=:id"
            ),
            {"id": profile["id"]},
        )
        await session.commit()
        await profile_service.rebuild_projection(session, profile["id"])
        entry = await service.rebuild_pool_entry(session, user.id)
        await session.commit()

        assert entry is None
        assert await service.projection_for(session, user.id) is None


@pytest.mark.asyncio
async def test_generation_refuses_an_ineligible_viewer() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, profile = await create_eligible_member(session, reviewer)
        await session.execute(
            text("UPDATE dating_profiles SET status='suspended' WHERE id=:id"),
            {"id": profile["id"]},
        )
        await session.commit()
        await profile_service.rebuild_projection(session, profile["id"])
        await service.rebuild_pool_entry(session, user.id)
        await session.commit()

        from vav.common.exceptions import VavError

        with pytest.raises(VavError) as error:
            await service.generate_candidates(session, user.id)
        assert error.value.code == "RECOMMENDATION_NOT_ELIGIBLE"
