"""Service-level response contracts for the SOC-001 follow graph."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from vav.modules.attendee_social import service


def _session_with_rows(rows: list[dict[str, object]]) -> AsyncMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("loader", "edge_column"),
    [
        (service.list_following, "f.followee_id AS user_id"),
        (service.list_followers, "f.follower_id AS user_id"),
    ],
)
async def test_follow_lists_return_server_computed_mutuality_and_relation_kind(
    loader: object, edge_column: str
) -> None:
    followed_at = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    session = _session_with_rows(
        [
            {"user_id": UUID(int=2), "followed_at": followed_at, "is_mutual": True},
            {"user_id": UUID(int=3), "followed_at": followed_at, "is_mutual": False},
        ]
    )

    items = await loader(session, user_id=UUID(int=1), limit=200)  # type: ignore[operator]

    assert items == [
        {
            "user_id": str(UUID(int=2)),
            "followed_at": followed_at,
            "is_mutual": True,
            "relation_kind": "follow",
        },
        {
            "user_id": str(UUID(int=3)),
            "followed_at": followed_at,
            "is_mutual": False,
            "relation_kind": "follow",
        },
    ]
    statement, parameters = session.execute.await_args.args
    sql = str(statement)
    assert edge_column in sql
    assert "EXISTS (SELECT 1 FROM social_follows reverse_edge" in sql
    assert "reverse_edge.state='active'" in sql
    assert parameters == {"user_id": str(UUID(int=1)), "limit": 200}


@pytest.mark.asyncio
async def test_unfollow_response_is_explicitly_a_follow_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "follow_graph_enabled", lambda: None)
    session = AsyncMock()
    session.scalar.return_value = None

    result = await service.unfollow_member(
        session, follower_id=UUID(int=1), followee_id=UUID(int=2)
    )

    assert result["relation_kind"] == "follow"
    assert result["action"] == "unchanged"
