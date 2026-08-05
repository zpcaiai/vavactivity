"""A profile change during a batch's life invalidates the frozen item."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.recommendations import batches, service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_a_privacy_change_invalidates_an_unseen_item() -> None:
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
        before = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert before
        candidate_id = before[0]["recommended_user_id"]
        candidate_profile_id = await session.scalar(
            text("SELECT id FROM dating_profiles WHERE user_id=:id"), {"id": candidate_id}
        )

        await session.execute(
            text(
                "UPDATE user_privacy_settings SET settings_version = settings_version + 1 WHERE user_id=:id"
            ),
            {"id": candidate_id},
        )
        await session.commit()
        await profile_service.rebuild_projection(session, candidate_profile_id)
        await service.rebuild_pool_entry(session, candidate_id)
        await session.commit()

        after = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert all(item["recommended_user_id"] != candidate_id for item in after)

        reason = await session.scalar(
            text(
                "SELECT invalidation_reason FROM recommendation_items "
                "WHERE viewer_user_id=:viewer AND recommended_user_id=:candidate"
            ),
            {"viewer": viewer.id, "candidate": candidate_id},
        )
        assert reason in {"privacy_changed", "profile_updated", "candidate_not_eligible"}
