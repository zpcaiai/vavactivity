"""Member preferences drive both filtering and scoring."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.recommendations import service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_hard_criteria_filter_the_candidate_out() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )

        matched = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert any(item["candidate_user_id"] == candidate.id for item in matched["candidates"])

        await profile_service.replace_preferences(
            session,
            viewer,
            [
                {
                    "criterion_code": "age_range",
                    "operator": "range",
                    "desired_value": {"minimum": 20, "maximum": 25},
                    "importance": "required",
                    "hard_constraint": True,
                }
            ],
            allow_relaxation=False,
        )
        await session.commit()
        await profile_service.rebuild_projection(
            session, (await profile_service.require_profile(session, viewer.id))["id"]
        )
        await service.rebuild_pool_entry(session, viewer.id)
        await session.commit()

        filtered = await service.generate_candidates(session, viewer.id)
        await session.commit()
        assert all(item["candidate_user_id"] != candidate.id for item in filtered["candidates"])
        assert filtered["report"]["hard_constraint_failures"]


@pytest.mark.asyncio
async def test_preference_criteria_are_read_from_their_owner_only() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, viewer_profile = await create_eligible_member(session, reviewer)
        other, _ = await create_eligible_member(session, reviewer)

        await profile_service.replace_preferences(
            session,
            viewer,
            [
                {
                    "criterion_code": "city_code",
                    "operator": "equals",
                    "desired_value": "shanghai",
                    "importance": "important",
                    "hard_constraint": False,
                }
            ],
            allow_relaxation=False,
        )
        await session.commit()
        await profile_service.rebuild_projection(session, viewer_profile["id"])
        await session.commit()

        viewer_criteria = await service.preference_criteria(session, viewer.id)
        other_criteria = await service.preference_criteria(session, other.id)
        assert [item["criterion_code"] for item in viewer_criteria] == ["city_code"]
        assert "city_code" not in [item["criterion_code"] for item in other_criteria]


@pytest.mark.asyncio
async def test_directional_scores_are_stored_for_both_directions() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1991, gender="male", partner_genders=("female",)
        )
        result = await service.generate_candidates(session, viewer.id)
        await session.commit()
        pair = next(
            item for item in result["candidates"] if item["candidate_user_id"] == candidate.id
        )
        forward = await service.directional_score_row(
            session, pair_id=pair["candidate_pair_id"], source_user_id=viewer.id
        )
        reverse = await service.directional_score_row(
            session, pair_id=pair["candidate_pair_id"], source_user_id=candidate.id
        )
        assert forward is not None and reverse is not None
        assert 0 <= forward["total_score_bps"] <= 10_000
        assert forward["scoring_policy_version"] == reverse["scoring_policy_version"]
