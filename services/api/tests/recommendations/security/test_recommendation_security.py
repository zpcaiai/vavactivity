"""Cross-user, privacy, safety and disclosure guarantees for recommendations."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import explanations, feedback_service, service
from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS

from ..helpers import criterion, make_pair


async def _batch(session, viewer):  # type: ignore[no-untyped-def]
    await service.generate_candidates(session, viewer.id)
    await service.generate_batch(session, viewer.id)
    return await service.current_batch(session, viewer)


@pytest.mark.asyncio
async def test_a_member_cannot_open_someone_elses_recommendation() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        intruder, _other = await make_pair(session)
        view = await _batch(session, female)
        item_id = UUID(view["items"][0]["recommendation_item_id"])

        with pytest.raises(VavError) as error:
            await service.record_exposure(
                session,
                intruder,
                item_id,
                exposure_type="profile_opened",
                duration_ms=None,
                idempotency_key=f"steal-{uuid4()}",
            )
        assert error.value.code == "RECOMMENDATION_ITEM_NOT_FOUND"
        assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_a_member_cannot_attach_feedback_to_someone_elses_item() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        intruder, other = await make_pair(session)
        view = await _batch(session, female)
        item_id = UUID(view["items"][0]["recommendation_item_id"])

        with pytest.raises(VavError) as error:
            await feedback_service.record_feedback(
                session,
                intruder,
                recommended_user_id=other.id,
                feedback_type="liked",
                reason_code=None,
                reason_details=None,
                recommendation_item_id=item_id,
                idempotency_key=f"steal-fb-{uuid4()}",
            )
        assert error.value.code == "RECOMMENDATION_ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_a_blocked_pair_is_never_recommended_in_either_direction() -> None:
    """Batch 18 owns the block table; the gateway must honour it the moment it exists."""
    async with session_factory() as session:
        female, male = await make_pair(session)
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS user_blocks ("
                "blocker_user_id uuid NOT NULL, blocked_user_id uuid NOT NULL, "
                "reason_category varchar(64), created_at timestamptz NOT NULL DEFAULT now(), "
                "PRIMARY KEY (blocker_user_id, blocked_user_id))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO user_blocks (blocker_user_id,blocked_user_id,reason_category) "
                "VALUES (:a,:b,'other') ON CONFLICT DO NOTHING"
            ),
            {"a": male.id, "b": female.id},
        )
        await session.commit()
        try:
            # The block runs the other way round; it still protects both people.
            safety = await service.evaluate_recommendation_pair_safety(session, female.id, male.id)
            assert safety["allowed"] is False
            assert safety["reason_code"] == "blocked"

            await service.generate_candidates(session, female.id)
            await service.generate_batch(session, female.id)
            recommended = await session.scalar(
                text(
                    "SELECT count(*) FROM recommendation_items WHERE "
                    "(viewer_user_id=:a AND recommended_user_id=:b) OR (viewer_user_id=:b AND recommended_user_id=:a)"
                ),
                {"a": female.id, "b": male.id},
            )
            assert int(recommended or 0) == 0
        finally:
            await session.execute(text("DROP TABLE IF EXISTS user_blocks"))
            await session.commit()


@pytest.mark.asyncio
async def test_the_safety_gateway_fails_closed_when_moderation_is_unavailable() -> None:
    class BrokenSession:
        async def scalar(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("moderation store unreachable")

    result = await service.evaluate_recommendation_pair_safety(
        BrokenSession(),  # type: ignore[arg-type]
        uuid4(),
        uuid4(),
    )
    assert result["allowed"] is False
    assert result["reason_code"] == "moderation_unavailable"


@pytest.mark.asyncio
async def test_a_recommendation_never_carries_contact_details_or_free_text() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        view = await _batch(session, female)
        serialised = str(view["items"])
        for leak in ("@example.com", "password", "date_of_birth", "phone", "wechat"):
            assert leak not in serialised
        for item in view["items"]:
            summary = item["profile_summary"]
            assert set(summary.keys()) <= {
                "approved_profile_version",
                "privacy_settings_version",
                "projection_checksum",
                "age_bucket",
                "city_code",
                "region_code",
                "country_code",
                "faith_codes",
                "relationship_intent",
                "language_codes",
                "lifestyle_codes",
                "marital_status_code",
                "children_status_code",
                "relocation_willingness",
            }


@pytest.mark.asyncio
async def test_an_explanation_never_reveals_the_other_partys_criteria_or_score() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(
            session,
            male_criteria=[
                criterion(
                    "city_code",
                    "in",
                    ["shanghai"],
                    importance="required",
                    hard=True,
                    allow_unknown=False,
                )
            ],
        )
        view = await _batch(session, female)
        for item in view["items"]:
            explanation = item["explanation"]
            explanations.assert_safe(explanation)
            text_blob = str(explanation)
            assert "hard_constraint" not in text_blob
            assert "criterion_code" not in text_blob
            assert "importance_weight" not in text_blob
            assert "%" not in text_blob


@pytest.mark.asyncio
async def test_a_member_cannot_force_themselves_into_another_persons_batch() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        with pytest.raises(TypeError):
            # There is deliberately no such control anywhere in the API.
            await feedback_service.update_tuning(
                session,
                female,
                exploration_level=None,
                feedback_personalization_enabled=None,
                daily_received_limit=None,
                allow_relaxed_recommendations=None,
                recommendations_paused=None,
                force_show_to_user_id=uuid4(),  # type: ignore[call-arg]
            )


@pytest.mark.asyncio
async def test_a_member_cannot_raise_their_own_daily_limit_past_the_platform_ceiling() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        with pytest.raises(VavError) as error:
            await feedback_service.update_tuning(
                session,
                female,
                exploration_level=None,
                feedback_personalization_enabled=None,
                daily_received_limit=100000,
                allow_relaxed_recommendations=None,
                recommendations_paused=None,
            )
        assert error.value.status_code in {400, 409, 422}


@pytest.mark.asyncio
async def test_relaxation_only_ever_applies_to_the_viewers_own_conditions() -> None:
    async with session_factory() as session:
        female, male = await make_pair(
            session,
            male_overrides={"city": "chengdu", "region": "west"},
            female_criteria=[
                criterion(
                    "city_code",
                    "in",
                    ["shanghai"],
                    importance="required",
                    hard=True,
                    allow_unknown=False,
                )
            ],
            male_criteria=[
                criterion(
                    "city_code",
                    "in",
                    ["chengdu"],
                    importance="required",
                    hard=True,
                    allow_unknown=False,
                )
            ],
        )
        await feedback_service.update_tuning(
            session,
            female,
            exploration_level=None,
            feedback_personalization_enabled=None,
            daily_received_limit=None,
            allow_relaxed_recommendations=True,
            recommendations_paused=None,
        )
        await service.generate_candidates(session, female.id)
        pair = (
            (
                await session.execute(
                    text(
                        "SELECT hard_constraint_snapshot FROM recommendation_candidate_pairs WHERE "
                        "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
                    ),
                    {"a": female.id, "b": male.id},
                )
            )
            .mappings()
            .first()
        )
        assert pair is not None
        snapshot = pair["hard_constraint_snapshot"]
        # The man's own city rule still excludes her; her relaxation cannot touch it.
        assert snapshot["passed"] is False
        assert "city_code" in snapshot["blocking_codes"]


@pytest.mark.asyncio
async def test_the_audit_trail_records_rules_and_versions_never_profiles() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await _batch(session, female)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT safe_context FROM recommendation_audit_events WHERE actor_id=:id OR subject_id=:id"
                    ),
                    {"id": female.id},
                )
            )
            .scalars()
            .all()
        )
        assert rows
        blob = str(rows)
        for leak in ("self_introduction", "@example.com", "date_of_birth", "photo"):
            assert leak not in blob


@pytest.mark.asyncio
async def test_no_prohibited_signal_is_ever_persisted_as_a_feature_score() -> None:
    async with session_factory() as session:
        female, _male = await make_pair(session)
        await service.generate_candidates(session, female.id)
        stored = (
            (
                await session.execute(
                    text(
                        "SELECT feature_scores FROM recommendation_directional_scores WHERE source_user_id=:id"
                    ),
                    {"id": female.id},
                )
            )
            .scalars()
            .all()
        )
        assert stored
        codes = {str(entry["feature_code"]) for scores in stored for entry in (scores or [])}
        assert not codes & PROHIBITED_SCORING_SIGNALS


def test_recommendation_endpoints_reject_an_anonymous_caller(client: TestClient) -> None:
    for method, path in (
        ("get", "/api/v1/recommendations"),
        ("post", "/api/v1/recommendations/batches"),
        ("get", "/api/v1/account/recommendation-preferences"),
        ("get", "/api/v1/account/recommendation-transparency"),
    ):
        response = client.post(path, json={}) if method == "post" else client.get(path)
        assert response.status_code in {401, 403}


def test_admin_recommendation_endpoints_require_a_permission(client: TestClient) -> None:
    for path in (
        "/api/v1/admin/recommendations/dashboard",
        "/api/v1/admin/recommendations/strategies",
        "/api/v1/admin/recommendations/batches",
        "/api/v1/admin/recommendations/audit",
    ):
        response = client.get(path)
        assert response.status_code in {401, 403}
