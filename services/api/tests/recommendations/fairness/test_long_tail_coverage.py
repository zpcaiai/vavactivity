"""Long-tail profiles get a chance inside the qualified set."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.core.database import session_factory
from vav.modules.recommendations import batches

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_coverage_is_reported_against_the_eligible_pool() -> None:
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
        await batches.record_exposure(
            session,
            viewer_id=viewer.id,
            item_id=items[0]["id"],
            exposure_type="card_visible",
            duration_ms=2_000,
        )
        await session.commit()

        overview = await batches.exposure_overview(session)
        assert overview["eligible_profiles"] > 0
        assert overview["exposed_profiles"] >= 1
        assert overview["never_exposed_profiles"] == (
            overview["eligible_profiles"] - overview["exposed_profiles"]
        )
        assert 0 <= overview["coverage_ratio_bps"] <= 10_000
