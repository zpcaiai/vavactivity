"""Races around batching, exposure, feedback and strategy activation."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import feedback_service, service

from ..helpers import make_pair


async def _prepare_batch(female: Any) -> UUID:
    async with session_factory() as session:
        await service.generate_candidates(session, female.id)
        await service.generate_batch(session, female.id)
        view = await service.current_batch(session, female)
        assert view["items"]
        return UUID(view["items"][0]["recommendation_item_id"])


@pytest.mark.asyncio
async def test_concurrent_batch_requests_leave_exactly_one_active_batch() -> None:
    async with session_factory() as setup:
        female, _male = await make_pair(setup)
        await service.generate_candidates(setup, female.id)

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                await service.generate_batch(session, female.id)
                return "generated"
            except (VavError, DBAPIError) as error:
                return getattr(error, "code", "conflict")

    results = await asyncio.gather(attempt(), attempt(), attempt(), return_exceptions=True)
    assert any(result == "generated" for result in results)

    async with session_factory() as session:
        active = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_batches WHERE user_id=:id AND status='active'"
            ),
            {"id": female.id},
        )
        assert int(active or 0) == 1


@pytest.mark.asyncio
async def test_the_same_exposure_key_sent_twice_at_once_records_once() -> None:
    async with session_factory() as setup:
        female, _male = await make_pair(setup)
    item_id = await _prepare_batch(female)
    key = f"race-{uuid4()}"

    async def attempt() -> dict[str, Any]:
        async with session_factory() as session:
            return await service.record_exposure(
                session,
                female,
                item_id,
                exposure_type="card_visible",
                duration_ms=3000,
                idempotency_key=key,
            )

    results = await asyncio.gather(attempt(), attempt(), attempt(), return_exceptions=True)
    recorded = [
        result for result in results if isinstance(result, dict) and result.get("recorded") is True
    ]
    assert len(recorded) == 1

    async with session_factory() as session:
        stored = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_exposures WHERE viewer_user_id=:id AND idempotency_key=:key"
            ),
            {"id": female.id, "key": key},
        )
        assert int(stored or 0) == 1


@pytest.mark.asyncio
async def test_concurrent_feedback_with_one_key_is_applied_once() -> None:
    async with session_factory() as setup:
        female, male = await make_pair(setup)
    key = f"fb-race-{uuid4()}"

    async def attempt() -> dict[str, Any]:
        async with session_factory() as session:
            return await feedback_service.record_feedback(
                session,
                female,
                recommended_user_id=male.id,
                feedback_type="not_relevant",
                reason_code="lifestyle_not_suitable",
                reason_details=None,
                recommendation_item_id=None,
                idempotency_key=key,
            )

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    recorded = [
        result for result in results if isinstance(result, dict) and result.get("recorded") is True
    ]
    assert len(recorded) == 1

    async with session_factory() as session:
        stored = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_feedback_events WHERE viewer_user_id=:id AND idempotency_key=:key"
            ),
            {"id": female.id, "key": key},
        )
        assert int(stored or 0) == 1


@pytest.mark.asyncio
async def test_generating_candidates_twice_at_once_keeps_one_row_per_pair() -> None:
    async with session_factory() as setup:
        female, male = await make_pair(setup)

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                await service.generate_candidates(session, female.id)
                return "ok"
            except DBAPIError:
                return "conflict"

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    assert any(result == "ok" for result in results)

    async with session_factory() as session:
        pairs = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_candidate_pairs WHERE "
                "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
            ),
            {"a": female.id, "b": male.id},
        )
        assert int(pairs or 0) == 1


@pytest.mark.asyncio
async def test_only_one_strategy_can_be_active_at_a_time() -> None:
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id,strategy_code FROM recommendation_strategies WHERE status='active' LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )
        assert row is not None
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO recommendation_strategies "
                    "(strategy_code,semantic_version,status,description,hard_constraint_policy,feature_manifest,"
                    "scoring_policy,bidirectional_policy,ranking_policy,diversification_policy,exposure_policy,"
                    "explanation_policy,cold_start_policy,approved_by,evaluation_passed) "
                    "VALUES (:code,'9.9.9','active','duplicate active strategy','{}'::jsonb,'[]'::jsonb,"
                    "'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,"
                    "(SELECT id FROM users LIMIT 1),true)"
                ),
                {"code": row["strategy_code"]},
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_a_strategy_cannot_go_live_without_approval_and_a_passing_evaluation() -> None:
    async with session_factory() as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                text(
                    "INSERT INTO recommendation_strategies "
                    "(strategy_code,semantic_version,status,description,hard_constraint_policy,feature_manifest,"
                    "scoring_policy,bidirectional_policy,ranking_policy,diversification_policy,exposure_policy,"
                    "explanation_policy,cold_start_policy) "
                    "VALUES (:code,'9.9.9','active','unapproved','{}'::jsonb,'[]'::jsonb,'{}'::jsonb,"
                    "'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb)"
                ),
                {"code": f"unapproved-{uuid4().hex[:8]}"},
            )
        message = str(error.value).lower()
        assert "approv" in message or "evaluation" in message
        await session.rollback()


@pytest.mark.asyncio
async def test_a_batch_cannot_hold_the_same_person_twice() -> None:
    async with session_factory() as setup:
        female, _male = await make_pair(setup)
    await _prepare_batch(female)

    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT recommendation_batch_id,viewer_user_id,recommended_user_id,candidate_pair_id "
                        "FROM recommendation_items WHERE viewer_user_id=:id LIMIT 1"
                    ),
                    {"id": female.id},
                )
            )
            .mappings()
            .first()
        )
        assert row is not None
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO recommendation_items "
                    "(recommendation_batch_id,viewer_user_id,recommended_user_id,candidate_pair_id,rank_position,"
                    "viewer_to_candidate_score_bps,candidate_to_viewer_score_bps,bidirectional_score_bps,confidence_bps) "
                    "VALUES (:batch,:viewer,:recommended,:pair,99,5000,5000,5000,5000)"
                ),
                {
                    "batch": row["recommendation_batch_id"],
                    "viewer": row["viewer_user_id"],
                    "recommended": row["recommended_user_id"],
                    "pair": row["candidate_pair_id"],
                },
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_concurrent_tuning_updates_converge_on_one_final_state() -> None:
    async with session_factory() as setup:
        female, _male = await make_pair(setup)

    async def attempt(level: str) -> str:
        async with session_factory() as session:
            try:
                result = await feedback_service.update_tuning(
                    session,
                    female,
                    exploration_level=level,
                    feedback_personalization_enabled=None,
                    daily_received_limit=None,
                    allow_relaxed_recommendations=None,
                    recommendations_paused=None,
                )
                return str(result["exploration_level"])
            except (VavError, DBAPIError):
                return "conflict"

    results = await asyncio.gather(attempt("focused"), attempt("open"), return_exceptions=True)
    assert any(result in {"focused", "open"} for result in results)

    async with session_factory() as session:
        rows = await session.scalar(
            text("SELECT count(*) FROM recommendation_user_tuning_profiles WHERE user_id=:id"),
            {"id": female.id},
        )
        assert int(rows or 0) == 1
