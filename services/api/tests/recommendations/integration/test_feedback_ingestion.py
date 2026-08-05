"""Feedback ingestion, cooldowns, safety removal and member tuning."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import batches, feedback, service
from vav.modules.recommendations.domain import canonical_pair

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


async def _viewer_and_item(session):
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
async def test_duplicate_feedback_is_processed_once() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        first = await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="viewed",
            recommendation_item_id=item["id"],
            from_member=True,
        )
        await session.commit()
        second = await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="viewed",
            recommendation_item_id=item["id"],
            from_member=True,
        )
        await session.commit()
        assert first["recorded"] and not second["recorded"]


@pytest.mark.asyncio
async def test_a_skip_creates_a_cooldown_not_a_permanent_rule() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="skipped",
            recommendation_item_id=item["id"],
            reason_code="lifestyle_not_suitable",
            source_module="interactions",
        )
        await session.commit()

        low, high = canonical_pair(viewer.id, item["recommended_user_id"])
        row = (
            (
                await session.execute(
                    text(
                        "SELECT exclusion_type, expires_at FROM recommendation_pair_exclusions "
                        "WHERE user_low_id=:low AND user_high_id=:high AND released_at IS NULL"
                    ),
                    {"low": low, "high": high},
                )
            )
            .mappings()
            .first()
        )
        assert row is not None
        assert row["exclusion_type"] == "skip_cooldown"
        assert row["expires_at"] is not None


@pytest.mark.asyncio
async def test_a_block_removes_the_candidate_immediately_and_permanently() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="blocked",
            recommendation_item_id=item["id"],
            source_module="moderation",
        )
        await session.commit()

        low, high = canonical_pair(viewer.id, item["recommended_user_id"])
        row = (
            (
                await session.execute(
                    text(
                        "SELECT exclusion_type, expires_at FROM recommendation_pair_exclusions "
                        "WHERE user_low_id=:low AND user_high_id=:high AND exclusion_type='safety_block'"
                    ),
                    {"low": low, "high": high},
                )
            )
            .mappings()
            .first()
        )
        assert row is not None and row["expires_at"] is None

        status = await session.scalar(
            text("SELECT status FROM recommendation_items WHERE id=:id"), {"id": item["id"]}
        )
        assert status == "invalidated"


@pytest.mark.asyncio
async def test_members_cannot_record_interaction_feedback_directly() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        with pytest.raises(VavError) as error:
            await feedback.ingest(
                session,
                viewer_user_id=viewer.id,
                recommended_user_id=item["recommended_user_id"],
                feedback_type="liked",
                recommendation_item_id=item["id"],
                from_member=True,
            )
        assert error.value.code == "RECOMMENDATION_FEEDBACK_NOT_MEMBER_OWNED"


@pytest.mark.asyncio
async def test_negative_reasons_are_encrypted_and_never_returned_in_aggregates() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="not_relevant",
            recommendation_item_id=item["id"],
            reason_code="faith_expectations_differ",
            reason_details="A private note that must never be shown to the other member.",
            from_member=True,
        )
        await session.commit()

        stored = await session.scalar(
            text(
                "SELECT reason_details_encrypted FROM recommendation_feedback_events "
                "WHERE viewer_user_id=:viewer ORDER BY received_at DESC LIMIT 1"
            ),
            {"viewer": viewer.id},
        )
        assert stored is not None and "private note" not in str(stored)
        summary = await feedback.feedback_summary(session)
        assert "private note" not in str(summary)


@pytest.mark.asyncio
async def test_personalisation_can_be_disabled_and_reset() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="not_relevant",
            recommendation_item_id=item["id"],
            reason_code="location_not_suitable",
            from_member=True,
        )
        await session.commit()
        tuned = await service.tuning_profile(session, viewer.id)
        assert tuned["feature_weight_adjustments"]

        await feedback.update_tuning(session, viewer.id, feedback_personalization_enabled=False)
        await session.commit()
        disabled = await service.tuning_profile(session, viewer.id)
        assert not disabled["feedback_personalization_enabled"]
        assert disabled["feature_weight_adjustments"] == {}

        await feedback.reset_tuning(session, viewer.id)
        await session.commit()
        reset = await service.tuning_profile(session, viewer.id)
        assert reset["feature_weight_adjustments"] == {}
        assert reset["tuning_version"] > tuned["tuning_version"]


@pytest.mark.asyncio
async def test_disabled_personalisation_stops_further_weight_updates() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        viewer, item = await _viewer_and_item(session)
        await feedback.update_tuning(session, viewer.id, feedback_personalization_enabled=False)
        await session.commit()

        await feedback.ingest(
            session,
            viewer_user_id=viewer.id,
            recommended_user_id=item["recommended_user_id"],
            feedback_type="not_relevant",
            recommendation_item_id=item["id"],
            reason_code="faith_expectations_differ",
            from_member=True,
        )
        await session.commit()
        profile = await service.tuning_profile(session, viewer.id)
        assert profile["feature_weight_adjustments"] == {}
