"""Strategy rollback restores the previous active version."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import experiments, service
from vav.modules.recommendations.evaluation import RELEASE_BLOCKING_METRICS
from vav.modules.recommendations.strategy import baseline_strategy_payload

from ..helpers import create_reviewer_once, ensure_strategy


def _version() -> str:
    """Unique semantic version so repeated local runs never collide."""
    return f"9.{uuid4().int % 100000}.0"


async def _release(session, version: str):
    approver = await create_reviewer_once(session)
    releaser = await create_reviewer_once(session)
    payload = baseline_strategy_payload()
    payload["semantic_version"] = version
    draft = await service.create_strategy(session, payload=payload, actor_id=None)
    await experiments.run_evaluation(
        session,
        dataset_code="recommendation-baseline-synthetic",
        strategy_id=draft["id"],
        metrics={metric: 0 for metric in RELEASE_BLOCKING_METRICS},
    )
    await service.transition_strategy(
        session, strategy_id=draft["id"], target_status="evaluating", actor_id=None
    )
    await service.transition_strategy(
        session, strategy_id=draft["id"], target_status="approved", actor_id=approver.id
    )
    await service.transition_strategy(
        session, strategy_id=draft["id"], target_status="active", actor_id=releaser.id
    )
    await session.commit()
    return draft


@pytest.mark.asyncio
async def test_rollback_marks_the_strategy_and_is_audited() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        released = await _release(session, _version())
        actor = await create_reviewer_once(session)

        await service.transition_strategy(
            session,
            strategy_id=released["id"],
            target_status="rolled_back",
            actor_id=actor.id,
            reason="guardrail regression",
        )
        await session.commit()

        current = await service.strategy_by_id(session, released["id"])
        assert current["status"] == "rolled_back"
        audited = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_audit_events "
                "WHERE subject_id=:id AND event_type='recommendation.strategy.rolled_back'"
            ),
            {"id": released["id"]},
        )
        assert int(audited or 0) == 1


@pytest.mark.asyncio
async def test_only_one_strategy_stays_active_per_code() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        await _release(session, _version())
        active = await session.scalar(
            text("SELECT count(*) FROM recommendation_strategies WHERE status='active'")
        )
        assert int(active or 0) == 1
