"""Skipping, cooldowns and what a skip does not do."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions.domain import SkipStatus, canonical_pair

from ..helpers import key, paired_members, recommendation_item_for


@pytest.mark.asyncio
async def test_a_skip_starts_the_cooldown_for_its_type() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)

        short = await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            skip_type="not_now",
            reason_code=None,
            reason_details=None,
            idempotency_key=key(),
        )
        await session.commit()
        assert short["skip_type"] == "not_now"
        assert short["cooldown_until"] is not None


@pytest.mark.asyncio
async def test_not_interested_waits_longer_than_not_now() -> None:
    async with session_factory() as session:
        viewer_a, candidate_a = await paired_members(session)
        item_a = await recommendation_item_for(session, viewer=viewer_a, candidate=candidate_a)
        short = await like_service.create_skip(
            session,
            viewer_user_id=viewer_a.id,
            recommendation_item_id=item_a,
            skip_type="not_now",
            reason_code=None,
            reason_details=None,
            idempotency_key=key(),
        )
        await session.commit()

        viewer_b, candidate_b = await paired_members(session)
        item_b = await recommendation_item_for(session, viewer=viewer_b, candidate=candidate_b)
        long = await like_service.create_skip(
            session,
            viewer_user_id=viewer_b.id,
            recommendation_item_id=item_b,
            skip_type="not_interested",
            reason_code=None,
            reason_details=None,
            idempotency_key=key(),
        )
        await session.commit()
        assert long["cooldown_until"] > short["cooldown_until"]


@pytest.mark.asyncio
async def test_the_free_text_reason_is_encrypted_at_rest() -> None:
    """The reason belongs to its author and the engine, nobody else."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        secret = "distance is the real problem for me"
        result = await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            skip_type="not_now",
            reason_code="distance",
            reason_details=secret,
            idempotency_key=key(),
        )
        await session.commit()

        stored = await session.scalar(
            text("SELECT reason_details_encrypted FROM matchmaking_skips WHERE id=:id"),
            {"id": result["skip_id"]},
        )
        assert stored is not None
        assert secret not in stored


@pytest.mark.asyncio
async def test_the_skip_reason_never_reaches_the_interaction_history() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            skip_type="not_interested",
            reason_code="lifestyle",
            reason_details="they smoke",
            idempotency_key=key(),
        )
        await session.commit()

        rows = (
            await session.execute(
                text(
                    "SELECT safe_metadata::text AS meta, reason_code FROM matchmaking_interaction_history "
                    "WHERE entity_type='skip'"
                )
            )
        ).mappings()
        for row in rows:
            assert "smoke" not in row["meta"]
            assert row["reason_code"] is None


@pytest.mark.asyncio
async def test_a_skip_publishes_a_pair_exclusion_that_expires() -> None:
    """The pair is delayed, not removed: the exclusion carries an end date."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            skip_type="not_now",
            reason_code=None,
            reason_details=None,
            idempotency_key=key(),
        )
        await session.commit()

        low, high = canonical_pair(viewer.id, candidate.id)
        row = (
            await session.execute(
                text(
                    "SELECT exclusion_type, expires_at FROM recommendation_pair_exclusions "
                    "WHERE user_low_id=:low AND user_high_id=:high AND released_at IS NULL"
                ),
                {"low": low, "high": high},
            )
        ).mappings()
        exclusion = row.first()
        assert exclusion is not None
        assert exclusion["exclusion_type"] == "skip"
        assert exclusion["expires_at"] is not None


@pytest.mark.asyncio
async def test_undoing_a_skip_releases_the_exclusion() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        result = await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            skip_type="not_now",
            reason_code=None,
            reason_details=None,
            idempotency_key=key(),
        )
        await session.commit()

        undone = await like_service.withdraw_skip(
            session, viewer_user_id=viewer.id, skip_id=result["skip_id"]
        )
        await session.commit()
        assert undone["status"] == SkipStatus.WITHDRAWN.value

        low, high = canonical_pair(viewer.id, candidate.id)
        active = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_pair_exclusions "
                "WHERE user_low_id=:low AND user_high_id=:high AND exclusion_type='skip' "
                "AND released_at IS NULL"
            ),
            {"low": low, "high": high},
        )
        assert int(active or 0) == 0


@pytest.mark.asyncio
async def test_an_unsupported_skip_type_is_rejected() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        with pytest.raises(VavError) as excinfo:
            await like_service.create_skip(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=item,
                skip_type="block",
                reason_code=None,
                reason_details=None,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "SKIP_TYPE_INVALID"


@pytest.mark.asyncio
async def test_an_unsupported_reason_code_is_rejected() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        with pytest.raises(VavError) as excinfo:
            await like_service.create_skip(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=item,
                skip_type="not_now",
                reason_code="they_are_ugly",
                reason_details=None,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "SKIP_REASON_INVALID"
