"""Batch activation, display-time rechecks, invalidation and expiry."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service

from ..helpers import block_pair, create_eligible_member, create_reviewer_once, ensure_strategy


async def _batch_with_items(session):
    reviewer = await create_reviewer_once(session)
    viewer, _ = await create_eligible_member(
        session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
    )
    candidate, _ = await create_eligible_member(
        session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
    )
    batch = await batches.generate_batch(session, viewer.id)
    await session.commit()
    return viewer, candidate, batch


@pytest.mark.asyncio
async def test_an_active_batch_is_returned_to_its_owner() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate, batch = await _batch_with_items(session)
        active = await batches.active_batch(session, viewer.id)
        assert active is not None and active["id"] == batch["id"]
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert items and all(item["viewer_user_id"] == viewer.id for item in items)


@pytest.mark.asyncio
async def test_a_block_created_after_generation_hides_the_item() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _seed_candidate, _batch = await _batch_with_items(session)
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        assert items
        candidate = items[0]["recommended_user_id"]

        await block_pair(session, viewer.id, candidate)
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()

        assert all(item["recommended_user_id"] != candidate for item in items)
        status = await session.scalar(
            text(
                "SELECT status FROM recommendation_items WHERE viewer_user_id=:viewer AND recommended_user_id=:candidate"
            ),
            {"viewer": viewer.id, "candidate": candidate},
        )
        assert status == "invalidated"


@pytest.mark.asyncio
async def test_a_paused_candidate_profile_hides_the_item() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _seed_candidate, _batch = await _batch_with_items(session)
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        assert items
        candidate = items[0]["recommended_user_id"]

        await service.update_user_settings(session, candidate, {"recommendations_paused": True})
        await session.commit()

        remaining = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert all(item["recommended_user_id"] != candidate for item in remaining)


@pytest.mark.asyncio
async def test_an_operator_can_invalidate_a_batch_with_a_reason() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate, batch = await _batch_with_items(session)
        await batches.invalidate_batch(session, batch["id"], reason="incorrect strategy version")
        await session.commit()

        status = await session.scalar(
            text("SELECT status FROM recommendation_batches WHERE id=:id"), {"id": batch["id"]}
        )
        assert status == "cancelled"
        assert await batches.viewer_items(session, viewer_id=viewer.id) == []
        audited = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_audit_events WHERE subject_id=:id "
                "AND event_type='recommendation.batch.invalidated'"
            ),
            {"id": batch["id"]},
        )
        assert int(audited or 0) >= 1


@pytest.mark.asyncio
async def test_expired_batches_stop_serving_items() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate, batch = await _batch_with_items(session)
        await session.execute(
            text(
                "UPDATE recommendation_batches SET expires_at = now() - interval '1 day' WHERE id=:id"
            ),
            {"id": batch["id"]},
        )
        await session.execute(
            text(
                "UPDATE recommendation_items SET expires_at = now() - interval '1 day' "
                "WHERE recommendation_batch_id=:id"
            ),
            {"id": batch["id"]},
        )
        await session.commit()

        expired = await batches.expire_batches(session)
        await session.commit()
        assert expired >= 1
        assert await batches.viewer_items(session, viewer_id=viewer.id) == []
