"""Recommendation application service: pool, candidates, scoring and strategy.

Every stage is separate and versioned — pool eligibility, recall, both
directions of hard constraints, directional scoring, bidirectional composition
— so each can be tested and diagnosed on its own, and every result can be
reproduced from the stored snapshots.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.recommendations import bidirectional as bidirectional_engine
from vav.modules.recommendations import cold_start, constraints
from vav.modules.recommendations import scoring as scoring_engine
from vav.modules.recommendations.domain import (
    CandidatePairStatus,
    RecommendationStrategyStatus,
    can_transition_strategy,
    canonical_pair,
)
from vav.modules.recommendations.gateways import (
    InteractionGateway,
    ModerationGateway,
)

PROJECTION_FIELDS: tuple[str, ...] = (
    "age_bucket",
    "age_years",
    "country_code",
    "region_code",
    "city_code",
    "gender_code",
    "eligible_partner_gender_codes",
    "faith_codes",
    "relationship_intent",
    "marital_status_code",
    "children_status_code",
    "relocation_willingness",
    "language_codes",
    "lifestyle_codes",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def enabled() -> None:
    if not get_settings().recommendation_enabled:
        raise VavError("RECOMMENDATIONS_DISABLED", "Recommendations are disabled.", status_code=503)


def _jsonb(value: Any) -> Any:
    """Normalise a JSONB column that may arrive as text or as parsed JSON."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def projection_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Extract only the approved projection fields from a projection row."""
    return {field: _jsonb(row.get(field)) for field in PROJECTION_FIELDS}


# --------------------------------------------------------------------------
# Audit and events
# --------------------------------------------------------------------------


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

    Only identifiers, codes, versions and decisions are stored — never profile
    values, narratives or full preference criteria.
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
        await session.execute(
            text(
                "SELECT * FROM recommendation_strategies WHERE status='active' "
                "ORDER BY activated_at DESC NULLS LAST LIMIT 1"
            )
        )
    ).mappings()
    found = row.first()
    if found is None:
        raise VavError(
            "RECOMMENDATION_STRATEGY_MISSING",
            "No active recommendation strategy is configured.",
            status_code=503,
        )
    return dict(found)


async def strategy_by_id(session: AsyncSession, strategy_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_strategies WHERE id=:id"), {"id": strategy_id}
        )
    ).mappings()
    found = row.first()
    if found is None:
        raise VavError("RECOMMENDATION_STRATEGY_NOT_FOUND", "Strategy not found.", status_code=404)
    return dict(found)


async def create_strategy(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    actor_id: UUID | None,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO recommendation_strategies "
                "(strategy_code,semantic_version,status,hard_constraint_policy,feature_manifest,"
                "scoring_policy,bidirectional_policy,ranking_policy,diversification_policy,"
                "exposure_policy,explanation_policy,cold_start_policy,applicable_regions,"
                "applicable_segments,created_by) "
                "VALUES (:strategy_code,:semantic_version,'draft',CAST(:hard AS jsonb),CAST(:features AS jsonb),"
                "CAST(:scoring AS jsonb),CAST(:bidirectional AS jsonb),CAST(:ranking AS jsonb),"
                "CAST(:diversification AS jsonb),CAST(:exposure AS jsonb),CAST(:explanation AS jsonb),"
                "CAST(:cold_start AS jsonb),CAST(:regions AS jsonb),CAST(:segments AS jsonb),:actor) "
                "ON CONFLICT (strategy_code, semantic_version) DO NOTHING RETURNING *"
            ),
            {
                "strategy_code": payload["strategy_code"],
                "semantic_version": payload["semantic_version"],
                "hard": json_value(payload["hard_constraint_policy"]),
                "features": json_value(payload["feature_manifest"]),
                "scoring": json_value(payload["scoring_policy"]),
                "bidirectional": json_value(payload["bidirectional_policy"]),
                "ranking": json_value(payload["ranking_policy"]),
                "diversification": json_value(payload["diversification_policy"]),
                "exposure": json_value(payload["exposure_policy"]),
                "explanation": json_value(payload["explanation_policy"]),
                "cold_start": json_value(payload.get("cold_start_policy", {})),
                "regions": json_value(payload.get("applicable_regions", [])),
                "segments": json_value(payload.get("applicable_segments", [])),
                "actor": actor_id,
            },
        )
    ).mappings()
    created = row.first()
    if created is None:
        raise VavError(
            "RECOMMENDATION_STRATEGY_EXISTS",
            "A strategy with this code and version already exists.",
            status_code=409,
        )
    await audit(
        session,
        "recommendation.strategy.created",
        "recommendation_strategy",
        created["id"],
        actor_id=actor_id,
        context={
            "strategy_code": payload["strategy_code"],
            "semantic_version": payload["semantic_version"],
        },
    )
    return dict(created)


async def transition_strategy(
    session: AsyncSession,
    *,
    strategy_id: UUID,
    target_status: str,
    actor_id: UUID | None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Move a strategy through its lifecycle, enforcing release rules."""
    current = await strategy_by_id(session, strategy_id)
    if not can_transition_strategy(str(current["status"]), target_status):
        raise VavError(
            "RECOMMENDATION_STRATEGY_TRANSITION_INVALID",
            f"A strategy cannot move from {current['status']} to {target_status}.",
            status_code=409,
        )

    if target_status == RecommendationStrategyStatus.APPROVED.value:
        await _require_passing_evaluation(session, strategy_id)

    if target_status == RecommendationStrategyStatus.ACTIVE.value:
        await _require_passing_evaluation(session, strategy_id)
        if current["approved_by"] is None:
            raise VavError(
                "RECOMMENDATION_STRATEGY_NOT_APPROVED",
                "A strategy must be approved before activation.",
                status_code=409,
            )
        if actor_id is not None and current["approved_by"] == actor_id:
            raise VavError(
                "RECOMMENDATION_STRATEGY_SELF_ACTIVATION",
                "The approver of a strategy cannot also activate it.",
                status_code=409,
            )
        await session.execute(
            text(
                "UPDATE recommendation_strategies SET status='superseded', updated_at=now() "
                "WHERE strategy_code=:code AND status='active'"
            ),
            {"code": current["strategy_code"]},
        )

    assignments = {
        RecommendationStrategyStatus.APPROVED.value: ("approved_by=:actor, approved_at=now(), "),
        RecommendationStrategyStatus.ACTIVE.value: ("activated_by=:actor, activated_at=now(), "),
    }.get(target_status, "")

    row = (
        await session.execute(
            text(
                "UPDATE recommendation_strategies SET status=:status, "
                f"{assignments}updated_at=now() WHERE id=:id AND status=:expected RETURNING *"
            ),
            {
                "status": target_status,
                "id": strategy_id,
                "expected": current["status"],
                "actor": actor_id,
            },
        )
    ).mappings()
    updated = row.first()
    if updated is None:
        raise VavError(
            "RECOMMENDATION_STRATEGY_CONFLICT",
            "The strategy changed while this request was in flight.",
            status_code=409,
        )

    event = {
        RecommendationStrategyStatus.APPROVED.value: "recommendation.strategy.approved",
        RecommendationStrategyStatus.ACTIVE.value: "recommendation.strategy.activated",
        RecommendationStrategyStatus.ROLLED_BACK.value: "recommendation.strategy.rolled_back",
    }.get(target_status, "recommendation.strategy.updated")
    await audit(
        session,
        event,
        "recommendation_strategy",
        strategy_id,
        actor_id=actor_id,
        reason=reason,
        context={"status": target_status},
    )
    return dict(updated)


async def _require_passing_evaluation(session: AsyncSession, strategy_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT status, blocking_failures, guardrail_failures FROM recommendation_evaluation_runs "
                "WHERE strategy_id=:id ORDER BY started_at DESC LIMIT 1"
            ),
            {"id": strategy_id},
        )
    ).mappings()
    latest = row.first()
    if latest is None or str(latest["status"]) != "passed":
        await audit(
            session,
            "recommendation.release.blocked",
            "recommendation_strategy",
            strategy_id,
            reason="evaluation_not_passed",
        )
        raise VavError(
            "RECOMMENDATION_EVALUATION_REQUIRED",
            "A strategy needs a passing offline evaluation before release.",
            status_code=409,
        )


# --------------------------------------------------------------------------
# Member settings and tuning
# --------------------------------------------------------------------------


async def user_settings(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_user_settings WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    if found is not None:
        record = dict(found)
        record["relaxable_criteria"] = _jsonb(record.get("relaxable_criteria")) or []
        return record
    return {
        "user_id": user_id,
        "recommendations_paused": False,
        "daily_received_limit": None,
        "delivery_frequency": "daily",
        "extended_recommendations_enabled": False,
        "relaxable_criteria": [],
        "preferred_locale": settings.dating_profile_default_locale,
        "settings_version": 1,
    }


async def update_user_settings(
    session: AsyncSession, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Members control quantity, pacing and their own relaxations only.

    Nothing here can bypass safety, another member's conditions or privacy.
    """
    current = await user_settings(session, user_id)
    merged = {**current, **{key: value for key, value in payload.items() if value is not None}}
    limit = merged.get("daily_received_limit")
    if limit is not None:
        merged["daily_received_limit"] = max(
            0, min(int(limit), get_settings().recommendation_max_daily_received)
        )
    await session.execute(
        text(
            "INSERT INTO recommendation_user_settings "
            "(user_id,recommendations_paused,daily_received_limit,delivery_frequency,"
            "extended_recommendations_enabled,relaxable_criteria,preferred_locale,settings_version,updated_at) "
            "VALUES (:user_id,:paused,:limit,:frequency,:extended,CAST(:relaxable AS jsonb),:locale,"
            "COALESCE((SELECT settings_version + 1 FROM recommendation_user_settings WHERE user_id=:user_id),1),now()) "
            "ON CONFLICT (user_id) DO UPDATE SET recommendations_paused=EXCLUDED.recommendations_paused,"
            "daily_received_limit=EXCLUDED.daily_received_limit,delivery_frequency=EXCLUDED.delivery_frequency,"
            "extended_recommendations_enabled=EXCLUDED.extended_recommendations_enabled,"
            "relaxable_criteria=EXCLUDED.relaxable_criteria,preferred_locale=EXCLUDED.preferred_locale,"
            "settings_version=recommendation_user_settings.settings_version + 1,updated_at=now()"
        ),
        {
            "user_id": user_id,
            "paused": bool(merged.get("recommendations_paused", False)),
            "limit": merged.get("daily_received_limit"),
            "frequency": str(merged.get("delivery_frequency", "daily")),
            "extended": bool(merged.get("extended_recommendations_enabled", False)),
            "relaxable": json_value(merged.get("relaxable_criteria", [])),
            "locale": str(merged.get("preferred_locale", "zh-CN")),
        },
    )
    await rebuild_pool_entry(session, user_id)
    await invalidate_candidates(session, user_id, reason="member_settings_changed")
    return await user_settings(session, user_id)


async def tuning_profile(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_user_tuning_profiles WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    if found is not None:
        record = dict(found)
        record["feature_weight_adjustments"] = (
            _jsonb(record.get("feature_weight_adjustments")) or {}
        )
        return record
    return {
        "user_id": user_id,
        "tuning_version": 1,
        "feature_weight_adjustments": {},
        "exploration_level": "balanced",
        "feedback_personalization_enabled": settings.recommendation_feedback_personalization_default,
        "derived_from_feedback_through": None,
    }


# --------------------------------------------------------------------------
# Recommendation pool
# --------------------------------------------------------------------------


async def rebuild_pool_entry(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    """Recompute one member's pool eligibility from the approved projection."""
    settings = get_settings()
    projection_row = (
        await session.execute(
            text("SELECT * FROM dating_profile_recommendation_projections WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).mappings()
    projection = projection_row.first()
    if projection is None:
        await session.execute(
            text("DELETE FROM recommendation_pool_entries WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
        await audit(
            session,
            "recommendation.pool.user_removed",
            "user",
            user_id,
            reason="no_projection",
        )
        return None

    record = dict(projection)
    profile_row = (
        await session.execute(
            text(
                "SELECT p.id, p.status, p.approved_at, u.status AS account_status "
                "FROM dating_profiles p JOIN users u ON u.id = p.user_id WHERE p.user_id=:user_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    profile = profile_row.first()

    member_settings = await user_settings(session, user_id)
    criteria = await preference_criteria(session, user_id)

    reasons: list[str] = list(_jsonb(record.get("ineligible_reason_codes")) or [])
    eligible = bool(record["eligible"])
    if profile is None:
        eligible = False
        reasons.append("profile_not_found")
    else:
        if str(profile["account_status"]) != "active":
            eligible = False
            reasons.append("account_not_active")
        if str(profile["status"]) != "active":
            eligible = False
            reasons.append("profile_not_active")
    if member_settings["recommendations_paused"]:
        eligible = False
        reasons.append("recommendation_paused_by_user")
    age_years = record.get("age_years")
    if age_years is None:
        eligible = False
        reasons.append("age_unknown")
    elif int(age_years) < settings.dating_minimum_age:
        eligible = False
        reasons.append("below_minimum_age")

    payload = {
        "user_id": user_id,
        "dating_profile_id": record["dating_profile_id"],
        "profile_projection_version": record["projection_version"],
        "preference_version": record["preference_version"],
        "privacy_settings_version": record["privacy_settings_version"],
        "country_code": record.get("country_code"),
        "region_code": record.get("region_code"),
        "city_code": record.get("city_code"),
        "age_bucket": record.get("age_bucket"),
        "age_years": age_years,
        "gender_code": record.get("gender_code"),
        "genders": json_value(_jsonb(record.get("eligible_partner_gender_codes")) or []),
        "relationship_intent": record.get("relationship_intent"),
        "eligible": eligible,
        "reasons": json_value(sorted(set(reasons))),
        "criteria_count": len(criteria),
        "approved_at": profile["approved_at"] if profile is not None else None,
    }
    await session.execute(
        text(
            "INSERT INTO recommendation_pool_entries "
            "(user_id,dating_profile_id,profile_projection_version,preference_version,"
            "privacy_settings_version,country_code,region_code,city_code,age_bucket,age_years,"
            "gender_code,eligible_partner_gender_codes,relationship_intent,eligible,"
            "eligibility_reasons,stated_criteria_count,approved_at,updated_at) "
            "VALUES (:user_id,:dating_profile_id,:profile_projection_version,:preference_version,"
            ":privacy_settings_version,:country_code,:region_code,:city_code,:age_bucket,:age_years,"
            ":gender_code,CAST(:genders AS jsonb),:relationship_intent,:eligible,"
            "CAST(:reasons AS jsonb),:criteria_count,:approved_at,now()) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "dating_profile_id=EXCLUDED.dating_profile_id,"
            "profile_projection_version=EXCLUDED.profile_projection_version,"
            "preference_version=EXCLUDED.preference_version,"
            "privacy_settings_version=EXCLUDED.privacy_settings_version,"
            "country_code=EXCLUDED.country_code,region_code=EXCLUDED.region_code,"
            "city_code=EXCLUDED.city_code,age_bucket=EXCLUDED.age_bucket,age_years=EXCLUDED.age_years,"
            "gender_code=EXCLUDED.gender_code,"
            "eligible_partner_gender_codes=EXCLUDED.eligible_partner_gender_codes,"
            "relationship_intent=EXCLUDED.relationship_intent,eligible=EXCLUDED.eligible,"
            "eligibility_reasons=EXCLUDED.eligibility_reasons,"
            "stated_criteria_count=EXCLUDED.stated_criteria_count,approved_at=EXCLUDED.approved_at,"
            "pool_version=recommendation_pool_entries.pool_version + 1,updated_at=now()"
        ),
        payload,
    )
    await audit(
        session,
        "recommendation.pool.user_added" if eligible else "recommendation.pool.user_removed",
        "user",
        user_id,
        context={"eligible": eligible, "reason_codes": sorted(set(reasons))},
    )
    if not eligible:
        await invalidate_candidates(session, user_id, reason="pool_ineligible")
    return await pool_entry(session, user_id)


async def rebuild_pool(session: AsyncSession) -> int:
    rows = (
        await session.execute(text("SELECT user_id FROM dating_profile_recommendation_projections"))
    ).all()
    for (user_id,) in rows:
        await rebuild_pool_entry(session, user_id)
    return len(rows)


async def pool_entry(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_pool_entries WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        return None
    record = dict(found)
    record["eligibility_reasons"] = _jsonb(record.get("eligibility_reasons")) or []
    record["eligible_partner_gender_codes"] = (
        _jsonb(record.get("eligible_partner_gender_codes")) or []
    )
    return record


async def require_eligible_pool_entry(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    entry = await pool_entry(session, user_id)
    if entry is None or not entry["eligible"]:
        raise VavError(
            "RECOMMENDATION_NOT_ELIGIBLE",
            "This account is not currently part of the recommendation pool.",
            status_code=409,
            details=list(entry["eligibility_reasons"]) if entry else ["no_pool_entry"],
        )
    return entry


# --------------------------------------------------------------------------
# Preferences and projections
# --------------------------------------------------------------------------


async def preference_criteria(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """The member's own indexed criteria, never exposed to another member."""
    row = (
        await session.execute(
            text(
                "SELECT indexed_preference_criteria FROM dating_profile_recommendation_projections "
                "WHERE user_id=:user_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        return []
    return list(_jsonb(found["indexed_preference_criteria"]) or [])


async def projection_for(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT * FROM dating_profile_recommendation_projections WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        return None
    return dict(found)


# --------------------------------------------------------------------------
# Candidate generation
# --------------------------------------------------------------------------


async def invalidate_candidates(session: AsyncSession, user_id: UUID, *, reason: str) -> int:
    """Invalidate a member's pairs and every recommendation item not yet shown."""
    result = await session.execute(
        text(
            "UPDATE recommendation_candidate_pairs SET status='invalidated', invalidated_at=now(), "
            "invalidation_reason=:reason WHERE (user_low_id=:user_id OR user_high_id=:user_id) "
            "AND status <> 'invalidated'"
        ),
        {"user_id": user_id, "reason": reason[:128]},
    )
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated', invalidated_at=now(), "
            "invalidation_reason=:reason WHERE (viewer_user_id=:user_id OR recommended_user_id=:user_id) "
            "AND status IN ('ready','exposed')"
        ),
        {"user_id": user_id, "reason": reason[:128]},
    )
    await audit(
        session,
        "recommendation.candidate.invalidated",
        "user",
        user_id,
        reason=reason,
        context={"invalidated_pairs": int(getattr(result, "rowcount", 0) or 0)},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def generate_candidates(
    session: AsyncSession,
    user_id: UUID,
    *,
    strategy: dict[str, Any] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Generate canonical candidate pairs for one member.

    Stages run in order and each one is counted, so an operator can see where
    candidates were lost without ever learning who excluded whom.
    """
    enabled()
    settings = get_settings()
    active = strategy or await active_strategy(session)
    viewer_entry = await require_eligible_pool_entry(session, user_id)
    viewer_projection_row = await projection_for(session, user_id)
    if viewer_projection_row is None:
        raise VavError(
            "RECOMMENDATION_PROJECTION_MISSING",
            "The approved profile projection is not available.",
            status_code=409,
        )
    viewer_projection = projection_payload(viewer_projection_row)
    viewer_criteria = await preference_criteria(session, user_id)
    viewer_settings = await user_settings(session, user_id)
    max_candidates = limit or settings.recommendation_max_candidates_per_user

    recalled = await _recall(
        session,
        user_id=user_id,
        viewer_entry=viewer_entry,
        limit=max_candidates,
    )

    interaction_gateway = InteractionGateway(session)
    moderation_gateway = ModerationGateway(session)
    now = utcnow()
    excluded = await interaction_gateway.excluded_partners(user_id, now=now)

    report: dict[str, Any] = {
        "pool_size": await _eligible_pool_size(session),
        "recalled": len(recalled),
        "excluded_by_interaction": 0,
        "excluded_by_safety": 0,
        "hard_constraint_failed": 0,
        "below_minimum_score": 0,
        "eligible": 0,
        "hard_constraint_failures": {},
    }
    failure_evaluations: list[constraints.HardConstraintEvaluation] = []
    generated: list[dict[str, Any]] = []

    allow_viewer_relaxation = bool(
        settings.recommendation_allow_user_relaxation
        and viewer_settings.get("extended_recommendations_enabled")
    )
    minimum_directional = int(
        _jsonb(active["bidirectional_policy"]).get(
            "minimum_directional_score_bps", settings.recommendation_min_directional_score_bps
        )
    )
    minimum_bidirectional = int(
        _jsonb(active["bidirectional_policy"]).get(
            "minimum_bidirectional_score_bps", settings.recommendation_min_bidirectional_score_bps
        )
    )
    scoring_policy = _jsonb(active["scoring_policy"])
    viewer_tuning = await tuning_profile(session, user_id)

    for candidate in recalled:
        candidate_id: UUID = candidate["user_id"]
        if str(candidate_id) in excluded:
            report["excluded_by_interaction"] += 1
            continue

        decision = await moderation_gateway.evaluate_recommendation_pair(
            viewer_user_id=user_id, candidate_user_id=candidate_id
        )
        if not decision.allowed:
            report["excluded_by_safety"] += 1
            continue

        candidate_projection_row = await projection_for(session, candidate_id)
        if candidate_projection_row is None or not candidate_projection_row["eligible"]:
            report["excluded_by_interaction"] += 1
            continue
        candidate_projection = projection_payload(candidate_projection_row)
        candidate_criteria = list(
            _jsonb(candidate_projection_row["indexed_preference_criteria"]) or []
        )
        candidate_settings = await user_settings(session, candidate_id)

        evaluation = constraints.evaluate_pair(
            viewer_projection=viewer_projection,
            candidate_projection=candidate_projection,
            viewer_criteria=viewer_criteria,
            candidate_criteria=candidate_criteria,
            viewer_preference_version=int(viewer_projection_row["preference_version"]),
            candidate_preference_version=int(candidate_projection_row["preference_version"]),
            minimum_age=settings.dating_minimum_age,
            allow_viewer_relaxation=allow_viewer_relaxation,
            allow_candidate_relaxation=bool(
                settings.recommendation_allow_user_relaxation
                and candidate_settings.get("extended_recommendations_enabled")
            ),
            unknown_value_policy=settings.recommendation_unknown_value_policy,
        )
        if not evaluation.passed:
            report["hard_constraint_failed"] += 1
            failure_evaluations.append(evaluation)
            continue

        candidate_tuning = await tuning_profile(session, candidate_id)
        viewer_score = scoring_engine.score_direction(
            source_user_id=user_id,
            target_user_id=candidate_id,
            viewer_projection=viewer_projection,
            candidate_projection=candidate_projection,
            viewer_criteria=viewer_criteria,
            tuning_adjustments=(
                viewer_tuning["feature_weight_adjustments"]
                if viewer_tuning["feedback_personalization_enabled"]
                else None
            ),
            missingness_policy=str(scoring_policy.get("missingness_policy")),
            missing_penalty_bps=int(scoring_policy.get("missing_penalty_bps", 0)),
        )
        candidate_score = scoring_engine.score_direction(
            source_user_id=candidate_id,
            target_user_id=user_id,
            viewer_projection=candidate_projection,
            candidate_projection=viewer_projection,
            viewer_criteria=candidate_criteria,
            tuning_adjustments=(
                candidate_tuning["feature_weight_adjustments"]
                if candidate_tuning["feedback_personalization_enabled"]
                else None
            ),
            missingness_policy=str(scoring_policy.get("missingness_policy")),
            missing_penalty_bps=int(scoring_policy.get("missing_penalty_bps", 0)),
        )
        composed = bidirectional_engine.combine(
            viewer_score,
            candidate_score,
            minimum_directional_bps=minimum_directional,
            minimum_bidirectional_bps=minimum_bidirectional,
        )
        if not composed.meets_minimum_directional or not composed.meets_minimum_bidirectional:
            report["below_minimum_score"] += 1
            continue

        pair = await upsert_candidate_pair(
            session,
            viewer_user_id=user_id,
            candidate_user_id=candidate_id,
            strategy_id=active["id"],
            viewer_projection_row=viewer_projection_row,
            candidate_projection_row=candidate_projection_row,
            evaluation=evaluation,
            composed=composed,
        )
        await _store_directional_scores(
            session, pair_id=pair["id"], scores=(viewer_score, candidate_score)
        )
        report["eligible"] += 1
        generated.append(
            {
                "candidate_pair_id": pair["id"],
                "candidate_user_id": candidate_id,
                "bidirectional_score_bps": composed.combined_score_bps,
                "minimum_directional_score_bps": composed.minimum_directional_score_bps,
                "confidence_bps": composed.confidence_bps,
                "relaxed_codes": evaluation.relaxed_codes,
            }
        )

    report["hard_constraint_failures"] = constraints.aggregate_failure_reasons(failure_evaluations)
    await audit(
        session,
        "recommendation.candidates.generated",
        "user",
        user_id,
        context={key: value for key, value in report.items() if key != "hard_constraint_failures"},
    )
    return {"report": report, "candidates": generated}


async def _eligible_pool_size(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM recommendation_pool_entries WHERE eligible = true")
            )
        ).scalar_one()
        or 0
    )


async def _recall(
    session: AsyncSession,
    *,
    user_id: UUID,
    viewer_entry: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Coarse recall over normalised, automatically usable columns only.

    Mutual relationship eligibility and the platform's adult rule are applied in
    SQL so the application never loads the whole pool into memory.
    """
    accepted_genders = viewer_entry.get("eligible_partner_gender_codes") or []
    rows = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_pool_entries "
                "WHERE eligible = true AND user_id <> :user_id "
                "AND (:accepted_empty OR CAST(:accepted AS jsonb) @> to_jsonb(gender_code)) "
                "AND (eligible_partner_gender_codes @> CAST(:viewer_gender AS jsonb) OR :viewer_gender_null) "
                "AND age_years >= :minimum_age "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {
                "user_id": user_id,
                "accepted": json_value([str(code) for code in accepted_genders]),
                "accepted_empty": not accepted_genders,
                "viewer_gender": json_value([viewer_entry.get("gender_code")])
                if viewer_entry.get("gender_code")
                else "[]",
                "viewer_gender_null": viewer_entry.get("gender_code") is None,
                "minimum_age": get_settings().dating_minimum_age,
                "limit": limit,
            },
        )
    ).mappings()
    return [dict(row) for row in rows]


async def upsert_candidate_pair(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    candidate_user_id: UUID,
    strategy_id: UUID,
    viewer_projection_row: dict[str, Any],
    candidate_projection_row: dict[str, Any],
    evaluation: constraints.HardConstraintEvaluation,
    composed: bidirectional_engine.BidirectionalCompatibilityResult,
) -> dict[str, Any]:
    """Insert or refresh the single canonical pair record for two members."""
    low, high = canonical_pair(viewer_user_id, candidate_user_id)
    low_row = viewer_projection_row if low == viewer_user_id else candidate_projection_row
    high_row = candidate_projection_row if low == viewer_user_id else viewer_projection_row
    settings = get_settings()
    valid_until = utcnow() + timedelta(days=settings.recommendation_candidate_validity_days)

    params = {
        "low": low,
        "high": high,
        "low_projection": int(low_row["projection_version"]),
        "high_projection": int(high_row["projection_version"]),
        "low_preference": int(low_row["preference_version"]),
        "high_preference": int(high_row["preference_version"]),
        "strategy_id": strategy_id,
        "status": CandidatePairStatus.ELIGIBLE.value,
        "eligibility": json_value(
            {
                "generated_at": utcnow().isoformat(),
                "low_privacy_version": int(low_row["privacy_settings_version"]),
                "high_privacy_version": int(high_row["privacy_settings_version"]),
            }
        ),
        "hard": json_value(evaluation.as_dict()),
        "score": json_value(composed.as_dict()),
        "valid_until": valid_until,
    }
    row = (
        await session.execute(
            text(
                "INSERT INTO recommendation_candidate_pairs "
                "(user_low_id,user_high_id,low_profile_projection_version,high_profile_projection_version,"
                "low_preference_version,high_preference_version,strategy_id,status,eligibility_snapshot,"
                "hard_constraint_snapshot,score_snapshot,valid_until) "
                "VALUES (:low,:high,:low_projection,:high_projection,:low_preference,:high_preference,"
                ":strategy_id,:status,CAST(:eligibility AS jsonb),CAST(:hard AS jsonb),CAST(:score AS jsonb),:valid_until) "
                "ON CONFLICT (user_low_id,user_high_id,strategy_id,low_profile_projection_version,"
                "high_profile_projection_version,low_preference_version,high_preference_version) "
                "DO UPDATE SET status=EXCLUDED.status, hard_constraint_snapshot=EXCLUDED.hard_constraint_snapshot, "
                "score_snapshot=EXCLUDED.score_snapshot, valid_until=EXCLUDED.valid_until, "
                "invalidated_at=NULL, invalidation_reason=NULL RETURNING *"
            ),
            params,
        )
    ).mappings()
    pair = row.first()
    if pair is None:
        raise VavError(
            "RECOMMENDATION_PAIR_CONFLICT", "Candidate pair could not be stored.", status_code=409
        )
    return dict(pair)


async def _store_directional_scores(
    session: AsyncSession,
    *,
    pair_id: UUID,
    scores: tuple[scoring_engine.DirectionalCompatibilityScore, ...],
) -> None:
    for score in scores:
        await session.execute(
            text(
                "INSERT INTO recommendation_directional_scores "
                "(candidate_pair_id,source_user_id,target_user_id,total_score_bps,confidence_bps,"
                "unknown_feature_count,feature_scores,missing_information,satisfied_preferences,"
                "scoring_policy_version,feature_registry_version) "
                "VALUES (:pair_id,:source,:target,:total,:confidence,:unknown,CAST(:features AS jsonb),"
                "CAST(:missing AS jsonb),CAST(:satisfied AS jsonb),:policy,:registry) "
                "ON CONFLICT (candidate_pair_id,source_user_id,scoring_policy_version,feature_registry_version) "
                "DO UPDATE SET total_score_bps=EXCLUDED.total_score_bps, confidence_bps=EXCLUDED.confidence_bps, "
                "unknown_feature_count=EXCLUDED.unknown_feature_count, feature_scores=EXCLUDED.feature_scores, "
                "missing_information=EXCLUDED.missing_information, satisfied_preferences=EXCLUDED.satisfied_preferences"
            ),
            {
                "pair_id": pair_id,
                "source": score.source_user_id,
                "target": score.target_user_id,
                "total": score.total_score_bps,
                "confidence": score.confidence_bps,
                "unknown": score.unknown_feature_count,
                "features": json_value([item.as_dict() for item in score.feature_scores]),
                "missing": json_value(score.missing_information),
                "satisfied": json_value(score.satisfied_preferences),
                "policy": score.scoring_policy_version,
                "registry": score.feature_registry_version,
            },
        )


async def directional_score_row(
    session: AsyncSession, *, pair_id: UUID, source_user_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_directional_scores "
                "WHERE candidate_pair_id=:pair_id AND source_user_id=:source "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"pair_id": pair_id, "source": source_user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        return None
    record = dict(found)
    for key in ("feature_scores", "missing_information", "satisfied_preferences"):
        record[key] = _jsonb(record.get(key))
    return record


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------


async def candidate_diagnostics(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Aggregate diagnostics for one member; never names another member."""
    entry = await pool_entry(session, user_id)
    generation = (
        await generate_candidates(session, user_id) if entry and entry["eligible"] else None
    )
    report = generation["report"] if generation else {}
    interaction_count = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_feedback_events WHERE viewer_user_id=:user_id"
                ),
                {"user_id": user_id},
            )
        ).scalar_one()
        or 0
    )
    region_size = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_pool_entries WHERE eligible = true "
                    "AND region_code IS NOT DISTINCT FROM :region AND user_id <> :user_id"
                ),
                {"region": entry["region_code"] if entry else None, "user_id": user_id},
            )
        ).scalar_one()
        or 0
    )
    assessment = cold_start.assess(
        account_age_days=_days_since(entry.get("approved_at") if entry else None),
        profile_approved_days=_days_since(entry.get("approved_at") if entry else None),
        stated_criteria_count=int(entry["stated_criteria_count"]) if entry else 0,
        eligible_profiles_in_region=region_size,
        interaction_count=interaction_count,
        base_exploration_slots=get_settings().recommendation_exploration_slot_count,
    )
    return {
        "pool_entry": entry,
        "generation_report": report,
        "cold_start": assessment.as_dict(),
        "empty_result_report": cold_start.empty_result_report(
            pool_size=int(report.get("pool_size", 0)),
            recalled=int(report.get("recalled", 0)),
            hard_constraint_failures=dict(report.get("hard_constraint_failures", {})),
            safety_excluded=int(report.get("excluded_by_safety", 0)),
            cooldown_excluded=int(report.get("excluded_by_interaction", 0)),
        ),
    }


def _days_since(moment: datetime | None) -> int:
    if moment is None:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, (utcnow() - moment).days)
