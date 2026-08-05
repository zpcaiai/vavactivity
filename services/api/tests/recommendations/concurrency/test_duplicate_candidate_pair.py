"""Concurrent candidate generation cannot duplicate a canonical pair."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import canonical_pair

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_both_directions_generating_at_once_produce_one_pair() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )

    async def generate(user_id):
        async with session_factory() as session:
            try:
                await service.generate_candidates(session, user_id)
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(generate(viewer.id), generate(candidate.id))

    async with session_factory() as session:
        low, high = canonical_pair(viewer.id, candidate.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_candidate_pairs "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(count or 0) == 1
