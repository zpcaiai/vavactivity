"""Withdrawing a like before and after a match."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions.domain import LikeStatus

from ..helpers import key, mutual_items, paired_members, reach_mutual_match


@pytest.mark.asyncio
async def test_an_unmatched_like_can_be_withdrawn() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()

        withdrawn = await like_service.withdraw_like(
            session, viewer_user_id=viewer.id, like_id=result["like_id"]
        )
        await session.commit()
        assert withdrawn["status"] == LikeStatus.WITHDRAWN.value


@pytest.mark.asyncio
async def test_withdrawal_frees_the_direction_for_a_later_like() -> None:
    """The partial unique index only covers active and matched rows."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        first = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        await like_service.withdraw_like(
            session, viewer_user_id=viewer.id, like_id=first["like_id"]
        )
        await session.commit()

        # A new recommendation of the same member can be liked again.
        await session.execute(
            text("UPDATE recommendation_items SET status='ready' WHERE id=:id"), {"id": forward}
        )
        await session.commit()
        second = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        assert second["like_id"] != first["like_id"]


@pytest.mark.asyncio
async def test_a_matched_like_cannot_be_withdrawn_directly() -> None:
    """The other member consented to the match, not to the like."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await reach_mutual_match(session, viewer, candidate)
        like_id = await session.scalar(
            text(
                "SELECT id FROM matchmaking_likes WHERE actor_user_id=:actor "
                "AND target_user_id=:target"
            ),
            {"actor": viewer.id, "target": candidate.id},
        )

        with pytest.raises(VavError) as excinfo:
            await like_service.withdraw_like(session, viewer_user_id=viewer.id, like_id=like_id)
        assert excinfo.value.code == "LIKE_ALREADY_MATCHED"
        assert excinfo.value.details == [{"action": "close_mutual_match"}]


@pytest.mark.asyncio
async def test_a_member_cannot_withdraw_someone_elses_like() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await like_service.withdraw_like(
                session, viewer_user_id=candidate.id, like_id=result["like_id"]
            )
        assert excinfo.value.code == "LIKE_NOT_FOUND"


@pytest.mark.asyncio
async def test_withdrawal_is_silent() -> None:
    """The target never knew about the like, so there is nothing to announce."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        await like_service.withdraw_like(
            session, viewer_user_id=viewer.id, like_id=result["like_id"]
        )
        await session.commit()

        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_events WHERE topic='matchmaking.like.withdrawn' "
                    "AND aggregate_id=:id"
                ),
                {"id": str(result["like_id"])},
            )
        ).mappings()
        for row in rows:
            assert "recipient_user_ids" not in row["payload"]
