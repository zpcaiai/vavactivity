"""Seed the synthetic recommendation evaluation dataset.

Only synthetic fixtures are seeded. Copying a real member's sensitive profile
into a development or test dataset is never done.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import text

from vav.core.database import session_factory

DATASET_CODE = "recommendation-baseline-synthetic"

FIXTURE_MANIFEST: dict[str, Any] = {
    "source": "synthetic_only",
    "profiles": "vav.cli.seed_dating_profiles fixtures",
    "fixed_inputs": [
        "strategy_version",
        "taxonomy_version",
        "preference_version",
        "profile_projection_version",
    ],
    "contains_real_member_data": False,
    "metrics": {
        "correctness": [
            "hard_constraint_violation_rate",
            "eligibility_violation_rate",
            "blocked_pair_leakage_rate",
            "profile_version_accuracy",
        ],
        "ranking": ["ndcg_at_10", "precision_at_5", "pairwise_agreement", "minimum_directional"],
        "coverage": [
            "profile_exposure_coverage",
            "empty_result_rate",
            "repeat_exposure_rate",
        ],
        "fairness": [
            "exposure_gini",
            "qualified_long_tail_never_exposed",
            "max_exposure_share",
        ],
    },
}


async def seed_recommendation_evaluations() -> None:
    async with session_factory() as session:
        owner_id = await session.scalar(text("SELECT id FROM users ORDER BY created_at LIMIT 1"))
        if owner_id is None:
            print("No users exist yet; run the base seed first.")
            return
        await session.execute(
            text(
                "INSERT INTO recommendation_evaluation_datasets "
                "(dataset_code,name,status,version,fixture_manifest,synthetic_only,privacy_review_status,created_by) "
                "VALUES (:code,:name,'active',1,CAST(:manifest AS jsonb),true,'not_required',:owner) "
                "ON CONFLICT (dataset_code) DO UPDATE SET fixture_manifest=EXCLUDED.fixture_manifest,"
                "status='active',updated_at=now()"
            ),
            {
                "code": DATASET_CODE,
                "name": "Baseline synthetic recommendation evaluation set",
                "manifest": json.dumps(FIXTURE_MANIFEST, ensure_ascii=False, sort_keys=True),
                "owner": owner_id,
            },
        )
        await session.commit()
    print(f"Recommendation evaluation dataset seeded: {DATASET_CODE} (synthetic only)")


if __name__ == "__main__":
    asyncio.run(seed_recommendation_evaluations())
