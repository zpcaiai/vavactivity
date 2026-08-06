"""A double tap, a retry, and two devices."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import idempotency
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions.idempotency import IdempotencyOperation

from ..helpers import key, mutual_items, paired_members


@pytest.mark.asyncio
async def test_two_simultaneous_likes_create_one_row() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)

    async def press() -> None:
        async with session_factory() as session:
            try:
                await like_service.create_like(
                    session,
                    viewer_user_id=viewer.id,
                    recommendation_item_id=forward,
                    idempotency_key=key(),
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(press(), press())

    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_likes WHERE actor_user_id=:actor "
                "AND target_user_id=:target AND status IN ('active','matched')"
            ),
            {"actor": viewer.id, "target": candidate.id},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_the_same_key_replays_the_first_answer() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        shared = key()
        payload = {"recommendation_item_id": str(forward)}

        replay = await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.LIKE,
            key=shared,
            payload=payload,
        )
        assert replay is None
        result = await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=shared,
        )
        await idempotency.complete(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.LIKE,
            key=shared,
            response=result,
        )
        await session.commit()

        second = await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.LIKE,
            key=shared,
            payload=payload,
        )
        assert second is not None
        assert second.payload["like_id"] == result["like_id"]


@pytest.mark.asyncio
async def test_the_same_key_with_a_different_body_is_refused() -> None:
    """Reusing a key for a different request is a client bug, not a retry."""
    async with session_factory() as session:
        viewer, _candidate = await paired_members(session)
        shared = key()
        await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.SKIP,
            key=shared,
            payload={"skip_type": "not_now"},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await idempotency.begin(
                session,
                user_id=viewer.id,
                operation=IdempotencyOperation.SKIP,
                key=shared,
                payload={"skip_type": "not_interested"},
            )
        assert excinfo.value.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


@pytest.mark.asyncio
async def test_one_key_can_be_reused_across_different_operations() -> None:
    """Clients often derive one key per gesture; scoping avoids a collision."""
    async with session_factory() as session:
        viewer, _candidate = await paired_members(session)
        shared = key()
        first = await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.LIKE,
            key=shared,
            payload={"a": 1},
        )
        second = await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.SKIP,
            key=shared,
            payload={"a": 1},
        )
        await session.commit()
        assert first is None
        assert second is None


@pytest.mark.asyncio
async def test_an_in_progress_key_refuses_a_second_attempt() -> None:
    async with session_factory() as session:
        viewer, _candidate = await paired_members(session)
        shared = key()
        await idempotency.begin(
            session,
            user_id=viewer.id,
            operation=IdempotencyOperation.LIKE,
            key=shared,
            payload={"a": 1},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await idempotency.begin(
                session,
                user_id=viewer.id,
                operation=IdempotencyOperation.LIKE,
                key=shared,
                payload={"a": 1},
            )
        assert excinfo.value.code == "IDEMPOTENT_REQUEST_IN_PROGRESS"
