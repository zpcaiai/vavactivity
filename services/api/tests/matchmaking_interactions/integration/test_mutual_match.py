"""Reciprocal likes, one match, one notification."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions.domain import (
    LikeStatus,
    MutualMatchStatus,
    PairStatus,
    canonical_pair,
)

from ..helpers import key, mutual_items, paired_members, reach_mutual_match


@pytest.mark.asyncio
async def test_one_like_alone_creates_no_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _backward = await mutual_items(session, viewer, candidate)
        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        assert result["outcome"] == "one_sided"

        low, high = canonical_pair(viewer.id, candidate.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_mutual_matches "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_the_reciprocal_like_creates_the_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, backward = await mutual_items(session, viewer, candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        second = await like_service.create_like(
            session,
            viewer_user_id=candidate.id,
            recommendation_item_id=backward,
            idempotency_key=key(),
        )
        await session.commit()

        assert second["outcome"] == "mutual_match"
        assert second["mutual_match_id"] is not None


@pytest.mark.asyncio
async def test_both_likes_become_matched() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await reach_mutual_match(session, viewer, candidate)

        statuses = (
            await session.execute(
                text(
                    "SELECT status FROM matchmaking_likes WHERE "
                    "(actor_user_id=:a AND target_user_id=:b) OR "
                    "(actor_user_id=:b AND target_user_id=:a)"
                ),
                {"a": viewer.id, "b": candidate.id},
            )
        ).scalars()
        values = list(statuses)
        assert len(values) == 2
        assert set(values) == {LikeStatus.MATCHED.value}


@pytest.mark.asyncio
async def test_the_pair_records_the_active_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        low, high = canonical_pair(viewer.id, candidate.id)
        row = (
            await session.execute(
                text(
                    "SELECT status, active_mutual_match_id FROM matchmaking_pairs "
                    "WHERE user_low_id=:low AND user_high_id=:high"
                ),
                {"low": low, "high": high},
            )
        ).mappings()
        pair = row.one()
        assert pair["status"] == PairStatus.MUTUAL_MATCHED.value
        assert pair["active_mutual_match_id"] == match["id"]


@pytest.mark.asyncio
async def test_the_match_notification_is_emitted_once() -> None:
    """Both members are recipients of a single event, not one event each."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_events "
                    "WHERE topic='matchmaking.mutual_match.created' AND aggregate_id=:id"
                ),
                {"id": str(match["id"])},
            )
        ).mappings()
        events = list(rows)
        assert len(events) == 1
        recipients = events[0]["payload"]["recipient_user_ids"]
        assert set(recipients) == {str(viewer.id), str(candidate.id)}


@pytest.mark.asyncio
async def test_a_member_can_close_the_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        result = await match_service.close_match(
            session, user_id=viewer.id, match_id=match["id"], reason_code="changed_mind"
        )
        await session.commit()
        assert result["status"] == MutualMatchStatus.CLOSED.value


@pytest.mark.asyncio
async def test_closing_is_idempotent() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        await match_service.close_match(session, user_id=viewer.id, match_id=match["id"])
        await session.commit()
        again = await match_service.close_match(session, user_id=candidate.id, match_id=match["id"])
        await session.commit()
        assert again["status"] == MutualMatchStatus.CLOSED.value


@pytest.mark.asyncio
async def test_the_match_view_carries_no_internal_score() -> None:
    """A member learns that they matched, not what the engine thought."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await reach_mutual_match(session, viewer, candidate)
        rows = await match_service.list_matches(session, viewer.id)
        assert rows
        for row in rows:
            for forbidden in (
                "viewer_to_candidate_score_bps",
                "candidate_to_viewer_score_bps",
                "bidirectional_score_bps",
                "confidence_bps",
            ):
                assert forbidden not in row
