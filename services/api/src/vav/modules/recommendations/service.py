"""Recommendation application service.

The pipeline is deliberately staged — pool eligibility, safety exclusion,
bidirectional hard constraints, recall, bidirectional scoring, exposure
budget, diversification, explanation, frozen batch — rather than scoring the
whole table and letting a model decide who suits whom.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import User
from vav.modules.recommendations import (
    bidirectional,
    coldstart,
    constraints,
    explanations,
    ranking,
    scoring,
)
from vav.modules.recommendations import (
    exposure as exposure_rules,
)
from vav.modules.recommendations.domain import (
    CandidatePairStatus,
    RecommendationBatchStatus,
    RecommendationItemStatus,
    can_transition_batch,
    normalise_pair,
)
from vav.modules.recommendations.strategy import STRATEGY_CODE

PROJECTION_COLUMNS = (
    "dating_profile_id,user_id,approved_profile_version,preference_version,privacy_settings_version,"
    "eligible,age_bucket,age_years,country_code,region_code,city_code,gender_code,"
    "eligible_partner_gender_codes,faith_codes,relationship_intent,marital_status_code,"
    "children_status_code,relocation_willingness,language_codes,lifestyle_codes,"
    "indexed_preference_criteria,projection_checksum,projection_version"
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def enabled() -> None:
    if not get_settings().recommendation_enabled:
        raise VavError("RECOMMENDATION_DISABLED", "Recommendations are disabled.", status_code=503)


async def audit(
    session: AsyncSession,
    event_type: str,
    subject_type: str,
    subject_id: UUID | None,
    *,
    actor_id: UUID | None = None,
    reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Record a recommendation audit event.

    Only versions, rule codes, outcomes and actors are stored — never a
    profile, a full preference set or a photo.
    """
    await session.execute(
        text(
            "INSERT INTO recommendation_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,safe_context) "
            "VALUES (:event_type,:actor_id,:subject_type,:subject_id,:reason,CAST(:context AS jsonb))"
        ),
        {
            "event_type": event_type,
            "actor_id": actor_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "reason": reason,
            "context": json_value(context or {}),
        },
    )


async def emit_event(
    session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'recommendation',:aggregate_id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "aggregate_id": str(aggregate_id), "payload": json_value(payload)},
    )


# --------------------------------------------------------------------------
# Strategy
# --------------------------------------------------------------------------


async def active_strategy(session: AsyncSession) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,strategy_code,semantic_version,hard_constraint_policy,feature_manifest,"
                    "scoring_policy,bidirectional_policy,ranking_policy,diversification_policy,"
                    "exposure_policy,explanation_policy,cold_start_policy "
                    "FROM recommendation_strategies WHERE strategy_code=:code AND status='active'"
                ),
                {"code": get_settings().recommendation_default_strategy or STRATEGY_CODE},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RECOMMENDATION_STRATEGY_NOT_ACTIVE",
            "No active recommendation strategy is configured.",
            status_code=503,
        )
    return dict(row)


# --------------------------------------------------------------------------
# Safety gateway
# --------------------------------------------------------------------------


async def evaluate_recommendation_pair_safety(
    session: AsyncSession, viewer_user_id: UUID, candidate_user_id: UUID
) -> dict[str, Any]:
    """Ask the moderation domain whether a pair may be recommended.

    Batch 18 owns blocking and restrictions. Until it exists the gateway reads
    defensively and, on any error, fails closed rather than leaking a pair.
    """
    settings = get_settings()
    try:
        blocks_exist = await session.scalar(
            text("SELECT to_regclass('public.user_blocks') IS NOT NULL")
        )
        if blocks_exist:
            blocked = await session.scalar(
                text(
                    "SELECT count(*) FROM user_blocks WHERE (blocker_user_id=:a AND blocked_user_id=:b) "
                    "OR (blocker_user_id=:b AND blocked_user_id=:a)"
                ),
                {"a": viewer_user_id, "b": candidate_user_id},
            )
            if int(blocked or 0):
                # The reason is deliberately coarse: no report detail crosses over.
                return {"allowed": False, "reason_code": "blocked", "restriction_version": 1}
        restrictions_exist = await session.scalar(
            text("SELECT to_regclass('public.user_safety_restrictions') IS NOT NULL")
        )
        if restrictions_exist:
            restricted = await session.scalar(
                text(
                    "SELECT count(*) FROM user_safety_restrictions WHERE user_id IN (:a,:b) "
                    "AND status='active' AND blocks_recommendations=true"
                ),
                {"a": viewer_user_id, "b": candidate_user_id},
            )
            if int(restricted or 0):
                return {
                    "allowed": False,
                    "reason_code": "safety_restricted",
                    "restriction_version": 1,
                }
    except Exception:  # noqa: BLE001 - the gateway must not leak on failure
        if settings.recommendation_fail_closed_on_moderation_error:
            return {
                "allowed": False,
                "reason_code": "moderation_unavailable",
                "restriction_version": 0,
            }
        raise
    return {"allowed": True, "reason_code": None, "restriction_version": 1}


# --------------------------------------------------------------------------
# Recommendation pool
# --------------------------------------------------------------------------


async def sync_pool_entry(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Refresh one member's pool entry from their Batch 13 projection."""
    projection = (
        (
            await session.execute(
                text(
                    f"SELECT {PROJECTION_COLUMNS} FROM dating_profile_recommendation_projections WHERE user_id=:id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    tuning = (
        (
            await session.execute(
                text(
                    "SELECT recommendations_paused FROM recommendation_user_tuning_profiles WHERE user_id=:id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    paused = bool(tuning and tuning["recommendations_paused"])

    if projection is None:
        removed = await session.execute(
            text("DELETE FROM recommendation_pool_entries WHERE user_id=:id"), {"id": user_id}
        )
        if int(getattr(removed, "rowcount", 0) or 0):
            await emit_event(
                session, "recommendation.pool.user_removed", user_id, {"reason": "no_projection"}
            )
        return {"user_id": str(user_id), "eligible": False, "reasons": ["projection_not_eligible"]}

    account_status = await session.scalar(
        text("SELECT status FROM users WHERE id=:id"), {"id": user_id}
    )
    reasons: list[str] = []
    if account_status != "active":
        reasons.append("account_not_active")
    if not projection["eligible"]:
        reasons.append("projection_not_eligible")
    if paused:
        reasons.append("recommendations_paused")
    eligible = not reasons

    await session.execute(
        text(
            "INSERT INTO recommendation_pool_entries "
            "(user_id,dating_profile_id,profile_projection_version,preference_version,privacy_settings_version,"
            "country_code,region_code,city_code,age_bucket,age_years,gender_code,eligible_partner_gender_codes,"
            "relationship_intent,eligible,eligibility_reasons,recommendations_paused,pool_version,updated_at) "
            "VALUES (:user_id,:profile_id,:projection_version,:preference_version,:privacy_version,"
            ":country,:region,:city,:age_bucket,:age_years,:gender,CAST(:partner_genders AS jsonb),"
            ":intent,:eligible,CAST(:reasons AS jsonb),:paused,1,now()) "
            "ON CONFLICT (user_id) DO UPDATE SET dating_profile_id=EXCLUDED.dating_profile_id,"
            "profile_projection_version=EXCLUDED.profile_projection_version,"
            "preference_version=EXCLUDED.preference_version,privacy_settings_version=EXCLUDED.privacy_settings_version,"
            "country_code=EXCLUDED.country_code,region_code=EXCLUDED.region_code,city_code=EXCLUDED.city_code,"
            "age_bucket=EXCLUDED.age_bucket,age_years=EXCLUDED.age_years,gender_code=EXCLUDED.gender_code,"
            "eligible_partner_gender_codes=EXCLUDED.eligible_partner_gender_codes,"
            "relationship_intent=EXCLUDED.relationship_intent,eligible=EXCLUDED.eligible,"
            "eligibility_reasons=EXCLUDED.eligibility_reasons,recommendations_paused=EXCLUDED.recommendations_paused,"
            "pool_version=recommendation_pool_entries.pool_version+1,updated_at=now()"
        ),
        {
            "user_id": user_id,
            "profile_id": projection["dating_profile_id"],
            "projection_version": projection["projection_version"],
            "preference_version": projection["preference_version"],
            "privacy_version": projection["privacy_settings_version"],
            "country": projection["country_code"],
            "region": projection["region_code"],
            "city": projection["city_code"],
            "age_bucket": projection["age_bucket"],
            "age_years": projection["age_years"],
            "gender": projection["gender_code"],
            "partner_genders": json_value(projection["eligible_partner_gender_codes"]),
            "intent": projection["relationship_intent"],
            "eligible": eligible,
            "reasons": json_value(reasons),
            "paused": paused,
        },
    )
    await emit_event(
        session,
        "recommendation.pool.user_added" if eligible else "recommendation.pool.user_removed",
        user_id,
        {"eligible": eligible, "reasons": reasons},
    )
    return {"user_id": str(user_id), "eligible": eligible, "reasons": reasons}


async def rebuild_pool(session: AsyncSession) -> dict[str, Any]:
    """Refresh every pool entry from the current projections."""
    enabled()
    user_ids = (
        (
            await session.execute(
                text("SELECT user_id FROM dating_profile_recommendation_projections")
            )
        )
        .scalars()
        .all()
    )
    eligible = 0
    for user_id in user_ids:
        result = await sync_pool_entry(session, user_id)
        if result["eligible"]:
            eligible += 1
    # Members whose projection disappeared must leave the pool too.
    await session.execute(
        text(
            "DELETE FROM recommendation_pool_entries WHERE user_id NOT IN "
            "(SELECT user_id FROM dating_profile_recommendation_projections)"
        )
    )
    await session.commit()
    return {"synced": len(user_ids), "eligible": eligible}


async def projection_for(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {PROJECTION_COLUMNS} FROM dating_profile_recommendation_projections WHERE user_id=:id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RECOMMENDATION_PROJECTION_MISSING",
            "This member has no recommendation projection.",
            status_code=409,
        )
    return dict(row)


async def require_pool_entry(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_pool_entries WHERE user_id=:id"),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RECOMMENDATION_NOT_IN_POOL",
            "You are not currently in the recommendation pool.",
            status_code=409,
            details=[{"reasons": ["projection_not_eligible"]}],
        )
    if not row["eligible"]:
        raise VavError(
            "RECOMMENDATION_NOT_ELIGIBLE",
            "Your profile does not currently qualify for recommendations.",
            status_code=409,
            details=[{"reasons": list(row["eligibility_reasons"])}],
        )
    return dict(row)


# --------------------------------------------------------------------------
# Candidate recall and generation
# --------------------------------------------------------------------------


async def _recall_candidates(
    session: AsyncSession, viewer: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """Deterministic coarse recall over normalised pool columns only.

    Full profiles are never loaded into memory: recall reads indexed codes and
    is bounded by ``RECOMMENDATION_MAX_CANDIDATES_PER_USER``.
    """
    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.user_id, p.age_years, p.city_code, p.region_code, p.country_code "
                    "FROM recommendation_pool_entries p "
                    "WHERE p.eligible = true AND p.user_id <> :viewer_id "
                    # Both sides must already accept each other's gender.
                    "AND p.eligible_partner_gender_codes ? :viewer_gender "
                    "AND CAST(:partner_genders AS jsonb) ? p.gender_code "
                    "ORDER BY (p.country_code = :country) DESC, (p.region_code = :region) DESC, "
                    "(p.city_code = :city) DESC, p.updated_at DESC LIMIT :limit"
                ),
                {
                    "viewer_id": viewer["user_id"],
                    "viewer_gender": viewer["gender_code"],
                    "partner_genders": json_value(viewer["eligible_partner_gender_codes"]),
                    "country": viewer["country_code"],
                    "region": viewer["region_code"],
                    "city": viewer["city_code"],
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def _excluded_user_ids(session: AsyncSession, viewer_id: UUID) -> set[UUID]:
    """Everyone this member must not be shown right now."""
    excluded: set[UUID] = {viewer_id}
    cooldowns = (
        (
            await session.execute(
                text(
                    "SELECT skipped_user_id FROM recommendation_skip_cooldowns "
                    "WHERE viewer_user_id=:id AND cooldown_until > now()"
                ),
                {"id": viewer_id},
            )
        )
        .scalars()
        .all()
    )
    excluded.update(cooldowns)

    settings = get_settings()
    recent = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT exposed_user_id FROM recommendation_exposures "
                    "WHERE viewer_user_id=:id AND exposed_at > now() - make_interval(days => :days)"
                ),
                {"id": viewer_id, "days": settings.recommendation_repeat_exposure_cooldown_days},
            )
        )
        .scalars()
        .all()
    )
    excluded.update(recent)

    # Batch 15/16 own interactions and relationships; read them if present.
    for table, column_a, column_b, clause in (
        (
            "matchmaking_interactions",
            "initiator_user_id",
            "target_user_id",
            "status IN ('pending','accepted')",
        ),
        ("relationship_journeys", "user_a_id", "user_b_id", "status NOT IN ('ended','archived')"),
    ):
        exists = await session.scalar(text(f"SELECT to_regclass('public.{table}') IS NOT NULL"))
        if not exists:
            continue
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT {column_a} AS a, {column_b} AS b FROM {table} "
                        f"WHERE ({column_a}=:id OR {column_b}=:id) AND {clause}"
                    ),
                    {"id": viewer_id},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            excluded.add(row["a"])
            excluded.add(row["b"])
    return excluded


async def generate_candidates(
    session: AsyncSession, viewer_user_id: UUID, *, commit: bool = True
) -> dict[str, Any]:
    """Build and persist evaluated candidate pairs for one member."""
    enabled()
    settings = get_settings()
    strategy = await active_strategy(session)
    viewer_entry = await require_pool_entry(session, viewer_user_id)
    viewer_projection = await projection_for(session, viewer_user_id)
    viewer_criteria = list(viewer_projection["indexed_preference_criteria"])

    tuning = await tuning_profile(session, viewer_user_id)
    allow_relaxation = bool(
        settings.recommendation_allow_user_relaxation and tuning["allow_relaxed_recommendations"]
    )
    relaxable = frozenset(strategy["hard_constraint_policy"].get("relaxable_criteria", []))

    excluded = await _excluded_user_ids(session, viewer_user_id)
    recalled = await _recall_candidates(
        session, viewer_entry, settings.recommendation_max_candidates_per_user
    )

    evaluations: list[dict[str, Any]] = []
    generated = 0
    safety_blocked = 0
    valid_until = utcnow() + timedelta(days=settings.recommendation_candidate_validity_days)

    for candidate in recalled:
        candidate_id = candidate["user_id"]
        if candidate_id in excluded:
            continue
        safety = await evaluate_recommendation_pair_safety(session, viewer_user_id, candidate_id)
        if not safety["allowed"]:
            safety_blocked += 1
            continue

        candidate_projection = await projection_for(session, candidate_id)
        candidate_criteria = list(candidate_projection["indexed_preference_criteria"])
        evaluation = constraints.evaluate_pair(
            viewer_projection=viewer_projection,
            candidate_projection=candidate_projection,
            viewer_criteria=viewer_criteria,
            candidate_criteria=candidate_criteria,
            viewer_preference_version=int(viewer_projection["preference_version"]),
            candidate_preference_version=int(candidate_projection["preference_version"]),
            viewer_allows_relaxation=allow_relaxation,
            relaxable_criteria=relaxable,
        )
        evaluations.append(evaluation)

        low_id, high_id = normalise_pair(viewer_user_id, candidate_id)
        low_projection = viewer_projection if low_id == viewer_user_id else candidate_projection
        high_projection = candidate_projection if low_id == viewer_user_id else viewer_projection
        status = (
            CandidatePairStatus.ELIGIBLE.value
            if evaluation["passed"]
            else CandidatePairStatus.HARD_CONSTRAINT_FAILED.value
        )

        pair_id = await session.scalar(
            text(
                "INSERT INTO recommendation_candidate_pairs "
                "(user_low_id,user_high_id,low_profile_projection_version,high_profile_projection_version,"
                "low_preference_version,high_preference_version,strategy_id,status,eligibility_snapshot,"
                "hard_constraint_snapshot,valid_until) "
                "VALUES (:low,:high,:low_proj,:high_proj,:low_pref,:high_pref,:strategy,:status,"
                "CAST(:eligibility AS jsonb),CAST(:constraints AS jsonb),:valid_until) "
                "ON CONFLICT (user_low_id,user_high_id,strategy_id,low_profile_projection_version,"
                "high_profile_projection_version,low_preference_version,high_preference_version) "
                "DO UPDATE SET status=EXCLUDED.status,hard_constraint_snapshot=EXCLUDED.hard_constraint_snapshot,"
                "valid_until=EXCLUDED.valid_until,invalidated_at=NULL,invalidation_reason=NULL RETURNING id"
            ),
            {
                "low": low_id,
                "high": high_id,
                "low_proj": low_projection["projection_version"],
                "high_proj": high_projection["projection_version"],
                "low_pref": low_projection["preference_version"],
                "high_pref": high_projection["preference_version"],
                "strategy": strategy["id"],
                "status": status,
                "eligibility": json_value(
                    {"safety_allowed": True, "recall_stage": "normalised_codes_only"}
                ),
                "constraints": json_value(
                    {
                        "passed": evaluation["passed"],
                        "blocking_codes": evaluation["blocking_codes"],
                        "unknown_codes": evaluation["unknown_codes"],
                        "relaxations_applied": evaluation["relaxations_applied"],
                        "policy_version": evaluation["policy_version"],
                    }
                ),
                "valid_until": valid_until,
            },
        )
        generated += 1

        if evaluation["passed"]:
            await _score_pair(
                session,
                pair_id=UUID(str(pair_id)),
                viewer_user_id=viewer_user_id,
                candidate_user_id=candidate_id,
                viewer_projection=viewer_projection,
                candidate_projection=candidate_projection,
                viewer_criteria=viewer_criteria,
                candidate_criteria=candidate_criteria,
                viewer_adjustments=tuning["feature_weight_adjustments"],
            )

    diagnostics = constraints.diagnostic_summary(evaluations)
    await audit(
        session,
        "recommendation.candidates.generated",
        "user",
        viewer_user_id,
        context={
            "recalled": len(recalled),
            "generated": generated,
            "safety_blocked": safety_blocked,
            "pass_rate_bps": diagnostics["pass_rate_bps"],
        },
    )
    if commit:
        await session.commit()
    return {
        "recalled": len(recalled),
        "generated": generated,
        "safety_blocked": safety_blocked,
        "diagnostics": diagnostics,
    }


async def _score_pair(
    session: AsyncSession,
    *,
    pair_id: UUID,
    viewer_user_id: UUID,
    candidate_user_id: UUID,
    viewer_projection: dict[str, Any],
    candidate_projection: dict[str, Any],
    viewer_criteria: list[dict[str, Any]],
    candidate_criteria: list[dict[str, Any]],
    viewer_adjustments: dict[str, int],
) -> dict[str, Any]:
    """Score both directions and persist them separately."""
    viewer_to_candidate = scoring.score_direction(
        source_projection=viewer_projection,
        target_projection=candidate_projection,
        source_criteria=viewer_criteria,
        weight_adjustments=viewer_adjustments,
    )
    candidate_to_viewer = scoring.score_direction(
        source_projection=candidate_projection,
        target_projection=viewer_projection,
        source_criteria=candidate_criteria,
    )
    for source_id, target_id, result in (
        (viewer_user_id, candidate_user_id, viewer_to_candidate),
        (candidate_user_id, viewer_user_id, candidate_to_viewer),
    ):
        await session.execute(
            text(
                "INSERT INTO recommendation_directional_scores "
                "(candidate_pair_id,source_user_id,target_user_id,total_score_bps,confidence_bps,"
                "feature_scores,missing_information,unknown_feature_count,scoring_policy_version) "
                "VALUES (:pair,:source,:target,:total,:confidence,CAST(:features AS jsonb),"
                "CAST(:missing AS jsonb),:unknown,:policy) "
                "ON CONFLICT (candidate_pair_id,source_user_id) DO UPDATE SET "
                "total_score_bps=EXCLUDED.total_score_bps,confidence_bps=EXCLUDED.confidence_bps,"
                "feature_scores=EXCLUDED.feature_scores,missing_information=EXCLUDED.missing_information,"
                "unknown_feature_count=EXCLUDED.unknown_feature_count,created_at=now()"
            ),
            {
                "pair": pair_id,
                "source": source_id,
                "target": target_id,
                "total": result["total_score_bps"],
                "confidence": result["confidence_bps"],
                "features": json_value(result["feature_scores"]),
                "missing": json_value(result["missing_information"]),
                "unknown": result["unknown_feature_count"],
                "policy": result["scoring_policy_version"],
            },
        )
    combined = bidirectional.combine(a_to_b=viewer_to_candidate, b_to_a=candidate_to_viewer)
    await session.execute(
        text(
            "UPDATE recommendation_candidate_pairs SET score_snapshot=CAST(:snapshot AS jsonb) WHERE id=:id"
        ),
        {
            "id": pair_id,
            "snapshot": json_value(
                {
                    "combined_score_bps": combined["combined_score_bps"],
                    "minimum_directional_score_bps": combined["minimum_directional_score_bps"],
                    "balance_score_bps": combined["balance_score_bps"],
                    "confidence_bps": combined["confidence_bps"],
                    "policy_version": combined["policy_version"],
                }
            ),
        },
    )
    return combined


async def invalidate_candidates_for(
    session: AsyncSession, user_id: UUID, reason: str, *, commit: bool = True
) -> dict[str, Any]:
    """Mark a member's candidates invalid and drop their unexposed items.

    Historical scores and audit records are preserved; only future exposure is
    prevented.
    """
    result = await session.execute(
        text(
            "UPDATE recommendation_candidate_pairs SET status='invalidated',invalidated_at=now(),"
            "invalidation_reason=:reason WHERE (user_low_id=:id OR user_high_id=:id) AND invalidated_at IS NULL"
        ),
        {"id": user_id, "reason": reason[:128]},
    )
    items = await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated',invalidation_reason=:reason "
            "WHERE (viewer_user_id=:id OR recommended_user_id=:id) AND status IN ('ready','exposed')"
        ),
        {"id": user_id, "reason": reason[:128]},
    )
    await audit(
        session,
        "recommendation.candidate.invalidated",
        "user",
        user_id,
        reason=reason,
        context={
            "pairs": int(getattr(result, "rowcount", 0) or 0),
            "items": int(getattr(items, "rowcount", 0) or 0),
        },
    )
    if commit:
        await session.commit()
    return {
        "invalidated_pairs": int(getattr(result, "rowcount", 0) or 0),
        "invalidated_items": int(getattr(items, "rowcount", 0) or 0),
    }


# --------------------------------------------------------------------------
# Tuning profile
# --------------------------------------------------------------------------


async def tuning_profile(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    row = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_user_tuning_profiles WHERE user_id=:id"),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        await session.execute(
            text(
                "INSERT INTO recommendation_user_tuning_profiles (user_id,feedback_personalization_enabled) "
                "VALUES (:id,:enabled) ON CONFLICT (user_id) DO NOTHING"
            ),
            {"id": user_id, "enabled": settings.recommendation_feedback_personalization_default},
        )
        row = (
            (
                await session.execute(
                    text("SELECT * FROM recommendation_user_tuning_profiles WHERE user_id=:id"),
                    {"id": user_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    return dict(row)


# --------------------------------------------------------------------------
# Exposure budget
# --------------------------------------------------------------------------


async def _budget(session: AsyncSession, user_id: UUID, budget_date: date) -> dict[str, Any]:
    settings = get_settings()
    tuning = await tuning_profile(session, user_id)
    received_limit = int(
        tuning["daily_received_limit"] or settings.recommendation_max_daily_received
    )
    await session.execute(
        text(
            "INSERT INTO recommendation_exposure_budgets "
            "(user_id,budget_date,daily_received_limit,daily_shown_limit) "
            "VALUES (:id,:day,:received,:shown) ON CONFLICT (user_id,budget_date) DO NOTHING"
        ),
        {
            "id": user_id,
            "day": budget_date,
            "received": received_limit,
            "shown": settings.recommendation_max_daily_shown_per_profile,
        },
    )
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM recommendation_exposure_budgets WHERE user_id=:id AND budget_date=:day"
                ),
                {"id": user_id, "day": budget_date},
            )
        )
        .mappings()
        .first()
    )
    assert row is not None
    return dict(row)


# --------------------------------------------------------------------------
# Batch generation
# --------------------------------------------------------------------------


async def generate_batch(
    session: AsyncSession,
    viewer_user_id: UUID,
    *,
    batch_type: str = "daily",
    requested_size: int | None = None,
) -> dict[str, Any]:
    """Generate, validate and atomically activate one recommendation batch."""
    enabled()
    settings = get_settings()
    strategy = await active_strategy(session)
    viewer_entry = await require_pool_entry(session, viewer_user_id)
    viewer_projection = await projection_for(session, viewer_user_id)
    viewer_criteria = list(viewer_projection["indexed_preference_criteria"])
    tuning = await tuning_profile(session, viewer_user_id)

    if tuning["recommendations_paused"]:
        raise VavError(
            "RECOMMENDATION_PAUSED",
            "You paused recommendations. Resume them to receive a new batch.",
            status_code=409,
        )

    today = utcnow().date()
    budget = await _budget(session, viewer_user_id, today)
    remaining = exposure_rules.remaining_received(budget, int(budget["daily_received_limit"]))
    size = min(
        requested_size or settings.recommendation_daily_batch_size,
        settings.recommendation_daily_batch_size if batch_type == "daily" else remaining,
        remaining,
    )
    if size <= 0:
        raise VavError(
            "RECOMMENDATION_DAILY_LIMIT_REACHED",
            "You have reached today's recommendation limit.",
            status_code=429,
        )
    if batch_type == "supplemental" and not settings.recommendation_supplemental_batch_enabled:
        raise VavError(
            "RECOMMENDATION_SUPPLEMENTAL_DISABLED",
            "Supplemental batches are disabled.",
            status_code=409,
        )

    batch_number = int(
        await session.scalar(
            text(
                "SELECT COALESCE(MAX(batch_number),0)+1 FROM recommendation_batches WHERE user_id=:id"
            ),
            {"id": viewer_user_id},
        )
        or 1
    )
    seed = hashlib.sha256(
        f"{viewer_user_id}:{batch_number}:{strategy['semantic_version']}".encode()
    ).hexdigest()[:32]

    batch_id = await session.scalar(
        text(
            "INSERT INTO recommendation_batches "
            "(user_id,batch_number,batch_type,strategy_id,profile_projection_version,preference_version,"
            "privacy_settings_version,status,requested_size,random_seed,expires_at) "
            "VALUES (:user_id,:number,:type,:strategy,:projection,:preference,:privacy,'building',:size,:seed,"
            "now() + make_interval(days => :ttl)) RETURNING id"
        ),
        {
            "user_id": viewer_user_id,
            "number": batch_number,
            "type": batch_type,
            "strategy": strategy["id"],
            "projection": viewer_projection["projection_version"],
            "preference": viewer_projection["preference_version"],
            "privacy": viewer_projection["privacy_settings_version"],
            "size": size,
            "seed": seed,
            "ttl": settings.recommendation_batch_ttl_days,
        },
    )
    batch_uuid = UUID(str(batch_id))

    candidates = await _collect_scored_candidates(session, viewer_user_id, tuning)
    qualified: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = {}
    for candidate in candidates:
        ok, reasons = bidirectional.meets_thresholds(
            candidate["bidirectional"],
            minimum_directional_bps=settings.recommendation_min_directional_score_bps,
            minimum_bidirectional_bps=settings.recommendation_min_bidirectional_score_bps,
            minimum_confidence_bps=settings.recommendation_min_confidence_bps,
        )
        if not ok:
            for reason in reasons:
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
            continue
        # Respect the other member's daily show budget before selecting them.
        candidate_budget = await _budget(session, candidate["candidate_user_id"], today)
        if not exposure_rules.can_show_profile(
            candidate_budget, int(candidate_budget["daily_shown_limit"])
        ):
            rejected_reasons["candidate_show_budget_exhausted"] = (
                rejected_reasons.get("candidate_show_budget_exhausted", 0) + 1
            )
            continue
        qualified.append(candidate)

    cold_start_types = coldstart.classify(
        account_created_at=await _account_created_at(session, viewer_user_id),
        profile_approved_at=await _profile_approved_at(session, viewer_user_id),
        criteria_count=len(viewer_criteria),
        pool_size_in_region=len(candidates),
        interaction_count=await _interaction_count(session, viewer_user_id),
    )
    exploration_slots = coldstart.exploration_slot_count(
        cold_start_types, str(tuning["exploration_level"]), strategy["cold_start_policy"]
    )

    adjusted = ranking.apply_adjustments(qualified, seed=seed, policy=strategy["ranking_policy"])
    main_size = max(0, size - min(exploration_slots, max(0, size - 1)))
    selected = ranking.diversify(
        adjusted, size=main_size, policy=strategy["diversification_policy"]
    )
    selected_ids = {str(item["candidate_pair_id"]) for item in selected}
    exploration = coldstart.select_exploration_candidates(
        adjusted,
        already_selected_ids=selected_ids,
        slots=size - len(selected),
        minimum_bidirectional_bps=settings.recommendation_min_bidirectional_score_bps,
    )
    for position, candidate in enumerate(exploration, start=len(selected) + 1):
        candidate["final_rank"] = position
    final = selected + exploration

    for candidate in final:
        explanation = explanations.build(
            viewer_score=candidate["viewer_score"],
            bidirectional=candidate["bidirectional"],
            viewer_criteria=viewer_criteria,
            relaxations_applied=candidate.get("relaxations_applied", []),
        )
        explanations.assert_safe(explanation)
        await session.execute(
            text(
                "INSERT INTO recommendation_items "
                "(recommendation_batch_id,viewer_user_id,recommended_user_id,candidate_pair_id,rank_position,"
                "viewer_to_candidate_score_bps,candidate_to_viewer_score_bps,bidirectional_score_bps,confidence_bps,"
                "is_exploration_slot,relaxation_applied,explanation_snapshot,visible_profile_snapshot,expires_at) "
                "VALUES (:batch,:viewer,:candidate,:pair,:rank,:v2c,:c2v,:bi,:confidence,:exploration,"
                "CAST(:relaxation AS jsonb),CAST(:explanation AS jsonb),CAST(:snapshot AS jsonb),"
                "now() + make_interval(days => :ttl))"
            ),
            {
                "batch": batch_uuid,
                "viewer": viewer_user_id,
                "candidate": candidate["candidate_user_id"],
                "pair": candidate["candidate_pair_id"],
                "rank": candidate["final_rank"],
                "v2c": candidate["bidirectional"]["user_a_to_b_score_bps"],
                "c2v": candidate["bidirectional"]["user_b_to_a_score_bps"],
                "bi": candidate["bidirectional"]["combined_score_bps"],
                "confidence": candidate["bidirectional"]["confidence_bps"],
                "exploration": bool(candidate.get("is_exploration_slot")),
                "relaxation": json_value(candidate.get("relaxations_applied", [])),
                "explanation": json_value(explanation),
                "snapshot": json_value(candidate["visible_snapshot"]),
                "ttl": settings.recommendation_batch_ttl_days,
            },
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_rank_results "
                "(recommendation_batch_id,candidate_pair_id,base_score_bps,adjusted_score_bps,"
                "novelty_adjustment_bps,diversity_adjustment_bps,exposure_adjustment_bps,"
                "exploration_adjustment_bps,final_rank,adjustment_snapshot) "
                "VALUES (:batch,:pair,:base,:adjusted,:novelty,:diversity,:exposure,:exploration,:rank,"
                "CAST(:snapshot AS jsonb)) ON CONFLICT (recommendation_batch_id,candidate_pair_id) DO NOTHING"
            ),
            {
                "batch": batch_uuid,
                "pair": candidate["candidate_pair_id"],
                "base": candidate["base_score_bps"],
                "adjusted": candidate["adjusted_score_bps"],
                "novelty": candidate["novelty_adjustment_bps"],
                "diversity": candidate.get("diversity_adjustment_bps", 0),
                "exposure": candidate["exposure_adjustment_bps"],
                "exploration": candidate["exploration_adjustment_bps"],
                "rank": candidate["final_rank"],
                "snapshot": json_value(candidate["adjustment_snapshot"]),
            },
        )

    report = {
        "recalled_candidates": len(candidates),
        "qualified_candidates": len(qualified),
        "selected": len(final),
        "exploration_slots": len(exploration),
        "cold_start_types": cold_start_types,
        "rejection_reasons": rejected_reasons,
        "intra_list_diversity_bps": ranking.intra_list_diversity(final),
        "strategy_version": strategy["semantic_version"],
        "seed": seed,
    }

    # Only one batch may be active; the previous one is exhausted first.
    await session.execute(
        text(
            "UPDATE recommendation_batches SET status='exhausted' WHERE user_id=:id AND status='active'"
        ),
        {"id": viewer_user_id},
    )
    await session.execute(
        text(
            "UPDATE recommendation_batches SET status='active',generated_size=:size,generated_at=now(),"
            "activated_at=now(),generation_report=CAST(:report AS jsonb) WHERE id=:id"
        ),
        {"id": batch_uuid, "size": len(final), "report": json_value(report)},
    )
    await session.execute(
        text(
            "UPDATE recommendation_exposure_budgets SET current_received_count=current_received_count+:count,"
            "updated_at=now() WHERE user_id=:id AND budget_date=:day"
        ),
        {"count": len(final), "id": viewer_user_id, "day": today},
    )
    await audit(
        session,
        "recommendation.batch.activated",
        "recommendation_batch",
        batch_uuid,
        actor_id=viewer_user_id,
        context={"size": len(final), "strategy_version": strategy["semantic_version"]},
    )
    await emit_event(session, "recommendation.batch.generated", batch_uuid, {"size": len(final)})
    await session.commit()
    return {
        "batch_id": str(batch_uuid),
        "batch_number": batch_number,
        "status": RecommendationBatchStatus.ACTIVE.value,
        "size": len(final),
        "report": report,
        "pool_entry_version": viewer_entry["pool_version"],
    }


async def _collect_scored_candidates(
    session: AsyncSession, viewer_user_id: UUID, tuning: dict[str, Any]
) -> list[dict[str, Any]]:
    """Load eligible pairs plus both directional scores and exposure history."""
    rows = (
        (
            await session.execute(
                text(
                    "SELECT c.id AS candidate_pair_id, c.hard_constraint_snapshot, "
                    "CASE WHEN c.user_low_id=:viewer THEN c.user_high_id ELSE c.user_low_id END AS candidate_user_id "
                    "FROM recommendation_candidate_pairs c "
                    "WHERE (c.user_low_id=:viewer OR c.user_high_id=:viewer) "
                    "AND c.status='eligible' AND c.invalidated_at IS NULL "
                    "AND (c.valid_until IS NULL OR c.valid_until > now())"
                ),
                {"viewer": viewer_user_id},
            )
        )
        .mappings()
        .all()
    )
    settings = get_settings()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        scores = (
            (
                await session.execute(
                    text(
                        "SELECT source_user_id,total_score_bps,confidence_bps,feature_scores,missing_information "
                        "FROM recommendation_directional_scores WHERE candidate_pair_id=:pair"
                    ),
                    {"pair": row["candidate_pair_id"]},
                )
            )
            .mappings()
            .all()
        )
        by_source = {score["source_user_id"]: dict(score) for score in scores}
        viewer_score = by_source.get(viewer_user_id)
        candidate_score = by_source.get(row["candidate_user_id"])
        if viewer_score is None or candidate_score is None:
            continue

        viewer_result = {
            "total_score_bps": viewer_score["total_score_bps"],
            "confidence_bps": viewer_score["confidence_bps"],
            "feature_scores": viewer_score["feature_scores"],
            "missing_information": viewer_score["missing_information"],
        }
        candidate_result = {
            "total_score_bps": candidate_score["total_score_bps"],
            "confidence_bps": candidate_score["confidence_bps"],
            "feature_scores": candidate_score["feature_scores"],
            "missing_information": candidate_score["missing_information"],
        }
        combined = bidirectional.combine(a_to_b=viewer_result, b_to_a=candidate_result)

        exposure_row = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE viewer_user_id=:viewer) AS viewer_seen, "
                        "count(*) AS total_recent FROM recommendation_exposures "
                        "WHERE exposed_user_id=:candidate AND exposed_at > now() - interval '7 days'"
                    ),
                    {"viewer": viewer_user_id, "candidate": row["candidate_user_id"]},
                )
            )
            .mappings()
            .first()
        )
        if exposure_row is None:
            continue
        projection = await projection_for(session, row["candidate_user_id"])
        snapshot = _visible_snapshot(projection)
        approved_at = await _profile_approved_at(session, row["candidate_user_id"])
        recency = 0
        if approved_at is not None:
            age_days = (utcnow() - approved_at).days
            recency = max(0, 30 - age_days)

        candidates.append(
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "candidate_user_id": row["candidate_user_id"],
                "viewer_score": viewer_result,
                "candidate_score": candidate_result,
                "bidirectional": combined,
                "bidirectional_score_bps": combined["combined_score_bps"],
                "confidence_bps": combined["confidence_bps"],
                "city_code": projection["city_code"],
                "faith_codes": projection["faith_codes"],
                "lifestyle_codes": projection["lifestyle_codes"],
                "never_exposed": int(exposure_row["total_recent"] or 0) == 0,
                "recently_exposed": int(exposure_row["viewer_seen"] or 0) > 0,
                "recent_exposure_count": int(exposure_row["total_recent"] or 0),
                "profile_recency_score": recency,
                "hard_constraints_passed": True,
                "safety_allowed": True,
                "relaxations_applied": list(
                    (row["hard_constraint_snapshot"] or {}).get("relaxations_applied", [])
                ),
                "visible_snapshot": snapshot,
                "exploration_adjustment_bps": 0,
            }
        )
    _ = settings
    _ = tuning
    return candidates


def _visible_snapshot(projection: dict[str, Any]) -> dict[str, Any]:
    """Freeze only the coarse, already-approved values a card may show.

    Contact details, exact birth dates, narratives and preference criteria are
    structurally absent — the projection never carried them.
    """
    return {
        "age_bucket": projection["age_bucket"],
        "city_code": projection["city_code"],
        "region_code": projection["region_code"],
        "country_code": projection["country_code"],
        "relationship_intent": projection["relationship_intent"],
        "approved_profile_version": projection["approved_profile_version"],
        "privacy_settings_version": projection["privacy_settings_version"],
        "projection_checksum": projection["projection_checksum"],
    }


async def _account_created_at(session: AsyncSession, user_id: UUID) -> datetime:
    value = await session.scalar(text("SELECT created_at FROM users WHERE id=:id"), {"id": user_id})
    return value or utcnow()


async def _profile_approved_at(session: AsyncSession, user_id: UUID) -> datetime | None:
    value = await session.scalar(
        text("SELECT approved_at FROM dating_profiles WHERE user_id=:id"), {"id": user_id}
    )
    return value if isinstance(value, datetime) else None


async def _interaction_count(session: AsyncSession, user_id: UUID) -> int:
    value = await session.scalar(
        text(
            "SELECT count(*) FROM recommendation_feedback_events WHERE viewer_user_id=:id "
            "AND feedback_type IN ('liked','skipped','not_relevant')"
        ),
        {"id": user_id},
    )
    return int(value or 0)


# --------------------------------------------------------------------------
# Reading a batch
# --------------------------------------------------------------------------


async def current_batch(session: AsyncSession, viewer: User) -> dict[str, Any]:
    """Return the active batch, re-checking every item's current eligibility."""
    enabled()
    batch = (
        (
            await session.execute(
                text(
                    "SELECT * FROM recommendation_batches WHERE user_id=:id AND status='active' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": viewer.id},
            )
        )
        .mappings()
        .first()
    )
    if batch is None:
        return {"has_batch": False, "items": [], "guidance": await empty_guidance(session, viewer)}

    if batch["expires_at"] and batch["expires_at"] < utcnow():
        await session.execute(
            text("UPDATE recommendation_batches SET status='expired' WHERE id=:id"),
            {"id": batch["id"]},
        )
        await session.commit()
        return {"has_batch": False, "items": [], "guidance": await empty_guidance(session, viewer)}

    rows = (
        (
            await session.execute(
                text(
                    "SELECT i.*, d.status AS profile_status, d.approved_version_number "
                    "FROM recommendation_items i "
                    "JOIN dating_profiles d ON d.user_id=i.recommended_user_id "
                    "WHERE i.recommendation_batch_id=:batch AND i.status IN ('ready','exposed','viewed') "
                    "ORDER BY i.rank_position"
                ),
                {"batch": batch["id"]},
            )
        )
        .mappings()
        .all()
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        # A frozen snapshot is not a licence: re-check the live state.
        if row["profile_status"] != "active" or row["approved_version_number"] is None:
            await _invalidate_item(session, row["id"], "profile_no_longer_active")
            continue
        safety = await evaluate_recommendation_pair_safety(
            session, viewer.id, row["recommended_user_id"]
        )
        if not safety["allowed"]:
            await _invalidate_item(session, row["id"], safety["reason_code"] or "safety_blocked")
            continue
        visible = await session.scalar(
            text("SELECT visible_in_matchmaking FROM user_privacy_settings WHERE user_id=:id"),
            {"id": row["recommended_user_id"]},
        )
        if not visible:
            await _invalidate_item(session, row["id"], "privacy_withdrawn")
            continue
        items.append(_item_dto(dict(row)))

    await session.commit()
    return {
        "has_batch": bool(items),
        "batch_id": str(batch["id"]),
        "batch_number": batch["batch_number"],
        "batch_type": batch["batch_type"],
        "expires_at": batch["expires_at"],
        "items": items,
        "guidance": None if items else await empty_guidance(session, viewer),
    }


def _item_dto(row: dict[str, Any]) -> dict[str, Any]:
    """The member-facing shape. No percentages, no directional scores."""
    return {
        "recommendation_item_id": str(row["id"]),
        "recommended_user_id": str(row["recommended_user_id"]),
        "rank_position": row["rank_position"],
        "status": row["status"],
        "is_exploration_slot": row["is_exploration_slot"],
        "relaxation_applied": list(row["relaxation_applied"] or []),
        "explanation": row["explanation_snapshot"],
        "profile_summary": row["visible_profile_snapshot"],
        "available_from": row["available_from"],
        "expires_at": row["expires_at"],
    }


async def _invalidate_item(session: AsyncSession, item_id: UUID, reason: str) -> None:
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated',invalidation_reason=:reason WHERE id=:id"
        ),
        {"id": item_id, "reason": reason[:128]},
    )
    await audit(
        session,
        "recommendation.item.invalidated",
        "recommendation_item",
        item_id,
        reason=reason,
    )


async def empty_guidance(session: AsyncSession, viewer: User) -> dict[str, Any]:
    """Explain an empty result honestly, with aggregate reasons only."""
    pairs = (
        (
            await session.execute(
                text(
                    "SELECT hard_constraint_snapshot FROM recommendation_candidate_pairs "
                    "WHERE (user_low_id=:id OR user_high_id=:id) AND invalidated_at IS NULL "
                    "ORDER BY generated_at DESC LIMIT 500"
                ),
                {"id": viewer.id},
            )
        )
        .scalars()
        .all()
    )
    evaluations = [
        {
            "passed": bool((snapshot or {}).get("passed")),
            "blocking_codes": list((snapshot or {}).get("blocking_codes", [])),
            "unknown_codes": list((snapshot or {}).get("unknown_codes", [])),
        }
        for snapshot in pairs
    ]
    diagnostics = constraints.diagnostic_summary(evaluations)
    return coldstart.empty_result_guidance(diagnostics)


# --------------------------------------------------------------------------
# Exposure recording
# --------------------------------------------------------------------------


async def record_exposure(
    session: AsyncSession,
    viewer: User,
    item_id: UUID,
    *,
    exposure_type: str,
    duration_ms: int | None,
    idempotency_key: str,
    source: str = "user_web",
) -> dict[str, Any]:
    """Record an exposure idempotently and count it only when truly visible."""
    enabled()
    settings = get_settings()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,viewer_user_id,recommended_user_id,status FROM recommendation_items WHERE id=:id"
                ),
                {"id": item_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["viewer_user_id"] != viewer.id:
        raise VavError(
            "RECOMMENDATION_ITEM_NOT_FOUND", "Recommendation not found.", status_code=404
        )

    visible = exposure_rules.counts_as_visible(
        exposure_type,
        duration_ms,
        minimum_visible_ms=settings.recommendation_exposure_visible_min_ms,
    )
    inserted = await session.scalar(
        text(
            "INSERT INTO recommendation_exposures "
            "(recommendation_item_id,viewer_user_id,exposed_user_id,exposure_type,source,duration_ms,"
            "counted_as_visible,idempotency_key) "
            "VALUES (:item,:viewer,:exposed,:type,:source,:duration,:visible,:key) "
            "ON CONFLICT (viewer_user_id,idempotency_key) DO NOTHING RETURNING id"
        ),
        {
            "item": item_id,
            "viewer": viewer.id,
            "exposed": row["recommended_user_id"],
            "type": exposure_type,
            "source": source,
            "duration": duration_ms,
            "visible": visible,
            "key": idempotency_key[:128],
        },
    )
    if inserted is None:
        await session.commit()
        return {"recorded": False, "duplicate": True, "counted_as_visible": visible}

    if visible:
        await session.execute(
            text(
                "UPDATE recommendation_items SET status=CASE WHEN status='ready' THEN 'exposed' ELSE status END,"
                "exposed_at=COALESCE(exposed_at, now()) WHERE id=:id"
            ),
            {"id": item_id},
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_exposure_budgets (user_id,budget_date,daily_received_limit,daily_shown_limit,current_shown_count) "
                "VALUES (:id,CURRENT_DATE,:received,:shown,1) "
                "ON CONFLICT (user_id,budget_date) DO UPDATE SET current_shown_count="
                "recommendation_exposure_budgets.current_shown_count+1,updated_at=now()"
            ),
            {
                "id": row["recommended_user_id"],
                "received": settings.recommendation_max_daily_received,
                "shown": settings.recommendation_max_daily_shown_per_profile,
            },
        )
    if exposure_type in {"profile_opened", "photo_viewed"}:
        await session.execute(
            text(
                "UPDATE recommendation_items SET status=CASE WHEN status IN ('ready','exposed') THEN 'viewed' ELSE status END,"
                "viewed_at=COALESCE(viewed_at, now()) WHERE id=:id"
            ),
            {"id": item_id},
        )
    await audit(
        session,
        "recommendation.item.exposed" if visible else "recommendation.item.viewed",
        "recommendation_item",
        item_id,
        actor_id=viewer.id,
        context={"exposure_type": exposure_type, "counted_as_visible": visible},
    )
    await session.commit()
    return {"recorded": True, "duplicate": False, "counted_as_visible": visible}


def generate_idempotency_key() -> str:
    return secrets.token_urlsafe(24)


def can_activate(current: str) -> bool:
    return can_transition_batch(current, RecommendationBatchStatus.ACTIVE.value)


def item_status_ready() -> str:
    return RecommendationItemStatus.READY.value
