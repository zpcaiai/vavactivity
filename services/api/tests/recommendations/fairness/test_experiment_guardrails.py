"""Experiment guardrails stop a treatment rather than optimise clicks."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import experiments, service
from vav.modules.recommendations.domain import ExperimentStatus

from ..helpers import create_reviewer_once, ensure_strategy


async def _experiment(session, *, code: str | None = None):
    strategy = await service.active_strategy(session)
    return await experiments.create_experiment(
        session,
        payload={
            "experiment_code": code or f"exp-{uuid4().hex[:12]}",
            "name": "Guardrail test",
            "hypothesis": "A different weighting improves qualified exposure.",
            "control_strategy_id": strategy["id"],
            "treatment_strategy_ids": [],
            "guardrail_thresholds": {"report_rate_bps": 100, "block_rate_bps": 100},
        },
        actor_id=None,
    )


@pytest.mark.asyncio
async def test_experiments_are_disabled_by_default() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        actor = await create_reviewer_once(session)
        experiment = await _experiment(session)
        await experiments.transition_experiment(
            session,
            experiment_id=experiment["id"],
            target_status=ExperimentStatus.APPROVED.value,
            actor_id=actor.id,
        )
        await session.commit()

        with pytest.raises(VavError) as error:
            await experiments.transition_experiment(
                session,
                experiment_id=experiment["id"],
                target_status=ExperimentStatus.RUNNING.value,
                actor_id=actor.id,
            )
        assert error.value.code == "RECOMMENDATION_EXPERIMENTS_DISABLED"
        await session.rollback()


@pytest.mark.asyncio
async def test_an_unapproved_experiment_cannot_start() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        experiment = await _experiment(session)
        await session.commit()
        with pytest.raises(VavError):
            await experiments.transition_experiment(
                session,
                experiment_id=experiment["id"],
                target_status=ExperimentStatus.RUNNING.value,
                actor_id=None,
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_a_breached_guardrail_is_reported() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        experiment = await _experiment(session)
        await session.commit()

        result = await experiments.check_guardrails(
            session,
            experiment_id=experiment["id"],
            metrics={"report_rate_bps": 900, "like_rate_bps": 9_000},
        )
        await session.commit()
        assert "report_rate_bps" in result["breached"]


@pytest.mark.asyncio
async def test_click_metrics_alone_do_not_clear_a_guardrail() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        experiment = await _experiment(session)
        await session.commit()
        result = await experiments.check_guardrails(
            session,
            experiment_id=experiment["id"],
            metrics={"like_rate_bps": 10_000, "block_rate_bps": 500},
        )
        await session.commit()
        assert result["breached"] == ["block_rate_bps"]


@pytest.mark.asyncio
async def test_assignment_is_stable_for_a_member() -> None:
    member = uuid4()
    assert experiments.assignment_hash("exp-code", member) == experiments.assignment_hash(
        "exp-code", member
    )
    assert experiments.assignment_hash("exp-code", member) != experiments.assignment_hash(
        "other-code", member
    )
