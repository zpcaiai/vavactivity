"""Run the offline recommendation evaluation against the active strategy."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.recommendations.evaluation import run

DATASET_CODE = "recommendation-baseline-synthetic"


async def run_recommendation_evaluation() -> None:
    async with session_factory() as session:
        dataset_id = await session.scalar(
            text("SELECT id FROM recommendation_evaluation_datasets WHERE dataset_code=:code"),
            {"code": DATASET_CODE},
        )
        strategy_id = await session.scalar(
            text("SELECT id FROM recommendation_strategies WHERE status='active' LIMIT 1")
        )
        if dataset_id is None or strategy_id is None:
            print("Seed the evaluation dataset and strategy first.")
            return
        actor_id = await session.scalar(text("SELECT id FROM users ORDER BY created_at LIMIT 1"))
        actor = await session.get(User, UUID(str(actor_id)))
        assert actor is not None
        result = await run(
            session, actor, dataset_id=UUID(str(dataset_id)), strategy_id=UUID(str(strategy_id))
        )
    status = "PASSED" if result["passed"] else "BLOCKED"
    print(f"Recommendation evaluation {status}")
    print(f"  correctness: {result['correctness_metrics']}")
    print(f"  ranking:     {result['ranking_metrics']}")
    print(f"  coverage:    {result['coverage_metrics']}")
    print(f"  fairness:    {result['fairness_metrics']}")
    if result["guardrail_failures"]:
        print(f"  guardrail failures: {result['guardrail_failures']}")


if __name__ == "__main__":
    asyncio.run(run_recommendation_evaluation())
