"""A member can only reach their own batches and items."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import batches, feedback

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_another_member_cannot_read_or_act_on_someone_elses_item() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        intruder, _ = await create_eligible_member(
            session, reviewer, birth_year=1994, gender="female", partner_genders=("male",)
        )
        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        item = items[0]

        assert await batches.viewer_items(session, viewer_id=intruder.id) != items

        with pytest.raises(VavError) as exposure_error:
            await batches.record_exposure(
                session,
                viewer_id=intruder.id,
                item_id=item["id"],
                exposure_type="card_visible",
                duration_ms=2_000,
            )
        assert exposure_error.value.code == "RECOMMENDATION_ITEM_NOT_FOUND"

        with pytest.raises(VavError) as feedback_error:
            await feedback.ingest(
                session,
                viewer_user_id=intruder.id,
                recommended_user_id=item["recommended_user_id"],
                feedback_type="profile_opened",
                recommendation_item_id=item["id"],
                from_member=True,
            )
        assert feedback_error.value.code == "RECOMMENDATION_ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_asking_for_another_members_batch_returns_nothing() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        intruder, _ = await create_eligible_member(
            session, reviewer, birth_year=1994, gender="female", partner_genders=("male",)
        )
        batch = await batches.generate_batch(session, viewer.id)
        await session.commit()

        stolen = await batches.viewer_items(session, viewer_id=intruder.id, batch_id=batch["id"])
        await session.commit()
        assert stolen == []
