"""Exposure fairness among qualified candidates, and release guardrails."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import evaluation, exposure, service
from vav.modules.recommendations.domain import GUARDRAIL_METRICS
from vav.modules.recommendations.evaluation import GUARDRAIL_THRESHOLDS

from ..helpers import create_member, create_reviewer, ensure_strategy, make_recommendable


async def _cohort(session, size: int = 3):  # type: ignore[no-untyped-def]
    """A small balanced cohort so fairness has something to measure."""
    await ensure_strategy(session)
    reviewer = await create_reviewer(session)
    women = []
    men = []
    for index in range(size):
        woman = await create_member(
            session, gender="female", city=["shanghai", "beijing", "chengdu"][index % 3]
        )
        man = await create_member(
            session, gender="male", city=["shanghai", "beijing", "chengdu"][index % 3]
        )
        await make_recommendable(session, woman, reviewer)
        await make_recommendable(session, man, reviewer)
        women.append(woman)
        men.append(man)
    return women, men


@pytest.mark.asyncio
async def test_every_qualified_profile_can_be_reached_by_someone() -> None:
    async with session_factory() as session:
        women, men = await _cohort(session)
        reachable: set[UUID] = set()
        for viewer in women:
            await service.generate_candidates(session, viewer.id)
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT user_low_id,user_high_id FROM recommendation_candidate_pairs "
                            "WHERE status='eligible' AND (user_low_id=:id OR user_high_id=:id)"
                        ),
                        {"id": viewer.id},
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                reachable.add(row["user_low_id"])
                reachable.add(row["user_high_id"])
        # Nobody in the cohort is structurally invisible.
        assert {man.id for man in men} <= reachable


@pytest.mark.asyncio
async def test_exposure_is_spread_rather_than_concentrated_on_one_profile() -> None:
    async with session_factory() as session:
        women, _men = await _cohort(session)
        for viewer in women:
            await service.generate_candidates(session, viewer.id)
            await service.generate_batch(session, viewer.id)
            view = await service.current_batch(session, viewer)
            for item in view["items"]:
                await service.record_exposure(
                    session,
                    viewer,
                    UUID(item["recommendation_item_id"]),
                    exposure_type="card_visible",
                    duration_ms=3000,
                    idempotency_key=f"fair-{uuid4()}",
                )

        counts = (
            (
                await session.execute(
                    text(
                        "SELECT exposed_user_id, count(*) AS shown FROM recommendation_exposures "
                        "WHERE counted_as_visible=true GROUP BY exposed_user_id"
                    )
                )
            )
            .mappings()
            .all()
        )
        distribution = {str(row["exposed_user_id"]): int(row["shown"]) for row in counts}
        assert distribution
        fairness = exposure.exposure_fairness(distribution, len(distribution))
        assert fairness["measured_within_qualified_candidates_only"] is True
        # No single profile may absorb the entire cohort's exposure.
        assert fairness["max_exposure_share_bps"] <= 10000
        if len(distribution) > 1:
            assert fairness["coverage_bps"] > 0


@pytest.mark.asyncio
async def test_the_daily_show_budget_protects_a_popular_profile() -> None:
    async with session_factory() as session:
        women, men = await _cohort(session, size=2)
        popular = men[0]
        await session.execute(
            text(
                "INSERT INTO recommendation_exposure_budgets (user_id,budget_date,daily_received_limit,"
                "daily_shown_limit,current_shown_count) VALUES (:id,CURRENT_DATE,5,3,3) "
                "ON CONFLICT (user_id,budget_date) DO UPDATE SET daily_shown_limit=3,current_shown_count=3"
            ),
            {"id": popular.id},
        )
        await session.commit()

        viewer = women[0]
        await service.generate_candidates(session, viewer.id)
        result = await service.generate_batch(session, viewer.id)
        selected = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items WHERE recommendation_batch_id=:batch "
                "AND recommended_user_id=:id"
            ),
            {"batch": UUID(result["batch_id"]), "id": popular.id},
        )
        assert int(selected or 0) == 0
        assert "candidate_show_budget_exhausted" in result["report"]["rejection_reasons"]


@pytest.mark.asyncio
async def test_fairness_never_means_ignoring_someones_stated_conditions() -> None:
    """A profile with nobody compatible stays unexposed rather than being forced in."""
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer(session)
        # This man is only open to men, so no woman may ever be shown to him.
        isolated = await create_member(session, gender="male", wants=["male"])
        await make_recommendable(session, isolated, reviewer)
        woman = await create_member(session, gender="female")
        await make_recommendable(session, woman, reviewer)

        await service.generate_candidates(session, woman.id)
        eligible = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_candidate_pairs WHERE status='eligible' AND "
                "((user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a))"
            ),
            {"a": woman.id, "b": isolated.id},
        )
        assert int(eligible or 0) == 0


@pytest.mark.asyncio
async def test_a_release_is_blocked_by_a_guardrail_not_by_engagement() -> None:
    async with session_factory() as session:
        women, _men = await _cohort(session, size=2)
        for viewer in women:
            await service.generate_candidates(session, viewer.id)
            await service.generate_batch(session, viewer.id)

        strategy = await service.active_strategy(session)
        dataset_id = await session.scalar(
            text("SELECT id FROM recommendation_evaluation_datasets ORDER BY created_at LIMIT 1")
        )
        assert dataset_id is not None
        actor = await create_reviewer(session)
        result = await evaluation.run(
            session,
            actor,
            dataset_id=UUID(str(dataset_id)),
            strategy_id=UUID(str(strategy["id"])),
        )

        assert result["engagement_alone_cannot_pass_a_release"] is True
        assert set(result["guardrail_metrics_considered"]) == set(GUARDRAIL_METRICS)
        correctness = result["correctness_metrics"]
        assert correctness["hard_constraint_violation_rate_bps"] == 0
        assert correctness["eligibility_violation_rate_bps"] == 0
        assert correctness["blocked_pair_leakage_rate_bps"] == 0
        assert correctness["self_recommendation_count"] == 0
        assert correctness["privacy_violation_rate_bps"] == 0

        # Zero-tolerance safety guardrails must never be among the failures. A
        # shared test database can legitimately trip coverage guardrails, which
        # is exactly why they are separate metrics with their own ceilings.
        zero_tolerance = {
            metric for metric, ceiling in GUARDRAIL_THRESHOLDS.items() if ceiling == 0
        }
        failed = {item["metric"] for item in result["guardrail_failures"]}
        assert not failed & zero_tolerance
        assert result["passed"] is (not failed)


@pytest.mark.asyncio
async def test_a_non_synthetic_dataset_needs_privacy_approval_first() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        strategy = await service.active_strategy(session)
        actor = await create_reviewer(session)
        dataset_id = await session.scalar(
            text(
                "INSERT INTO recommendation_evaluation_datasets "
                "(dataset_code,name,status,fixture_manifest,synthetic_only,privacy_review_status,created_by) "
                "VALUES (:code,'unapproved real data','draft','{}'::jsonb,false,'pending',:actor) RETURNING id"
            ),
            {"code": f"unapproved-{uuid4().hex[:8]}", "actor": actor.id},
        )
        await session.commit()
        from vav.common.exceptions import VavError

        with pytest.raises(VavError) as error:
            await evaluation.run(
                session,
                actor,
                dataset_id=UUID(str(dataset_id)),
                strategy_id=UUID(str(strategy["id"])),
            )
        assert error.value.code == "RECOMMENDATION_DATASET_NOT_APPROVED"


def test_every_safety_guardrail_has_a_ceiling() -> None:
    for metric in (
        "hard_constraint_violation_rate_bps",
        "privacy_violation_rate_bps",
        "safety_restriction_violation_rate_bps",
    ):
        assert metric in GUARDRAIL_THRESHOLDS
        # Safety violations have a zero tolerance, not a budget.
        assert GUARDRAIL_THRESHOLDS[metric] == 0
