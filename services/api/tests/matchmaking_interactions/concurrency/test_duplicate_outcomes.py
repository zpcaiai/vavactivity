import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import likes, service

from ..helpers import create_interaction_fixture


async def _like_and_commit(*, user_id: UUID, item_id: UUID) -> dict[str, object]:
    async with session_factory() as session:
        result = await likes.create_like(
            session,
            viewer_user_id=user_id,
            recommendation_item_id=item_id,
            idempotency_key=f"race-like-{uuid4()}",
        )
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_concurrent_reciprocal_likes_create_exactly_one_match() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        first_id = fixture.first.id
        second_id = fixture.second.id
        first_item_id = fixture.first_item_id
        second_item_id = fixture.second_item_id

    results = await asyncio.gather(
        _like_and_commit(user_id=first_id, item_id=first_item_id),
        _like_and_commit(user_id=second_id, item_id=second_item_id),
    )
    assert sorted(str(result["outcome"]) for result in results) == [
        "mutual_match",
        "one_sided",
    ]
    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_mutual_matches m "
                "JOIN matchmaking_pairs p ON p.id=m.pair_id "
                "WHERE p.user_low_id IN (:first,:second) "
                "AND p.user_high_id IN (:first,:second)"
            ),
            {"first": first_id, "second": second_id},
        )
        event_count = await session.scalar(
            text(
                "SELECT count(*) FROM outbox_events o "
                "JOIN matchmaking_mutual_matches m ON m.id::text=o.aggregate_id "
                "JOIN matchmaking_pairs p ON p.id=m.pair_id "
                "WHERE o.topic='matchmaking.mutual_match.created' "
                "AND p.user_low_id IN (:first,:second) "
                "AND p.user_high_id IN (:first,:second)"
            ),
            {"first": first_id, "second": second_id},
        )
        assert count == 1
        assert event_count == 1


@pytest.mark.asyncio
async def test_repeated_like_returns_the_same_direction_without_duplication() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        first = await likes.create_like(
            session,
            viewer_user_id=fixture.first.id,
            recommendation_item_id=fixture.first_item_id,
            idempotency_key=f"like-{uuid4()}",
        )
        # HTTP idempotency normally replays before the service. Restoring the
        # card state here exercises the database/service duplicate boundary.
        await session.execute(
            text("UPDATE recommendation_items SET status='ready' WHERE id=:id"),
            {"id": fixture.first_item_id},
        )
        repeated = await likes.create_like(
            session,
            viewer_user_id=fixture.first.id,
            recommendation_item_id=fixture.first_item_id,
            idempotency_key=f"like-{uuid4()}",
        )
        pair = await service.ensure_pair(session, fixture.first.id, fixture.second.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_likes WHERE pair_id=:pair "
                "AND actor_user_id=:actor AND status IN ('active','matched')"
            ),
            {"pair": pair["id"], "actor": fixture.first.id},
        )
        assert repeated["like_id"] == first["like_id"]
        assert count == 1
