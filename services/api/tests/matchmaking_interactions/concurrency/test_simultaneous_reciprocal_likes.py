"""Two members pressing like at the same moment."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions.domain import LikeStatus, canonical_pair

from ..helpers import key, mutual_items, paired_members


async def _like(user_id, item_id) -> None:
    async with session_factory() as session:
        try:
            await like_service.create_like(
                session,
                viewer_user_id=user_id,
                recommendation_item_id=item_id,
                idempotency_key=key(),
            )
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.mark.asyncio
async def test_reciprocal_likes_at_once_create_exactly_one_match() -> None:
    """The pair row is the point of contention.

    Both transactions want to create the match. The one that takes the pair
    lock first creates it; the other finds it already there.
    """
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, backward = await mutual_items(session, viewer, candidate)

    await asyncio.gather(_like(viewer.id, forward), _like(candidate.id, backward))

    async with session_factory() as session:
        low, high = canonical_pair(viewer.id, candidate.id)
        matches = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_mutual_matches "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(matches or 0) == 1


@pytest.mark.asyncio
async def test_only_one_match_notification_is_emitted() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, backward = await mutual_items(session, viewer, candidate)

    await asyncio.gather(_like(viewer.id, forward), _like(candidate.id, backward))

    async with session_factory() as session:
        low, high = canonical_pair(viewer.id, candidate.id)
        match_id = await session.scalar(
            text(
                "SELECT id FROM matchmaking_mutual_matches "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        events = await session.scalar(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE topic='matchmaking.mutual_match.created' AND aggregate_id=:id"
            ),
            {"id": str(match_id)},
        )
        assert int(events or 0) == 1


@pytest.mark.asyncio
async def test_both_likes_end_up_matched_after_the_race() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, backward = await mutual_items(session, viewer, candidate)

    await asyncio.gather(_like(viewer.id, forward), _like(candidate.id, backward))

    async with session_factory() as session:
        statuses = list(
            (
                await session.execute(
                    text(
                        "SELECT status FROM matchmaking_likes WHERE "
                        "(actor_user_id=:a AND target_user_id=:b) OR "
                        "(actor_user_id=:b AND target_user_id=:a)"
                    ),
                    {"a": viewer.id, "b": candidate.id},
                )
            ).scalars()
        )
        assert len(statuses) == 2
        assert set(statuses) == {LikeStatus.MATCHED.value}


@pytest.mark.asyncio
async def test_the_pair_row_is_created_once_under_contention() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, backward = await mutual_items(session, viewer, candidate)

    await asyncio.gather(_like(viewer.id, forward), _like(candidate.id, backward))

    async with session_factory() as session:
        low, high = canonical_pair(viewer.id, candidate.id)
        pairs = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_pairs "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(pairs or 0) == 1
