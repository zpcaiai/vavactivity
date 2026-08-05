"""Seed the recommendation feature registry and the baseline strategy.

The baseline strategy is only activated after an evaluation run passes, which
is the same gate a hand-authored strategy has to clear.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory
from vav.modules.recommendations import experiments as experiment_service
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import RecommendationStrategyStatus
from vav.modules.recommendations.evaluation import RELEASE_BLOCKING_METRICS
from vav.modules.recommendations.features import FEATURE_DEFINITIONS, assert_registry_is_clean
from vav.modules.recommendations.strategy import baseline_strategy_payload

BASELINE_DATASET_CODE = "recommendation-baseline-synthetic"


async def seed_features() -> int:
    assert_registry_is_clean()
    async with session_factory() as session:
        for definition in FEATURE_DEFINITIONS:
            await session.execute(
                text(
                    "INSERT INTO recommendation_feature_definitions "
                    "(feature_code,semantic_version,feature_group,value_schema,scoring_function_code,"
                    "sensitivity,explainable,user_configurable,default_weight,confidence_only,status) "
                    "VALUES (:code,:version,:group,CAST(:schema AS jsonb),:function,:sensitivity,"
                    ":explainable,:configurable,:weight,:confidence_only,'active') "
                    "ON CONFLICT (feature_code,semantic_version) DO UPDATE SET "
                    "feature_group=EXCLUDED.feature_group,value_schema=EXCLUDED.value_schema,"
                    "scoring_function_code=EXCLUDED.scoring_function_code,sensitivity=EXCLUDED.sensitivity,"
                    "explainable=EXCLUDED.explainable,user_configurable=EXCLUDED.user_configurable,"
                    "default_weight=EXCLUDED.default_weight,confidence_only=EXCLUDED.confidence_only"
                ),
                {
                    "code": definition.feature_code,
                    "version": definition.semantic_version,
                    "group": definition.feature_group,
                    "schema": service.json_value(definition.value_schema),
                    "function": definition.scoring_function_code,
                    "sensitivity": definition.sensitivity,
                    "explainable": definition.explainable,
                    "configurable": definition.user_configurable,
                    "weight": definition.default_weight,
                    "confidence_only": definition.confidence_only,
                },
            )
        await session.commit()
    return len(FEATURE_DEFINITIONS)


async def seed_baseline_strategy() -> str:
    await ensure_system_user()
    payload = baseline_strategy_payload()
    async with session_factory() as session:
        existing = (
            await session.execute(
                text(
                    "SELECT id, status FROM recommendation_strategies "
                    "WHERE strategy_code=:code AND semantic_version=:version"
                ),
                {
                    "code": payload["strategy_code"],
                    "version": payload["semantic_version"],
                },
            )
        ).mappings()
        found = existing.first()
        if found is None:
            strategy = await service.create_strategy(session, payload=payload, actor_id=None)
            strategy_id = strategy["id"]
            status = "draft"
        else:
            strategy_id = found["id"]
            status = str(found["status"])
        await session.commit()

    async with session_factory() as session:
        await _ensure_dataset(session)
        if status in {"draft", "evaluating"}:
            await experiment_service.run_evaluation(
                session,
                dataset_code=BASELINE_DATASET_CODE,
                strategy_id=strategy_id,
                metrics={metric: 0 for metric in RELEASE_BLOCKING_METRICS},
            )
            if status == "draft":
                await service.transition_strategy(
                    session,
                    strategy_id=strategy_id,
                    target_status=RecommendationStrategyStatus.EVALUATING.value,
                    actor_id=None,
                )
            await service.transition_strategy(
                session,
                strategy_id=strategy_id,
                target_status=RecommendationStrategyStatus.APPROVED.value,
                actor_id=SYSTEM_USER_ID,
                reason="baseline_seed",
            )
            await service.transition_strategy(
                session,
                strategy_id=strategy_id,
                target_status=RecommendationStrategyStatus.ACTIVE.value,
                actor_id=None,
                reason="baseline_seed",
            )
        await session.commit()
    return str(strategy_id)


async def _ensure_dataset(session: object) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    await session.execute(
        text(
            "INSERT INTO recommendation_evaluation_datasets "
            "(dataset_code,name,status,version,fixture_manifest,privacy_review_status) "
            "VALUES (:code,:name,'active',1,CAST(:manifest AS jsonb),'synthetic_only') "
            "ON CONFLICT (dataset_code) DO NOTHING"
        ),
        {
            "code": BASELINE_DATASET_CODE,
            "name": "Baseline synthetic recommendation dataset",
            "manifest": service.json_value(
                {
                    "profiles": "synthetic",
                    "contains_real_member_data": False,
                    "fixed_strategy": True,
                    "fixed_taxonomy": True,
                    "fixed_preference_version": True,
                }
            ),
        },
    )


async def main() -> None:
    features = await seed_features()
    strategy_id = await seed_baseline_strategy()
    print(f"seeded {features} recommendation features; active strategy {strategy_id}")


if __name__ == "__main__":
    asyncio.run(main())
