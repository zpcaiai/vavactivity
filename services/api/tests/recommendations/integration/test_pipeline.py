"""Pool sync, candidate generation, batching, exposure and feedback."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import feedback_service, service
from vav.modules.recommendations.domain import CandidatePairStatus

from ..helpers import (
    DEFAULT_CRITERIA,
    create_member,
    create_reviewer,
    criterion,
    ensure_strategy,
    make_pair,
    make_recommendable,
)


async def _batch_for(session, viewer):  # type: ignore[no-untyped-def]
    await service.generate_candidates(session, viewer.id)
    return await service.generate_batch(session, viewer.id)


@pytest.mark.asyncio
async def test_an_approved_profile_joins_the_pool_with_coarse_codes_only() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        entry = (
            (
                await session.execute(
                    text("SELECT * FROM recommendation_pool_entries WHERE user_id=:id"),
                    {"id": female.id},
                )
            )
            .mappings()
            .first()
        )
        assert entry is not None
        assert entry["eligible"] is True
        assert entry["city_code"] == "shanghai"
        # The pool never stores narratives, photos or free text.
        columns = set(entry.keys())
        assert not columns & {
            "self_introduction",
            "display_name",
            "date_of_birth",
            "photo_url",
            "email",
        }


@pytest.mark.asyncio
async def test_pausing_recommendations_removes_a_member_from_candidacy() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await feedback_service.update_tuning(
            session,
            female,
            exploration_level=None,
            feedback_personalization_enabled=None,
            daily_received_limit=None,
            allow_relaxed_recommendations=None,
            recommendations_paused=True,
        )
        result = await service.sync_pool_entry(session, female.id)
        await session.commit()
        assert result["eligible"] is False
        assert "recommendations_paused" in result["reasons"]
        with pytest.raises(VavError) as error:
            await service.generate_batch(session, female.id)
        assert error.value.code in {"RECOMMENDATION_PAUSED", "RECOMMENDATION_NOT_ELIGIBLE"}


@pytest.mark.asyncio
async def test_a_member_without_a_projection_is_not_in_the_pool() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        stranger = await create_member(session)
        result = await service.sync_pool_entry(session, stranger.id)
        await session.commit()
        assert result["eligible"] is False
        assert "projection_not_eligible" in result["reasons"]


@pytest.mark.asyncio
async def test_candidate_generation_evaluates_both_directions_and_scores_each_way() -> None:
    async with session_factory() as session:
        female, male = await make_pair(session)
        report = await service.generate_candidates(session, female.id)
        assert report["generated"] >= 1

        pair = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM recommendation_candidate_pairs WHERE "
                        "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
                    ),
                    {"a": female.id, "b": male.id},
                )
            )
            .mappings()
            .first()
        )
        assert pair is not None
        assert pair["status"] == CandidatePairStatus.ELIGIBLE.value
        assert pair["hard_constraint_snapshot"]["passed"] is True
        # One row per pair, whoever asked for it first.
        assert str(pair["user_low_id"]) < str(pair["user_high_id"])

        scores = (
            (
                await session.execute(
                    text(
                        "SELECT source_user_id,total_score_bps,confidence_bps FROM recommendation_directional_scores "
                        "WHERE candidate_pair_id=:id"
                    ),
                    {"id": pair["id"]},
                )
            )
            .mappings()
            .all()
        )
        assert {row["source_user_id"] for row in scores} == {female.id, male.id}
        assert pair["score_snapshot"]["combined_score_bps"] > 0


@pytest.mark.asyncio
async def test_a_hard_constraint_failure_is_recorded_and_never_scored() -> None:
    async with session_factory() as session:
        female, male = await make_pair(
            session,
            female_criteria=[
                criterion(
                    "age_range",
                    "range",
                    {"minimum": 20, "maximum": 22},
                    importance="required",
                    hard=True,
                    allow_unknown=False,
                ),
                *DEFAULT_CRITERIA[1:],
            ],
        )
        await service.generate_candidates(session, female.id)
        pair = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM recommendation_candidate_pairs WHERE "
                        "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
                    ),
                    {"a": female.id, "b": male.id},
                )
            )
            .mappings()
            .first()
        )
        assert pair is not None
        assert pair["status"] == CandidatePairStatus.HARD_CONSTRAINT_FAILED.value
        assert "age_range" in pair["hard_constraint_snapshot"]["blocking_codes"]
        scored = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_directional_scores WHERE candidate_pair_id=:id"
            ),
            {"id": pair["id"]},
        )
        assert scored == 0


@pytest.mark.asyncio
async def test_a_batch_activates_atomically_and_carries_its_own_explanations() -> None:
    async with session_factory() as session:
        female, male = await make_pair(session)
        result = await _batch_for(session, female)
        assert result["status"] == "active"
        assert result["size"] >= 1
        assert result["report"]["strategy_version"]

        items = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM recommendation_items WHERE recommendation_batch_id=:id ORDER BY rank_position"
                    ),
                    {"id": UUID(result["batch_id"])},
                )
            )
            .mappings()
            .all()
        )
        assert [row["rank_position"] for row in items] == list(range(1, len(items) + 1))
        eligible = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_candidate_pairs WHERE status='eligible' AND "
                "((user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a))"
            ),
            {"a": female.id, "b": male.id},
        )
        assert eligible == 1
        for row in items:
            explanation = row["explanation_snapshot"]
            assert explanation["summary"]
            assert explanation["caveat"]
            assert 0 <= row["bidirectional_score_bps"] <= 10000


@pytest.mark.asyncio
async def test_only_one_batch_stays_active_per_member() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        await _batch_for(session, female)
        active = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_batches WHERE user_id=:id AND status='active'"
            ),
            {"id": female.id},
        )
        assert active == 1


@pytest.mark.asyncio
async def test_the_same_batch_seed_reproduces_the_same_ranking() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        result = await _batch_for(session, female)
        first = (
            (
                await session.execute(
                    text(
                        "SELECT candidate_pair_id, final_rank, adjusted_score_bps FROM recommendation_rank_results "
                        "WHERE recommendation_batch_id=:id ORDER BY final_rank"
                    ),
                    {"id": UUID(result["batch_id"])},
                )
            )
            .mappings()
            .all()
        )
        assert first
        assert [row["final_rank"] for row in first] == list(range(1, len(first) + 1))
        batch = (
            (
                await session.execute(
                    text("SELECT random_seed FROM recommendation_batches WHERE id=:id"),
                    {"id": UUID(result["batch_id"])},
                )
            )
            .mappings()
            .first()
        )
        assert batch is not None and batch["random_seed"]


@pytest.mark.asyncio
async def test_the_daily_receive_budget_stops_an_endless_stream() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await service.generate_candidates(session, female.id)
        await session.execute(
            text(
                "INSERT INTO recommendation_exposure_budgets (user_id,budget_date,daily_received_limit,"
                "daily_shown_limit,current_received_count) VALUES (:id,CURRENT_DATE,5,50,5) "
                "ON CONFLICT (user_id,budget_date) DO UPDATE SET current_received_count=5,daily_received_limit=5"
            ),
            {"id": female.id},
        )
        await session.commit()
        with pytest.raises(VavError) as error:
            await service.generate_batch(session, female.id)
        assert error.value.code == "RECOMMENDATION_DAILY_LIMIT_REACHED"
        assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_the_member_facing_batch_never_carries_a_score_or_a_percentage() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        assert view["has_batch"] is True
        for item in view["items"]:
            keys = set(item.keys())
            assert not keys & {
                "bidirectional_score_bps",
                "viewer_to_candidate_score_bps",
                "candidate_to_viewer_score_bps",
                "confidence_bps",
            }
            assert "%" not in str(item["explanation"])


@pytest.mark.asyncio
async def test_an_impression_is_not_an_exposure_but_a_long_look_is() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        item_id = UUID(view["items"][0]["recommendation_item_id"])

        impression = await service.record_exposure(
            session,
            female,
            item_id,
            exposure_type="card_impression",
            duration_ms=50000,
            idempotency_key=f"imp-{uuid4()}",
        )
        assert impression["counted_as_visible"] is False

        visible = await service.record_exposure(
            session,
            female,
            item_id,
            exposure_type="card_visible",
            duration_ms=4000,
            idempotency_key=f"vis-{uuid4()}",
        )
        assert visible["counted_as_visible"] is True
        status = await session.scalar(
            text("SELECT status FROM recommendation_items WHERE id=:id"), {"id": item_id}
        )
        assert status in {"exposed", "viewed"}


@pytest.mark.asyncio
async def test_replaying_an_exposure_key_records_nothing_twice() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        item_id = UUID(view["items"][0]["recommendation_item_id"])
        key = f"replay-{uuid4()}"
        first = await service.record_exposure(
            session,
            female,
            item_id,
            exposure_type="profile_opened",
            duration_ms=None,
            idempotency_key=key,
        )
        second = await service.record_exposure(
            session,
            female,
            item_id,
            exposure_type="profile_opened",
            duration_ms=None,
            idempotency_key=key,
        )
        assert first["recorded"] is True
        assert second["duplicate"] is True
        count = await session.scalar(
            text("SELECT count(*) FROM recommendation_exposures WHERE recommendation_item_id=:id"),
            {"id": item_id},
        )
        assert count == 1


@pytest.mark.asyncio
async def test_a_skip_starts_a_cooldown_that_keeps_the_pair_out_of_the_next_batch() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        item = view["items"][0]
        male_id = UUID(item["recommended_user_id"])
        result = await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male_id,
            feedback_type="skipped",
            reason_code="location_not_suitable",
            reason_details="需要长期异地",
            recommendation_item_id=UUID(item["recommendation_item_id"]),
            idempotency_key=f"skip-{uuid4()}",
        )
        assert result["removed_from_candidates"] is False
        cooldown = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM recommendation_skip_cooldowns WHERE viewer_user_id=:a AND skipped_user_id=:b"
                    ),
                    {"a": female.id, "b": male_id},
                )
            )
            .mappings()
            .first()
        )
        assert cooldown is not None
        # Free text is stored encrypted, never in the clear.
        details = await session.scalar(
            text(
                "SELECT reason_details_encrypted FROM recommendation_feedback_events "
                "WHERE viewer_user_id=:id ORDER BY occurred_at DESC LIMIT 1"
            ),
            {"id": female.id},
        )
        assert details is not None and "需要长期异地" not in str(details)

        excluded = await service._excluded_user_ids(session, female.id)
        assert male_id in excluded


@pytest.mark.asyncio
async def test_a_block_removes_the_pair_and_never_becomes_taste_data() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        male_id = UUID(view["items"][0]["recommended_user_id"])
        before = await service.tuning_profile(session, female.id)
        result = await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male_id,
            feedback_type="blocked",
            reason_code=None,
            reason_details=None,
            recommendation_item_id=None,
            idempotency_key=f"block-{uuid4()}",
        )
        assert result["removed_from_candidates"] is True
        assert result["used_for_learning"] is False
        after = await service.tuning_profile(session, female.id)
        assert after["feature_weight_adjustments"] == before["feature_weight_adjustments"]
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items WHERE viewer_user_id=:a "
                "AND recommended_user_id=:b AND status IN ('ready','exposed','viewed')"
            ),
            {"a": female.id, "b": male_id},
        )
        assert remaining == 0


@pytest.mark.asyncio
async def test_feedback_is_idempotent_and_rejects_nonsense() -> None:
    async with session_factory() as session:
        female, male = await make_pair(session)
        key = f"fb-{uuid4()}"
        first = await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male.id,
            feedback_type="not_relevant",
            reason_code="lifestyle_not_suitable",
            reason_details=None,
            recommendation_item_id=None,
            idempotency_key=key,
        )
        second = await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male.id,
            feedback_type="not_relevant",
            reason_code="lifestyle_not_suitable",
            reason_details=None,
            recommendation_item_id=None,
            idempotency_key=key,
        )
        assert first["recorded"] and second["duplicate"]

        with pytest.raises(VavError) as unknown_type:
            await feedback_service.record_feedback(
                session,
                female,
                recommended_user_id=male.id,
                feedback_type="secretly_adored",
                reason_code=None,
                reason_details=None,
                recommendation_item_id=None,
                idempotency_key=f"bad-{uuid4()}",
            )
        assert unknown_type.value.code == "RECOMMENDATION_FEEDBACK_TYPE_INVALID"

        with pytest.raises(VavError) as self_rating:
            await feedback_service.record_feedback(
                session,
                female,
                recommended_user_id=female.id,
                feedback_type="liked",
                reason_code=None,
                reason_details=None,
                recommendation_item_id=None,
                idempotency_key=f"self-{uuid4()}",
            )
        assert self_rating.value.code == "RECOMMENDATION_FEEDBACK_SELF"


@pytest.mark.asyncio
async def test_a_preference_change_invalidates_the_batch_it_was_built_from() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        result = await _batch_for(session, female)
        await service.invalidate_candidates_for(session, female.id, "preference_updated")
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM recommendation_items WHERE recommendation_batch_id=:id "
                "AND status IN ('ready','exposed','viewed')"
            ),
            {"id": UUID(result["batch_id"])},
        )
        assert remaining == 0
        view = await service.current_batch(session, female)
        assert view["has_batch"] is False
        assert view["guidance"]["message"]


@pytest.mark.asyncio
async def test_withdrawing_matchmaking_visibility_pulls_a_live_recommendation() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        target = UUID(view["items"][0]["recommended_user_id"])
        await session.execute(
            text("UPDATE user_privacy_settings SET visible_in_matchmaking=false WHERE user_id=:id"),
            {"id": target},
        )
        await session.commit()
        refreshed = await service.current_batch(session, female)
        assert target not in {UUID(item["recommended_user_id"]) for item in refreshed["items"]}


@pytest.mark.asyncio
async def test_a_suspended_profile_disappears_from_a_live_batch() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        view = await service.current_batch(session, female)
        target = UUID(view["items"][0]["recommended_user_id"])
        await session.execute(
            text("UPDATE dating_profiles SET status='suspended' WHERE user_id=:id"),
            {"id": target},
        )
        await session.commit()
        refreshed = await service.current_batch(session, female)
        assert target not in {UUID(item["recommended_user_id"]) for item in refreshed["items"]}
        reason = await session.scalar(
            text(
                "SELECT invalidation_reason FROM recommendation_items WHERE viewer_user_id=:a AND recommended_user_id=:b"
            ),
            {"a": female.id, "b": target},
        )
        assert reason == "profile_no_longer_active"


@pytest.mark.asyncio
async def test_an_empty_result_is_explained_rather_than_padded() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer(session)
        lonely = await create_member(session, gender="female", city="lhasa", region="west")
        await make_recommendable(
            session,
            lonely,
            reviewer,
            criteria=[
                criterion(
                    "city_code",
                    "in",
                    ["nowhere_at_all"],
                    importance="required",
                    hard=True,
                    allow_unknown=False,
                )
            ],
        )
        await service.generate_candidates(session, lonely.id)
        guidance = await service.empty_guidance(session, lonely)
        assert guidance["message"] == "当前没有完全符合你全部硬性条件的推荐。"
        assert "静默绕过硬性条件" in guidance["never_done"]
        assert "制造虚假推荐" in guidance["never_done"]


@pytest.mark.asyncio
async def test_resetting_tuning_clears_every_learned_adjustment() -> None:
    async with session_factory() as session:
        female, male = await make_pair(session)
        await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male.id,
            feedback_type="not_relevant",
            reason_code="location_not_suitable",
            reason_details=None,
            recommendation_item_id=None,
            idempotency_key=f"nr-{uuid4()}",
        )
        tuned = await service.tuning_profile(session, female.id)
        assert tuned["feature_weight_adjustments"]
        await feedback_service.reset_tuning(session, female)
        after = await service.tuning_profile(session, female.id)
        assert after["feature_weight_adjustments"] == {}


@pytest.mark.asyncio
async def test_turning_personalisation_off_freezes_the_adjustments() -> None:
    async with session_factory() as session:
        female, male = await make_pair(session)
        await feedback_service.update_tuning(
            session,
            female,
            exploration_level=None,
            feedback_personalization_enabled=False,
            daily_received_limit=None,
            allow_relaxed_recommendations=None,
            recommendations_paused=None,
        )
        before = await service.tuning_profile(session, female.id)
        await feedback_service.record_feedback(
            session,
            female,
            recommended_user_id=male.id,
            feedback_type="not_relevant",
            reason_code="faith_expectations_differ",
            reason_details=None,
            recommendation_item_id=None,
            idempotency_key=f"off-{uuid4()}",
        )
        after = await service.tuning_profile(session, female.id)
        assert after["feature_weight_adjustments"] == before["feature_weight_adjustments"]


@pytest.mark.asyncio
async def test_every_pipeline_step_leaves_an_audit_trail() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch_for(session, female)
        events = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT event_type FROM recommendation_audit_events "
                        "WHERE actor_id=:id OR subject_id=:id"
                    ),
                    {"id": female.id},
                )
            )
            .scalars()
            .all()
        )
        assert "recommendation.candidates.generated" in events
        assert "recommendation.batch.activated" in events
