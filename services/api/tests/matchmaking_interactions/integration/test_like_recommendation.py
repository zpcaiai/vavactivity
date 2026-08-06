"""Liking a real recommendation item."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions.domain import LikeStatus, canonical_pair

from ..helpers import key, paired_members, recommendation_item_for


@pytest.mark.asyncio
async def test_a_like_records_a_one_sided_choice() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)

        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            idempotency_key=key(),
        )
        await session.commit()

        assert result["outcome"] == "one_sided"
        assert result["mutual_match_id"] is None
        status = await session.scalar(
            text("SELECT status FROM matchmaking_likes WHERE id=:id"),
            {"id": result["like_id"]},
        )
        assert status == LikeStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_a_like_creates_the_canonical_pair() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            idempotency_key=key(),
        )
        await session.commit()

        low, high = canonical_pair(viewer.id, candidate.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_pairs WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_the_recommendation_item_is_marked_acted() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            idempotency_key=key(),
        )
        await session.commit()
        status = await session.scalar(
            text("SELECT status FROM recommendation_items WHERE id=:id"), {"id": item}
        )
        assert status == "acted"


@pytest.mark.asyncio
async def test_a_member_cannot_like_someone_elses_recommendation() -> None:
    """Not-found and not-yours give the same answer.

    Distinguishing them would let a member probe which item identifiers exist
    for other people.
    """
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=candidate.id,
                recommendation_item_id=item,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "RECOMMENDATION_ITEM_NOT_FOUND"
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_recommendation_cannot_be_liked() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await session.execute(
            text(
                "UPDATE recommendation_items SET expires_at=now() - interval '1 day' WHERE id=:id"
            ),
            {"id": item},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=item,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "RECOMMENDATION_ITEM_EXPIRED"


@pytest.mark.asyncio
async def test_an_already_acted_item_cannot_be_liked_again() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            idempotency_key=key(),
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=item,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "RECOMMENDATION_ITEM_NOT_ACTIONABLE"


@pytest.mark.asyncio
async def test_the_outgoing_list_shows_only_the_members_own_choices() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        item = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=item,
            idempotency_key=key(),
        )
        await session.commit()

        mine = await like_service.outgoing_likes(session, viewer.id)
        theirs = await like_service.outgoing_likes(session, candidate.id)
        assert len(mine) == 1
        # The member who was liked sees nothing at all.
        assert theirs == []
