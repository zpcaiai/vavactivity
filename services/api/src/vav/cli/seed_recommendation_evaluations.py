"""Seed offline recommendation evaluation datasets.

Datasets are synthetic by construction: no real member profile is ever copied
into a development or test fixture.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import service

DATASETS: tuple[tuple[str, str, dict[str, object]], ...] = (
    (
        "recommendation-baseline-synthetic",
        "Baseline synthetic recommendation dataset",
        {
            "profiles": "synthetic",
            "profile_count": 40,
            "contains_real_member_data": False,
            "fixed_strategy": True,
            "fixed_taxonomy": True,
            "fixed_preference_version": True,
        },
    ),
    (
        "recommendation-hard-constraint-regression",
        "Hard-constraint regression fixtures",
        {
            "profiles": "synthetic",
            "profile_count": 24,
            "contains_real_member_data": False,
            "scenarios": [
                "mutual_pass",
                "viewer_rejects_candidate",
                "candidate_rejects_viewer",
                "unknown_allowed",
                "unknown_not_allowed",
                "relaxation_permitted",
                "relaxation_forbidden",
            ],
        },
    ),
    (
        "recommendation-fairness-exposure",
        "Qualified exposure fairness fixtures",
        {
            "profiles": "synthetic",
            "profile_count": 60,
            "contains_real_member_data": False,
            "groups": ["region_a", "region_b", "new_profiles", "long_tail"],
        },
    ),
)


async def seed() -> int:
    async with session_factory() as session:
        for code, name, manifest in DATASETS:
            await session.execute(
                text(
                    "INSERT INTO recommendation_evaluation_datasets "
                    "(dataset_code,name,status,version,fixture_manifest,privacy_review_status) "
                    "VALUES (:code,:name,'active',1,CAST(:manifest AS jsonb),'synthetic_only') "
                    "ON CONFLICT (dataset_code) DO UPDATE SET name=EXCLUDED.name, "
                    "fixture_manifest=EXCLUDED.fixture_manifest, updated_at=now()"
                ),
                {"code": code, "name": name, "manifest": service.json_value(manifest)},
            )
        await session.commit()
    return len(DATASETS)


async def main() -> None:
    count = await seed()
    print(f"seeded {count} recommendation evaluation datasets")


if __name__ == "__main__":
    asyncio.run(main())
