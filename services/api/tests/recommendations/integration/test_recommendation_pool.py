"""Recommendation-pool eligibility against the database."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_an_approved_active_profile_enters_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)

        entry = await service.pool_entry(session, user.id)
        assert entry is not None
        assert entry["eligible"]
        assert entry["eligibility_reasons"] == []
        assert entry["profile_projection_version"] >= 1


@pytest.mark.asyncio
async def test_pausing_recommendations_removes_a_member_from_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)

        await service.update_user_settings(session, user.id, {"recommendations_paused": True})
        await session.commit()

        entry = await service.pool_entry(session, user.id)
        assert entry is not None
        assert not entry["eligible"]
        assert "recommendation_paused_by_user" in entry["eligibility_reasons"]


@pytest.mark.asyncio
async def test_a_suspended_account_leaves_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)

        await session.execute(
            text("UPDATE users SET status='suspended' WHERE id=:id"), {"id": user.id}
        )
        await session.commit()
        entry = await service.rebuild_pool_entry(session, user.id)
        await session.commit()

        assert entry is not None
        assert not entry["eligible"]
        assert "account_not_active" in entry["eligibility_reasons"]


@pytest.mark.asyncio
async def test_a_member_without_a_projection_is_not_in_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, profile = await create_eligible_member(session, reviewer)

        await session.execute(
            text("DELETE FROM dating_profile_recommendation_projections WHERE user_id=:id"),
            {"id": user.id},
        )
        await session.commit()
        entry = await service.rebuild_pool_entry(session, user.id)
        await session.commit()
        assert entry is None
        assert await service.pool_entry(session, user.id) is None


@pytest.mark.asyncio
async def test_pool_rebuild_is_idempotent_and_versioned() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)

        first = await service.pool_entry(session, user.id)
        await service.rebuild_pool_entry(session, user.id)
        await session.commit()
        second = await service.pool_entry(session, user.id)

        assert first is not None and second is not None
        assert second["pool_version"] > first["pool_version"]
        assert second["eligible"] == first["eligible"]
