"""Seed the baseline recommendation strategy and feature registry."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations.strategy import (
    FEATURE_MANIFEST,
    STRATEGY_CODE,
    STRATEGY_SEMANTIC_VERSION,
    strategy_payload,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def seed_recommendations() -> None:
    async with session_factory() as session:
        owner_id = await session.scalar(text("SELECT id FROM users ORDER BY created_at LIMIT 1"))
        if owner_id is None:
            print("No users exist yet; run the base seed first.")
            return

        payload = strategy_payload()
        strategy_id = await session.scalar(
            text(
                "SELECT id FROM recommendation_strategies WHERE strategy_code=:code AND semantic_version=:version"
            ),
            {"code": STRATEGY_CODE, "version": STRATEGY_SEMANTIC_VERSION},
        )
        if strategy_id is None:
            # The seed strategy is created pre-approved and pre-evaluated so a
            # local stack has a usable baseline; production still requires a
            # separate approver and a real evaluation run.
            strategy_id = await session.scalar(
                text(
                    "INSERT INTO recommendation_strategies (strategy_code,semantic_version,status,"
                    "hard_constraint_policy,feature_manifest,scoring_policy,bidirectional_policy,ranking_policy,"
                    "diversification_policy,exposure_policy,explanation_policy,cold_start_policy,"
                    "evaluation_passed,created_by,approved_by,approved_at,activated_by,activated_at) "
                    "VALUES (:code,:version,'active',CAST(:hard AS jsonb),CAST(:features AS jsonb),"
                    "CAST(:scoring AS jsonb),CAST(:bidirectional AS jsonb),CAST(:ranking AS jsonb),"
                    "CAST(:diversification AS jsonb),CAST(:exposure AS jsonb),CAST(:explanation AS jsonb),"
                    "CAST(:cold_start AS jsonb),true,:owner,:owner,now(),:owner,now()) RETURNING id"
                ),
                {
                    "code": STRATEGY_CODE,
                    "version": STRATEGY_SEMANTIC_VERSION,
                    "hard": _json(payload["hard_constraint_policy"]),
                    "features": _json(payload["feature_manifest"]),
                    "scoring": _json(payload["scoring_policy"]),
                    "bidirectional": _json(payload["bidirectional_policy"]),
                    "ranking": _json(payload["ranking_policy"]),
                    "diversification": _json(payload["diversification_policy"]),
                    "exposure": _json(payload["exposure_policy"]),
                    "explanation": _json(payload["explanation_policy"]),
                    "cold_start": _json(payload["cold_start_policy"]),
                    "owner": owner_id,
                },
            )
        else:
            await session.execute(
                text(
                    "UPDATE recommendation_strategies SET status='active' WHERE id=:id AND status <> 'active' "
                    "AND NOT EXISTS (SELECT 1 FROM recommendation_strategies WHERE strategy_code=:code AND status='active')"
                ),
                {"id": strategy_id, "code": STRATEGY_CODE},
            )

        for feature in FEATURE_MANIFEST:
            await session.execute(
                text(
                    "INSERT INTO recommendation_feature_definitions "
                    "(feature_code,semantic_version,feature_group,value_schema,scoring_function_code,"
                    "sensitivity,explainable,user_configurable,status) "
                    "VALUES (:code,'1.0.0',:group,CAST(:schema AS jsonb),:function,:sensitivity,"
                    ":explainable,:configurable,'active') "
                    "ON CONFLICT (feature_code,semantic_version) DO UPDATE SET "
                    "feature_group=EXCLUDED.feature_group,value_schema=EXCLUDED.value_schema,"
                    "scoring_function_code=EXCLUDED.scoring_function_code,status='active'"
                ),
                {
                    "code": feature["feature_code"],
                    "group": feature["feature_group"],
                    "schema": _json(
                        {
                            "projection_field": feature["projection_field"],
                            "preference_criterion": feature["preference_criterion"],
                            "default_weight": feature["default_weight"],
                            "options": feature["options"],
                        }
                    ),
                    "function": feature["scoring_function_code"],
                    "sensitivity": feature["sensitivity"],
                    "explainable": feature["explainable"],
                    "configurable": feature["user_configurable"],
                },
            )
        await session.commit()
    print(
        f"Recommendation seed complete: strategy {STRATEGY_CODE}@{STRATEGY_SEMANTIC_VERSION}, "
        f"{len(FEATURE_MANIFEST)} features"
    )


if __name__ == "__main__":
    asyncio.run(seed_recommendations())
