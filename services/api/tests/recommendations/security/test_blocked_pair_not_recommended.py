"""Blocked pairs never reach a recommendation."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service
from vav.modules.recommendations.domain import canonical_pair

from ..helpers import block_pair, create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_a_blocked_pair_is_never_generated_or_shown() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        await block_pair(session, viewer.id, candidate.id)

        generated = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != candidate.id for item in generated["candidates"])

        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert all(item["recommended_user_id"] != candidate.id for item in items)


@pytest.mark.asyncio
async def test_a_permanent_safety_exclusion_survives_regeneration() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        low, high = canonical_pair(viewer.id, candidate.id)
        await session.execute(
            text(
                "INSERT INTO recommendation_pair_exclusions (user_low_id,user_high_id,exclusion_type,source_module) "
                "VALUES (:low,:high,'safety_block','moderation') ON CONFLICT DO NOTHING"
            ),
            {"low": low, "high": high},
        )
        await session.commit()

        for _ in range(2):
            generated = await service.generate_candidates(session, viewer.id)
            await session.commit()
            assert all(
                item["candidate_user_id"] != candidate.id for item in generated["candidates"]
            )
