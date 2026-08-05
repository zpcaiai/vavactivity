"""Recommendations consume only the approved Batch 13 projection."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import PROHIBITED_RECOMMENDATION_FIELDS

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_the_projection_carries_no_prohibited_field() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)

        projection = await service.projection_for(session, user.id)
        assert projection is not None
        payload = service.projection_payload(projection)
        assert not set(payload) & PROHIBITED_RECOMMENDATION_FIELDS
        serialised = service.json_value(payload).lower()
        for marker in ("@example.com", "self_introduction", "date_of_birth"):
            assert marker not in serialised


@pytest.mark.asyncio
async def test_a_draft_edit_does_not_change_the_recommendation_input() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, profile = await create_eligible_member(session, reviewer)
        before = await service.projection_for(session, user.id)

        await profile_service.update_fields(session, user, {"lifestyle.alcohol_use_code": "social"})
        await session.commit()

        after = await service.projection_for(session, user.id)
        assert before is not None and after is not None
        assert before["lifestyle_codes"] == after["lifestyle_codes"]


@pytest.mark.asyncio
async def test_pausing_a_profile_removes_the_projection_and_the_pool_entry() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, profile = await create_eligible_member(session, reviewer)

        await session.execute(
            text("UPDATE dating_profiles SET status='paused_by_user' WHERE id=:id"),
            {"id": profile["id"]},
        )
        await session.commit()
        await profile_service.rebuild_projection(session, profile["id"])
        entry = await service.rebuild_pool_entry(session, user.id)
        await session.commit()

        assert await service.projection_for(session, user.id) is None
        assert entry is None


@pytest.mark.asyncio
async def test_projection_versions_are_visible_to_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        user, _profile = await create_eligible_member(session, reviewer)
        entry = await service.pool_entry(session, user.id)
        projection = await service.projection_for(session, user.id)
        assert entry is not None and projection is not None
        assert entry["profile_projection_version"] == projection["projection_version"]
        assert entry["preference_version"] == projection["preference_version"]
        assert entry["privacy_settings_version"] == projection["privacy_settings_version"]
