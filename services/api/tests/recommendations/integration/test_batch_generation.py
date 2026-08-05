"""Batch generation, snapshots and daily limits."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import batches, service
from vav.modules.recommendations.batches import VISIBLE_SNAPSHOT_KEYS

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


async def _viewer_with_candidate(session):
    reviewer = await create_reviewer_once(session)
    viewer, _ = await create_eligible_member(
        session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
    )
    candidate, _ = await create_eligible_member(
        session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
    )
    return viewer, candidate


@pytest.mark.asyncio
async def test_a_member_receives_a_daily_batch_bound_to_its_versions() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, candidate = await _viewer_with_candidate(session)

        batch = await batches.generate_batch(session, viewer.id)
        await session.commit()

        assert batch["status"] == "active"
        assert batch["generated_size"] >= 1
        entry = await service.pool_entry(session, viewer.id)
        assert entry is not None
        assert batch["profile_projection_version"] == entry["profile_projection_version"]
        assert batch["preference_version"] == entry["preference_version"]
        assert batch["privacy_settings_version"] == entry["privacy_settings_version"]
        assert batch["ranking_seed"]


@pytest.mark.asyncio
async def test_repeating_generation_returns_the_same_batch() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        first = await batches.generate_batch(session, viewer.id)
        await session.commit()
        second = await batches.generate_batch(session, viewer.id)
        await session.commit()
        assert first["id"] == second["id"]

        count = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_batches WHERE user_id=:id AND batch_type='daily'"
            ),
            {"id": viewer.id},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_items_carry_only_the_approved_visible_snapshot() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        await batches.generate_batch(session, viewer.id)
        await session.commit()

        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert items
        for item in items:
            snapshot = item["visible_profile_snapshot"]
            assert set(snapshot) <= VISIBLE_SNAPSHOT_KEYS
            serialised = service.json_value(snapshot).lower()
            for marker in ("@example.com", "wechat", "date_of_birth", "object_key"):
                assert marker not in serialised


@pytest.mark.asyncio
async def test_ranking_results_are_recorded_with_separate_adjustments() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        batch = await batches.generate_batch(session, viewer.id)
        await session.commit()

        rows = (
            await session.execute(
                text(
                    "SELECT base_score_bps, adjusted_score_bps, final_rank FROM recommendation_rank_results "
                    "WHERE recommendation_batch_id=:id ORDER BY final_rank"
                ),
                {"id": batch["id"]},
            )
        ).mappings()
        results = [dict(row) for row in rows]
        assert results
        assert [row["final_rank"] for row in results] == list(range(1, len(results) + 1))
        for row in results:
            assert 0 <= row["base_score_bps"] <= 10_000
            assert 0 <= row["adjusted_score_bps"] <= 10_000


@pytest.mark.asyncio
async def test_a_paused_member_cannot_generate_a_batch() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        await service.update_user_settings(session, viewer.id, {"recommendations_paused": True})
        await session.commit()

        with pytest.raises(VavError) as error:
            await batches.generate_batch(session, viewer.id)
        assert error.value.code in {"RECOMMENDATION_NOT_ELIGIBLE", "RECOMMENDATION_PAUSED"}


@pytest.mark.asyncio
async def test_supplemental_batches_require_the_current_one_to_be_processed() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        await batches.generate_batch(session, viewer.id)
        await session.commit()

        with pytest.raises(VavError) as error:
            await batches.generate_batch(session, viewer.id, batch_type="supplemental")
        assert error.value.code == "RECOMMENDATION_BATCH_NOT_PROCESSED"


@pytest.mark.asyncio
async def test_the_daily_budget_is_consumed_by_generation() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, _candidate = await _viewer_with_candidate(session)
        batch = await batches.generate_batch(session, viewer.id)
        await session.commit()

        budget = await batches.budget_row(session, viewer.id, batch["created_at"].date())
        assert budget["current_received_count"] == batch["generated_size"]
        assert budget["current_received_count"] <= budget["daily_received_limit"]
