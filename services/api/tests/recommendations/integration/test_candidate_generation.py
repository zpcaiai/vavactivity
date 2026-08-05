"""Candidate generation, exclusions and canonical pairs."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import canonical_pair

from ..helpers import block_pair, create_eligible_member, create_reviewer_once, ensure_strategy


async def _pair_of_members(session):
    reviewer = await create_reviewer_once(session)
    viewer, _ = await create_eligible_member(
        session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
    )
    candidate, _ = await create_eligible_member(
        session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
    )
    return viewer, candidate


@pytest.mark.asyncio
async def test_a_compatible_pair_is_generated_once_and_canonically() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, candidate = await _pair_of_members(session)

        first = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert any(item["candidate_user_id"] == candidate.id for item in first["candidates"])

        # Generating from the other side must not create a second pair record.
        await service.generate_candidates(session, candidate.id)
        await session.commit()

        low, high = canonical_pair(viewer.id, candidate.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_candidate_pairs WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_a_member_is_never_recommended_to_themselves() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _pair_of_members(session)
        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != viewer.id for item in result["candidates"])


@pytest.mark.asyncio
async def test_a_blocked_pair_never_becomes_a_candidate() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, candidate = await _pair_of_members(session)
        await block_pair(session, viewer.id, candidate.id)

        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != candidate.id for item in result["candidates"])
        assert result["report"]["excluded_by_safety"] >= 1


@pytest.mark.asyncio
async def test_an_active_relationship_excludes_the_pair() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, candidate = await _pair_of_members(session)
        low, high = canonical_pair(viewer.id, candidate.id)
        await session.execute(
            text(
                "INSERT INTO recommendation_pair_exclusions (user_low_id,user_high_id,exclusion_type,source_module) "
                "VALUES (:low,:high,'active_relationship','matchmaking')"
            ),
            {"low": low, "high": high},
        )
        await session.commit()

        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != candidate.id for item in result["candidates"])
        assert result["report"]["excluded_by_interaction"] >= 1


@pytest.mark.asyncio
async def test_incompatible_relationship_eligibility_is_filtered_before_scoring() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, gender="female", partner_genders=("male",)
        )
        same_gender, _ = await create_eligible_member(
            session, reviewer, gender="female", partner_genders=("male",)
        )
        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != same_gender.id for item in result["candidates"])


@pytest.mark.asyncio
async def test_pool_ineligibility_invalidates_existing_candidates() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, candidate = await _pair_of_members(session)
        await service.generate_candidates(session, viewer.id)
        await session.commit()

        await service.update_user_settings(session, candidate.id, {"recommendations_paused": True})
        await session.commit()

        low, high = canonical_pair(viewer.id, candidate.id)
        status = await session.scalar(
            text(
                "SELECT status FROM recommendation_candidate_pairs WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert status == "invalidated"


@pytest.mark.asyncio
async def test_generation_reports_each_funnel_stage() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _pair_of_members(session)
        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        report = result["report"]
        for key in (
            "pool_size",
            "recalled",
            "excluded_by_safety",
            "excluded_by_interaction",
            "hard_constraint_failed",
            "below_minimum_score",
            "eligible",
        ):
            assert key in report
