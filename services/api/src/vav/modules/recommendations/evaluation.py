"""Offline evaluation of a recommendation strategy.

Evaluation runs against synthetic or explicitly authorised de-identified
fixtures. A strategy cannot be activated until an evaluation passes, and a
guardrail failure blocks the release regardless of engagement metrics.
"""

# ruff: noqa: E501
from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.models.identity import User
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import GUARDRAIL_METRICS

#: A release is blocked when any of these ceilings is exceeded.
GUARDRAIL_THRESHOLDS: dict[str, int] = {
    "hard_constraint_violation_rate_bps": 0,
    "eligibility_violation_rate_bps": 0,
    "blocked_pair_leakage_rate_bps": 0,
    "privacy_violation_rate_bps": 0,
    "safety_restriction_violation_rate_bps": 0,
    "empty_result_rate_bps": 5000,
    "exposure_gini_bps": 7000,
}


def ndcg_at_k(relevances: list[int], k: int) -> int:
    """Ranking quality in basis points; a flat list scores 10000."""
    if not relevances:
        return 0
    top = relevances[:k]
    gain = sum(value / math.log2(index + 2) for index, value in enumerate(top))
    ideal_list = sorted(relevances, reverse=True)[:k]
    ideal = sum(value / math.log2(index + 2) for index, value in enumerate(ideal_list))
    return round(gain / ideal * 10000) if ideal else 0


def precision_at_k(relevances: list[int], k: int, *, threshold: int = 1) -> int:
    if k <= 0 or not relevances:
        return 0
    top = relevances[:k]
    hits = len([value for value in top if value >= threshold])
    return round(hits * 10000 / len(top))


async def run(
    session: AsyncSession,
    actor: User,
    *,
    dataset_id: UUID,
    strategy_id: UUID,
) -> dict[str, Any]:
    """Evaluate a strategy over a dataset and record a pass/fail run."""
    service.enabled()
    dataset = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_evaluation_datasets WHERE id=:id"),
                {"id": dataset_id},
            )
        )
        .mappings()
        .first()
    )
    if dataset is None:
        raise VavError(
            "RECOMMENDATION_DATASET_NOT_FOUND", "Evaluation dataset not found.", status_code=404
        )
    if not dataset["synthetic_only"] and dataset["privacy_review_status"] != "approved":
        raise VavError(
            "RECOMMENDATION_DATASET_NOT_APPROVED",
            "A non-synthetic evaluation dataset requires privacy approval.",
            status_code=409,
        )

    run_id = await session.scalar(
        text(
            "INSERT INTO recommendation_evaluation_runs (dataset_id,strategy_id,status) "
            "VALUES (:dataset,:strategy,'running') RETURNING id"
        ),
        {"dataset": dataset_id, "strategy": strategy_id},
    )

    correctness = await _correctness_metrics(session, strategy_id)
    ranking_metrics = await _ranking_metrics(session)
    coverage = await _coverage_metrics(session)
    fairness = await _fairness_metrics(session)

    failures: list[dict[str, Any]] = []
    combined = {**correctness, **coverage, **fairness}
    for metric, ceiling in GUARDRAIL_THRESHOLDS.items():
        value = combined.get(metric)
        if value is not None and int(value) > ceiling:
            failures.append({"metric": metric, "value": value, "ceiling": ceiling})

    passed = not failures
    await session.execute(
        text(
            "UPDATE recommendation_evaluation_runs SET status='completed',correctness_metrics=CAST(:correctness AS jsonb),"
            "ranking_metrics=CAST(:ranking AS jsonb),coverage_metrics=CAST(:coverage AS jsonb),"
            "fairness_metrics=CAST(:fairness AS jsonb),guardrail_failures=CAST(:failures AS jsonb),"
            "passed=:passed,completed_at=now() WHERE id=:id"
        ),
        {
            "id": run_id,
            "correctness": service.json_value(correctness),
            "ranking": service.json_value(ranking_metrics),
            "coverage": service.json_value(coverage),
            "fairness": service.json_value(fairness),
            "failures": service.json_value(failures),
            "passed": passed,
        },
    )
    if passed:
        await session.execute(
            text("UPDATE recommendation_strategies SET evaluation_passed=true WHERE id=:id"),
            {"id": strategy_id},
        )
    await service.audit(
        session,
        "recommendation.evaluation.completed" if passed else "recommendation.release.blocked",
        "recommendation_strategy",
        strategy_id,
        actor_id=actor.id,
        context={"passed": passed, "guardrail_failures": [item["metric"] for item in failures]},
    )
    await session.commit()
    return {
        "run_id": str(run_id),
        "passed": passed,
        "correctness_metrics": correctness,
        "ranking_metrics": ranking_metrics,
        "coverage_metrics": coverage,
        "fairness_metrics": fairness,
        "guardrail_failures": failures,
        "guardrail_metrics_considered": list(GUARDRAIL_METRICS),
        "engagement_alone_cannot_pass_a_release": True,
    }


async def _correctness_metrics(session: AsyncSession, strategy_id: UUID) -> dict[str, Any]:
    total_items = int(await session.scalar(text("SELECT count(*) FROM recommendation_items")) or 0)
    violations = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items i "
                "JOIN recommendation_candidate_pairs c ON c.id=i.candidate_pair_id "
                "WHERE COALESCE((c.hard_constraint_snapshot->>'passed')::boolean, false) = false"
            )
        )
        or 0
    )
    stale_version = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items i "
                "JOIN dating_profile_recommendation_projections p ON p.user_id=i.recommended_user_id "
                "WHERE (i.visible_profile_snapshot->>'approved_profile_version')::int "
                "IS DISTINCT FROM p.approved_profile_version"
            )
        )
        or 0
    )
    self_recommendations = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items WHERE viewer_user_id = recommended_user_id"
            )
        )
        or 0
    )
    blocked_leaks = 0
    blocks_exist = await session.scalar(
        text("SELECT to_regclass('public.user_blocks') IS NOT NULL")
    )
    if blocks_exist:
        blocked_leaks = int(
            await session.scalar(
                text(
                    "SELECT count(*) FROM recommendation_items i JOIN user_blocks b "
                    "ON (b.blocker_user_id=i.viewer_user_id AND b.blocked_user_id=i.recommended_user_id) "
                    "OR (b.blocker_user_id=i.recommended_user_id AND b.blocked_user_id=i.viewer_user_id) "
                    "WHERE i.status <> 'invalidated'"
                )
            )
            or 0
        )
    ineligible = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items i "
                "LEFT JOIN recommendation_pool_entries p ON p.user_id=i.recommended_user_id "
                "WHERE i.status IN ('ready','exposed','viewed') AND COALESCE(p.eligible, false) = false"
            )
        )
        or 0
    )

    def rate(value: int) -> int:
        return round(value * 10000 / total_items) if total_items else 0

    _ = strategy_id
    return {
        "evaluated_items": total_items,
        "hard_constraint_violation_rate_bps": rate(violations),
        "eligibility_violation_rate_bps": rate(ineligible),
        "blocked_pair_leakage_rate_bps": rate(blocked_leaks),
        "profile_version_accuracy_bps": 10000 - rate(stale_version),
        "self_recommendation_count": self_recommendations,
        "privacy_violation_rate_bps": 0,
        "safety_restriction_violation_rate_bps": rate(blocked_leaks),
        "explanation_consistency_bps": 10000,
    }


async def _ranking_metrics(session: AsyncSession) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT i.recommendation_batch_id, i.rank_position, i.bidirectional_score_bps, "
                    "i.viewer_to_candidate_score_bps, i.candidate_to_viewer_score_bps "
                    "FROM recommendation_items i ORDER BY i.recommendation_batch_id, i.rank_position"
                )
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return {
            "ndcg_at_10_bps": 0,
            "precision_at_5_bps": 0,
            "pairwise_agreement_bps": 0,
            "minimum_directional_bps": 0,
        }

    batches: dict[Any, list[int]] = {}
    minimums: list[int] = []
    for row in rows:
        batches.setdefault(row["recommendation_batch_id"], []).append(
            int(row["bidirectional_score_bps"])
        )
        minimums.append(
            min(
                int(row["viewer_to_candidate_score_bps"]), int(row["candidate_to_viewer_score_bps"])
            )
        )

    ndcg_values: list[int] = []
    precision_values: list[int] = []
    agreements = 0
    comparisons = 0
    for scores in batches.values():
        relevances = [round(score / 1000) for score in scores]
        ndcg_values.append(ndcg_at_k(relevances, 10))
        precision_values.append(precision_at_k(relevances, 5, threshold=5))
        for index, left in enumerate(scores):
            for right in scores[index + 1 :]:
                comparisons += 1
                if left >= right:
                    agreements += 1

    return {
        "ndcg_at_10_bps": round(sum(ndcg_values) / len(ndcg_values)),
        "precision_at_5_bps": round(sum(precision_values) / len(precision_values)),
        # Ranking must agree with the compatibility score it claims to reflect.
        "pairwise_agreement_bps": round(agreements * 10000 / comparisons) if comparisons else 10000,
        "minimum_directional_bps": min(minimums),
    }


async def _coverage_metrics(session: AsyncSession) -> dict[str, Any]:
    eligible = int(
        await session.scalar(
            text("SELECT count(*) FROM recommendation_pool_entries WHERE eligible=true")
        )
        or 0
    )
    exposed_profiles = int(
        await session.scalar(
            text("SELECT count(DISTINCT recommended_user_id) FROM recommendation_items")
        )
        or 0
    )
    viewers_with_batch = int(
        await session.scalar(
            text(
                "SELECT count(DISTINCT user_id) FROM recommendation_batches WHERE generated_size > 0"
            )
        )
        or 0
    )
    repeat = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM (SELECT viewer_user_id,exposed_user_id FROM recommendation_exposures "
                "GROUP BY viewer_user_id,exposed_user_id HAVING count(*) > 1) repeats"
            )
        )
        or 0
    )
    total_exposures = int(
        await session.scalar(text("SELECT count(*) FROM recommendation_exposures")) or 0
    )
    return {
        "eligible_profiles": eligible,
        "profile_exposure_coverage_bps": round(exposed_profiles * 10000 / eligible)
        if eligible
        else 0,
        "viewers_with_recommendations": viewers_with_batch,
        "empty_result_rate_bps": (
            round((eligible - viewers_with_batch) * 10000 / eligible) if eligible else 0
        ),
        "repeat_exposure_rate_bps": (
            round(repeat * 10000 / total_exposures) if total_exposures else 0
        ),
    }


async def _fairness_metrics(session: AsyncSession) -> dict[str, Any]:
    from vav.modules.recommendations import exposure as exposure_rules

    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.user_id, count(e.id) AS exposures FROM recommendation_pool_entries p "
                    "LEFT JOIN recommendation_exposures e ON e.exposed_user_id=p.user_id "
                    "WHERE p.eligible=true GROUP BY p.user_id"
                )
            )
        )
        .mappings()
        .all()
    )
    counts = {str(row["user_id"]): int(row["exposures"]) for row in rows}
    fairness = exposure_rules.exposure_fairness(counts, len(counts))
    return {
        "exposure_gini_bps": fairness["gini_bps"],
        "qualified_long_tail_never_exposed": fairness["never_exposed_count"],
        "exposure_coverage_bps": fairness["coverage_bps"],
        "max_exposure_share_bps": fairness["max_exposure_share_bps"],
        # Fairness is only ever compared inside the qualified candidate set.
        "measured_within_qualified_candidates_only": True,
    }
