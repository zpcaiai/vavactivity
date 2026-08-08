"""Exposure recording, idempotency and statistics."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import batches

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


async def _first_item(session):
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
    return viewer, items[0]


@pytest.mark.asyncio
async def test_a_card_impression_is_not_a_visible_exposure() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)
        total_before = await session.scalar(
            text(
                "SELECT total_exposures FROM recommendation_profile_exposure_stats WHERE user_id=:id"
            ),
            {"id": item["recommended_user_id"]},
        )

        result = await batches.record_exposure(
            session, viewer_id=viewer.id, item_id=item["id"], exposure_type="card_impression"
        )
        await session.commit()
        assert result["recorded"] and not result["counted_as_visible"]

        stats = await session.scalar(
            text(
                "SELECT total_exposures FROM recommendation_profile_exposure_stats WHERE user_id=:id"
            ),
            {"id": item["recommended_user_id"]},
        )
        assert int(stats or 0) == int(total_before or 0)


@pytest.mark.asyncio
async def test_a_visible_card_updates_the_item_and_the_statistics() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)

        result = await batches.record_exposure(
            session,
            viewer_id=viewer.id,
            item_id=item["id"],
            exposure_type="card_visible",
            duration_ms=2_000,
        )
        await session.commit()
        assert result["counted_as_visible"]

        status = await session.scalar(
            text("SELECT status FROM recommendation_items WHERE id=:id"), {"id": item["id"]}
        )
        assert status == "exposed"
        stats = await session.scalar(
            text(
                "SELECT total_exposures FROM recommendation_profile_exposure_stats WHERE user_id=:id"
            ),
            {"id": item["recommended_user_id"]},
        )
        assert int(stats or 0) >= 1


@pytest.mark.asyncio
async def test_repeating_the_same_exposure_event_is_recorded_once() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)
        first = await batches.record_exposure(
            session, viewer_id=viewer.id, item_id=item["id"], exposure_type="profile_opened"
        )
        await session.commit()
        second = await batches.record_exposure(
            session, viewer_id=viewer.id, item_id=item["id"], exposure_type="profile_opened"
        )
        await session.commit()
        assert first["recorded"] and not second["recorded"]
        assert second["reason_code"] == "duplicate_event"

        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_exposures WHERE recommendation_item_id=:id "
                "AND exposure_type='profile_opened'"
            ),
            {"id": item["id"]},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_opening_a_profile_marks_the_item_viewed() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)
        await batches.record_exposure(
            session, viewer_id=viewer.id, item_id=item["id"], exposure_type="profile_opened"
        )
        await session.commit()
        status = await session.scalar(
            text("SELECT status FROM recommendation_items WHERE id=:id"), {"id": item["id"]}
        )
        assert status == "viewed"


@pytest.mark.asyncio
async def test_an_invalidated_item_cannot_record_exposure() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)
        await session.execute(
            text("UPDATE recommendation_items SET status='invalidated' WHERE id=:id"),
            {"id": item["id"]},
        )
        await session.commit()
        with pytest.raises(VavError) as error:
            await batches.record_exposure(
                session,
                viewer_id=viewer.id,
                item_id=item["id"],
                exposure_type="card_visible",
                duration_ms=2_000,
            )
        assert error.value.code == "RECOMMENDATION_ITEM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_exposure_overview_reports_coverage() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _first_item(session)
        await batches.record_exposure(
            session,
            viewer_id=viewer.id,
            item_id=item["id"],
            exposure_type="card_visible",
            duration_ms=2_000,
        )
        await session.commit()
        overview = await batches.exposure_overview(session)
        assert overview["eligible_profiles"] >= 2
        assert 0 <= overview["coverage_ratio_bps"] <= 10_000
        assert 0 <= overview["exposure_gini_bps"] <= 10_000
