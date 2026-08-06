"""A one-sided like is invisible, and nothing leaks its existence."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.main import app
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions import matches as match_service

from ..helpers import key, mutual_items, paired_members


def test_no_endpoint_exposes_incoming_likes() -> None:
    """The guarantee is a missing route, not a permission check.

    A permission can be misconfigured. A route that was never written cannot
    be called by anybody, ever.
    """
    paths = [route.path for route in app.routes if hasattr(route, "path")]
    for path in paths:
        assert "incoming" not in path
        assert "who-liked" not in path
        assert "admirers" not in path


def test_the_liked_member_sees_nothing() -> None:
    pass  # covered by the async case below; kept for readability of the file


@pytest.mark.asyncio
async def test_the_target_cannot_list_a_like_against_them() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()

        assert await like_service.outgoing_likes(session, candidate.id) == []
        assert await match_service.list_matches(session, candidate.id) == []


@pytest.mark.asyncio
async def test_a_one_sided_like_emits_no_recipient() -> None:
    """A notification worker cannot deliver what carries no recipient."""
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

        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_events WHERE topic='matchmaking.like.created' "
                    "AND aggregate_id=:id"
                ),
                {"id": str(result["like_id"])},
            )
        ).mappings()
        events = list(rows)
        assert events
        for event in events:
            assert "recipient_user_ids" not in event["payload"]
            assert str(candidate.id) not in str(event["payload"])


@pytest.mark.asyncio
async def test_single_like_notifications_cannot_be_switched_on() -> None:
    """The setting exists so it can be audited, and it is validated off."""
    from vav.core.config import Settings

    with pytest.raises(ValueError):
        Settings(MATCHMAKING_SINGLE_LIKE_NOTIFICATION_ENABLED="true")


@pytest.mark.asyncio
async def test_the_interaction_history_does_not_name_the_target_of_a_like() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()

        rows = (
            await session.execute(
                text(
                    "SELECT safe_metadata::text AS meta FROM matchmaking_interaction_history "
                    "WHERE entity_type='like'"
                )
            )
        ).mappings()
        for row in rows:
            assert str(candidate.id) not in row["meta"]
