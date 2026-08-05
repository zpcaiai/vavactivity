"""Strategy release gating."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import experiments, service
from vav.modules.recommendations.evaluation import RELEASE_BLOCKING_METRICS
from vav.modules.recommendations.strategy import baseline_strategy_payload

from ..helpers import create_reviewer_once, ensure_strategy


def _version() -> str:
    """Unique semantic version so repeated local runs never collide."""
    return f"9.{uuid4().int % 100000}.0"


async def _draft(session, version: str):
    payload = baseline_strategy_payload()
    payload["semantic_version"] = version
    return await service.create_strategy(session, payload=payload, actor_id=None)


@pytest.mark.asyncio
async def test_a_strategy_cannot_be_approved_without_a_passing_evaluation() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        draft = await _draft(session, _version())
        await service.transition_strategy(
            session, strategy_id=draft["id"], target_status="evaluating", actor_id=None
        )
        with pytest.raises(VavError) as error:
            await service.transition_strategy(
                session, strategy_id=draft["id"], target_status="approved", actor_id=None
            )
        assert error.value.code == "RECOMMENDATION_EVALUATION_REQUIRED"
        await session.rollback()


@pytest.mark.asyncio
async def test_a_failing_evaluation_blocks_the_release_and_is_audited() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        draft = await _draft(session, _version())
        outcome = await experiments.run_evaluation(
            session,
            dataset_code="recommendation-baseline-synthetic",
            strategy_id=draft["id"],
            metrics={"hard_constraint_violation_rate_bps": 12},
        )
        await session.commit()
        assert not outcome["result"]["passed"]
        assert "hard_constraint_violation_rate_bps" in outcome["result"]["blocking_failures"]

        await service.transition_strategy(
            session, strategy_id=draft["id"], target_status="evaluating", actor_id=None
        )
        with pytest.raises(VavError):
            await service.transition_strategy(
                session, strategy_id=draft["id"], target_status="approved", actor_id=None
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_activation_requires_approval_by_a_different_person() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        draft = await _draft(session, _version())
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
            session, strategy_id=draft["id"], target_status="approved", actor_id=reviewer.id
        )
        await session.commit()

        with pytest.raises(VavError) as error:
            await service.transition_strategy(
                session, strategy_id=draft["id"], target_status="active", actor_id=reviewer.id
            )
        assert error.value.code == "RECOMMENDATION_STRATEGY_SELF_ACTIVATION"
        await session.rollback()


@pytest.mark.asyncio
async def test_activating_a_new_version_supersedes_the_previous_one() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        approver = await create_reviewer_once(session)
        releaser = await create_reviewer_once(session)
        previous = await service.active_strategy(session)

        draft = await _draft(session, _version())
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

        current = await service.active_strategy(session)
        assert current["id"] == draft["id"]
        superseded = await service.strategy_by_id(session, previous["id"])
        assert superseded["status"] == "superseded"
