"""Run the offline recommendation evaluation against live pipeline output.

The correctness metrics are measured, not assumed: every produced item is
re-checked against both members' hard constraints, the exclusion table and the
recommendation DTO contract. Any violation is a release blocker.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.database import session_factory
from vav.modules.recommendations import service
from vav.modules.recommendations.batches import VISIBLE_SNAPSHOT_KEYS
from vav.modules.recommendations.domain import canonical_pair
from vav.modules.recommendations.evaluation import (
    RELEASE_BLOCKING_METRICS,
    catalog_coverage,
    gini_bps,
    rate_bps,
)
from vav.modules.recommendations.experiments import run_evaluation

DATASET_CODE = "recommendation-baseline-synthetic"


async def measure(session: AsyncSession) -> dict[str, int]:
    """Measure the release-blocking and coverage metrics from stored output."""
    items = (
        await session.execute(
            text(
                "SELECT i.id, i.viewer_user_id, i.recommended_user_id, i.candidate_pair_id, "
                "i.visible_profile_snapshot, i.status, p.hard_constraint_snapshot "
                "FROM recommendation_items i "
                "JOIN recommendation_candidate_pairs p ON p.id = i.candidate_pair_id "
                "WHERE i.status NOT IN ('invalidated','expired')"
            )
        )
    ).mappings()

    total = 0
    hard_violations = 0
    eligibility_violations = 0
    block_leaks = 0
    contact_leaks = 0
    unapproved = 0
    privacy_violations = 0

    for item in items:
        total += 1
        snapshot = service._jsonb(item["hard_constraint_snapshot"]) or {}
        if not snapshot.get("passed", False):
            hard_violations += 1

        entry = await service.pool_entry(session, item["recommended_user_id"])
        if entry is None or not entry["eligible"]:
            eligibility_violations += 1

        profile_status = (
            await session.execute(
                text(
                    "SELECT status, approved_version_number FROM dating_profiles WHERE user_id=:user_id"
                ),
                {"user_id": item["recommended_user_id"]},
            )
        ).mappings()
        profile = profile_status.first()
        if (
            profile is None
            or str(profile["status"]) != "active"
            or profile["approved_version_number"] is None
        ):
            unapproved += 1

        low, high = canonical_pair(item["viewer_user_id"], item["recommended_user_id"])
        blocked = (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_pair_exclusions WHERE user_low_id=:low "
                    "AND user_high_id=:high AND exclusion_type IN ('safety_block','active_relationship') "
                    "AND released_at IS NULL"
                ),
                {"low": low, "high": high},
            )
        ).scalar_one()
        restricted = (
            await session.execute(
                text(
                    "SELECT count(*) FROM activity_interaction_restrictions WHERE user_a_id=:low "
                    "AND user_b_id=:high AND status='active'"
                ),
                {"low": low, "high": high},
            )
        ).scalar_one()
        if int(blocked or 0) or int(restricted or 0):
            block_leaks += 1

        visible = service._jsonb(item["visible_profile_snapshot"]) or {}
        if set(visible) - VISIBLE_SNAPSHOT_KEYS:
            privacy_violations += 1
        serialised = service.json_value(visible).lower()
        if any(marker in serialised for marker in ("@", "wechat", "date_of_birth", "phone")):
            contact_leaks += 1

    exposed = {
        str(row[0])
        for row in (
            await session.execute(
                text(
                    "SELECT user_id FROM recommendation_profile_exposure_stats WHERE total_exposures > 0"
                )
            )
        ).all()
    }
    eligible = {
        str(row[0])
        for row in (
            await session.execute(
                text("SELECT user_id FROM recommendation_pool_entries WHERE eligible = true")
            )
        ).all()
    }
    exposure_counts = [
        int(row[0])
        for row in (
            await session.execute(
                text("SELECT total_exposures FROM recommendation_profile_exposure_stats")
            )
        ).all()
    ]
    empty_batches = int(
        (
            await session.execute(
                text("SELECT count(*) FROM recommendation_batches WHERE generated_size = 0")
            )
        ).scalar_one()
        or 0
    )
    all_batches = int(
        (await session.execute(text("SELECT count(*) FROM recommendation_batches"))).scalar_one()
        or 0
    )

    metrics: dict[str, int] = {metric: 0 for metric in RELEASE_BLOCKING_METRICS}
    metrics.update(
        {
            "evaluated_items": total,
            "hard_constraint_violation_rate_bps": rate_bps(hard_violations, total),
            "eligibility_violation_rate_bps": rate_bps(eligibility_violations, total),
            "blocked_pair_leakage_rate_bps": rate_bps(block_leaks, total),
            "privacy_violation_rate_bps": rate_bps(privacy_violations, total),
            "safety_restriction_violation_rate_bps": rate_bps(block_leaks, total),
            "contact_information_leakage_rate_bps": rate_bps(contact_leaks, total),
            "unapproved_profile_exposure_rate_bps": rate_bps(unapproved, total),
            "catalog_coverage_bps": catalog_coverage(exposed, eligible),
            "exposure_gini_bps": gini_bps(exposure_counts),
            "empty_result_rate_bps": rate_bps(empty_batches, all_batches),
        }
    )
    return metrics


async def main() -> None:
    async with session_factory() as session:
        strategy = await service.active_strategy(session)
        metrics = await measure(session)
        outcome: dict[str, Any] = await run_evaluation(
            session,
            dataset_code=DATASET_CODE,
            strategy_id=strategy["id"],
            metrics=metrics,
        )
        await session.commit()

    result = outcome["result"]
    print(f"metrics: {result['metrics']}")
    if not result["passed"]:
        print(f"blocking failures: {result['blocking_failures']}")
        print(f"guardrail failures: {result['guardrail_failures']}")
        sys.exit(1)
    print("recommendation evaluation passed")


if __name__ == "__main__":
    asyncio.run(main())
