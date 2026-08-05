"""Recommendation batches, exposure tracking and display-time rechecks.

A batch is an immutable, versioned snapshot: it binds the strategy, profile,
preference and privacy versions that produced it. Nothing is trusted at display
time — safety, privacy and profile status are rechecked before an item is
returned, however good the snapshot looked when it was frozen.
"""

# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_profiles.domain import DatingProfileViewContext
from vav.modules.matchmaking_profiles.service import viewer_projection
from vav.modules.recommendations import cold_start, explanations, ranking, service
from vav.modules.recommendations import exposure as exposure_rules
from vav.modules.recommendations import strategy as strategy_policies
from vav.modules.recommendations.bidirectional import BidirectionalCompatibilityResult
from vav.modules.recommendations.domain import (
    RecommendationBatchType,
    canonical_pair,
)
from vav.modules.recommendations.gateways import MembershipGateway, NotificationGateway
from vav.modules.recommendations.scoring import DirectionalCompatibilityScore, FeatureScore

#: Fields a recommendation card may ever contain.
#:
#: These are exactly the keys Batch 13's ``RECOMMENDATION_CARD`` projection
#: produces, minus anything that is not needed on a card. Anything outside this
#: allow-list fails closed rather than being quietly dropped.
VISIBLE_SNAPSHOT_KEYS: frozenset[str] = frozenset(
    {
        "profile_id",
        "profile_number",
        "display_name",
        "age_display",
        "city_display",
        "primary_photo",
        "faith_summary",
        "lifestyle_summary",
        "relationship_summary",
        "self_introduction",
        "visible_fields",
        "withheld_field_count",
        "view_context",
        "moderation_badges",
    }
)


def _period_key(batch_type: str, moment: datetime, sequence: int = 0) -> str:
    if batch_type == RecommendationBatchType.DAILY.value:
        return moment.date().isoformat()
    if batch_type == RecommendationBatchType.SUPPLEMENTAL.value:
        return f"{moment.date().isoformat()}#{sequence}"
    return moment.isoformat(timespec="seconds")


async def _next_batch_number(session: AsyncSession, user_id: UUID) -> int:
    current = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(batch_number),0) FROM recommendation_batches WHERE user_id=:user_id"
            ),
            {"user_id": user_id},
        )
    ).scalar_one()
    return int(current or 0) + 1


async def budget_row(session: AsyncSession, user_id: UUID, budget_date: date) -> dict[str, Any]:
    """Fetch or create today's budget row for a member."""
    settings = get_settings()
    member_settings = await service.user_settings(session, user_id)
    limit = member_settings.get("daily_received_limit")
    entitled_limit = await MembershipGateway(session).daily_received_limit(
        user_id, default_limit=settings.recommendation_max_daily_received
    )
    daily_limit = min(int(limit), entitled_limit) if limit is not None else entitled_limit
    await session.execute(
        text(
            "INSERT INTO recommendation_exposure_budgets "
            "(user_id,budget_date,daily_received_limit,daily_shown_limit) "
            "VALUES (:user_id,:budget_date,:received,:shown) "
            "ON CONFLICT (user_id,budget_date) DO NOTHING"
        ),
        {
            "user_id": user_id,
            "budget_date": budget_date,
            "received": daily_limit,
            "shown": settings.recommendation_max_daily_shown_per_profile,
        },
    )
    row = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_exposure_budgets WHERE user_id=:user_id AND budget_date=:budget_date"
            ),
            {"user_id": user_id, "budget_date": budget_date},
        )
    ).mappings()
    found = row.first()
    if found is None:  # pragma: no cover - the insert above guarantees a row
        raise VavError("RECOMMENDATION_BUDGET_MISSING", "Budget unavailable.", status_code=500)
    return dict(found)


async def _reserve_received_capacity(
    session: AsyncSession, *, user_id: UUID, budget_date: date, requested: int
) -> int:
    """Atomically reserve daily receive capacity.

    The conditional UPDATE means two concurrent workers can never push a member
    past the daily limit, and a refresh cannot buy extra capacity either.
    """
    if requested <= 0:
        return 0
    granted = (
        await session.execute(
            text(
                "WITH locked AS ("
                "  SELECT current_received_count AS before_count FROM recommendation_exposure_budgets"
                "  WHERE user_id=:user_id AND budget_date=:budget_date FOR UPDATE"
                "), updated AS ("
                "  UPDATE recommendation_exposure_budgets b SET"
                "    current_received_count = LEAST(b.daily_received_limit, b.current_received_count + :requested),"
                "    updated_at = now()"
                "  FROM locked WHERE b.user_id=:user_id AND b.budget_date=:budget_date"
                "  RETURNING b.current_received_count AS after_count, locked.before_count"
                ") SELECT after_count - before_count FROM updated"
            ),
            {"requested": requested, "user_id": user_id, "budget_date": budget_date},
        )
    ).scalar()
    return max(0, int(granted or 0))


async def _release_received_capacity(
    session: AsyncSession, *, user_id: UUID, budget_date: date, amount: int
) -> None:
    if amount <= 0:
        return
    await session.execute(
        text(
            "UPDATE recommendation_exposure_budgets SET "
            "current_received_count = GREATEST(current_received_count - :amount, 0), updated_at = now() "
            "WHERE user_id=:user_id AND budget_date=:budget_date"
        ),
        {"amount": amount, "user_id": user_id, "budget_date": budget_date},
    )


async def _shown_counts_today(session: AsyncSession, budget_date: date) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                "SELECT exposed_user_id, count(*) AS shown FROM recommendation_exposures "
                "WHERE exposed_at::date = :budget_date GROUP BY exposed_user_id"
            ),
            {"budget_date": budget_date},
        )
    ).mappings()
    return {str(row["exposed_user_id"]): int(row["shown"]) for row in rows}


async def _last_exposure_days(session: AsyncSession, viewer_id: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                "SELECT exposed_user_id, MAX(exposed_at) AS last_seen FROM recommendation_exposures "
                "WHERE viewer_user_id=:viewer GROUP BY exposed_user_id"
            ),
            {"viewer": viewer_id},
        )
    ).mappings()
    now = service.utcnow()
    result: dict[str, int] = {}
    for row in rows:
        last_seen = row["last_seen"]
        if last_seen is None:
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        result[str(row["exposed_user_id"])] = max(0, (now - last_seen).days)
    return result


async def _never_exposed(session: AsyncSession) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT p.user_id FROM recommendation_pool_entries p "
                "LEFT JOIN recommendation_profile_exposure_stats s ON s.user_id = p.user_id "
                "WHERE p.eligible = true AND (s.total_exposures IS NULL OR s.total_exposures = 0)"
            )
        )
    ).all()
    return {str(row[0]) for row in rows}


def _score_from_row(
    row: dict[str, Any], *, source: UUID, target: UUID
) -> DirectionalCompatibilityScore:
    features = [
        FeatureScore(
            feature_code=str(item["feature_code"]),
            raw_match_bps=int(item["raw_match_bps"]),
            importance_weight=int(item["importance_weight"]),
            weighted_score=int(item["weighted_score"]),
            confidence_bps=int(item["confidence_bps"]),
            explanation_code=item.get("explanation_code"),
            hard_constraint_satisfied=bool(item.get("hard_constraint_satisfied")),
            information_available=bool(item.get("information_available", True)),
            source=str(item.get("source", "member_preference")),
        )
        for item in (row.get("feature_scores") or [])
    ]
    return DirectionalCompatibilityScore(
        source_user_id=source,
        target_user_id=target,
        total_score_bps=int(row["total_score_bps"]),
        confidence_bps=int(row["confidence_bps"]),
        feature_scores=features,
        missing_information=list(row.get("missing_information") or []),
        unknown_feature_count=int(row["unknown_feature_count"]),
        scoring_policy_version=str(row["scoring_policy_version"]),
        feature_registry_version=str(row["feature_registry_version"]),
        satisfied_preferences=list(row.get("satisfied_preferences") or []),
    )


def _composed_from_snapshot(snapshot: dict[str, Any]) -> BidirectionalCompatibilityResult:
    return BidirectionalCompatibilityResult(
        user_a_to_b_score_bps=int(snapshot["user_a_to_b_score_bps"]),
        user_b_to_a_score_bps=int(snapshot["user_b_to_a_score_bps"]),
        combined_score_bps=int(snapshot["combined_score_bps"]),
        minimum_directional_score_bps=int(snapshot["minimum_directional_score_bps"]),
        balance_score_bps=int(snapshot["balance_score_bps"]),
        confidence_bps=int(snapshot["confidence_bps"]),
        asymmetric_features=list(snapshot.get("asymmetric_features") or []),
        mutual_strengths=list(snapshot.get("mutual_strengths") or []),
        mutual_unknowns=list(snapshot.get("mutual_unknowns") or []),
        meets_minimum_directional=bool(snapshot.get("meets_minimum_directional", True)),
        meets_minimum_bidirectional=bool(snapshot.get("meets_minimum_bidirectional", True)),
        policy_version=str(snapshot.get("policy_version", "1.0.0")),
    )


async def _visible_snapshot(
    session: AsyncSession, *, viewer_id: UUID, candidate_user_id: UUID
) -> dict[str, Any]:
    """Freeze the card the viewer is allowed to see, produced by Batch 13."""
    from vav.models.identity import User

    viewer = await session.get(User, viewer_id)
    profile_id = (
        await session.execute(
            text("SELECT id FROM dating_profiles WHERE user_id=:user_id"),
            {"user_id": candidate_user_id},
        )
    ).scalar()
    if profile_id is None:
        raise VavError(
            "RECOMMENDATION_PROFILE_UNAVAILABLE", "Profile unavailable.", status_code=409
        )
    projection = await viewer_projection(
        session,
        profile_id=profile_id,
        viewer=viewer,
        context=DatingProfileViewContext.RECOMMENDATION_CARD,
    )
    snapshot = {key: value for key, value in projection.items() if key in VISIBLE_SNAPSHOT_KEYS}
    snapshot["profile_id"] = str(profile_id)
    assert_snapshot_is_safe(snapshot)
    return snapshot


def assert_snapshot_is_safe(snapshot: dict[str, Any]) -> None:
    """Fail closed if a card snapshot ever carries a forbidden field."""
    unexpected = set(snapshot) - VISIBLE_SNAPSHOT_KEYS
    if unexpected:
        raise VavError(
            "RECOMMENDATION_SNAPSHOT_FIELD_NOT_ALLOWED",
            f"Recommendation cards cannot carry: {', '.join(sorted(unexpected))}.",
            status_code=500,
        )


# --------------------------------------------------------------------------
# Batch generation
# --------------------------------------------------------------------------


async def generate_batch(
    session: AsyncSession,
    user_id: UUID,
    *,
    batch_type: str = RecommendationBatchType.DAILY.value,
    requested_size: int | None = None,
    actor_id: UUID | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Generate, freeze and activate one recommendation batch."""
    service.enabled()
    settings = get_settings()
    now = service.utcnow()
    strategy = await service.active_strategy(session)
    entry = await service.require_eligible_pool_entry(session, user_id)
    member_settings = await service.user_settings(session, user_id)
    if member_settings["recommendations_paused"]:
        raise VavError(
            "RECOMMENDATION_PAUSED", "Recommendations are paused for this account.", status_code=409
        )

    sequence = 0
    if batch_type == RecommendationBatchType.SUPPLEMENTAL.value:
        if not settings.recommendation_supplemental_batch_enabled:
            raise VavError(
                "RECOMMENDATION_SUPPLEMENTAL_DISABLED",
                "Supplemental batches are disabled.",
                status_code=409,
            )
        sequence = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM recommendation_batches WHERE user_id=:user_id "
                        "AND batch_type='supplemental' AND created_at::date = :today"
                    ),
                    {"user_id": user_id, "today": now.date()},
                )
            ).scalar_one()
            or 0
        )
        await _require_current_batch_processed(session, user_id)

    period_key = _period_key(batch_type, now, sequence)
    idempotency_key = f"{batch_type}:{period_key}"
    existing = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_batches WHERE user_id=:user_id AND idempotency_key=:key"
            ),
            {"user_id": user_id, "key": idempotency_key},
        )
    ).mappings()
    found = existing.first()
    if found is not None:
        return dict(found)

    budget_date = now.date()
    budget = await budget_row(session, user_id, budget_date)
    size = requested_size or settings.recommendation_daily_batch_size
    decision = exposure_rules.can_receive(
        policy=strategy_policies.exposure_policy(settings),
        current_received_count=int(budget["current_received_count"]),
        requested=size,
    )
    if not decision.allowed:
        raise VavError(
            "RECOMMENDATION_DAILY_LIMIT_REACHED",
            "The daily recommendation limit has been reached.",
            status_code=429,
            details=[decision.reason_code],
        )
    size = min(size, decision.remaining_received)

    generation = await service.generate_candidates(session, user_id, strategy=strategy)
    candidates = generation["candidates"]
    report = dict(generation["report"])

    shown_today = await _shown_counts_today(session, budget_date)
    last_seen = await _last_exposure_days(session, user_id)
    never_exposed = await _never_exposed(session)
    exposure_policy = strategy_policies.exposure_policy(settings)

    already_recommended = {
        str(row[0])
        for row in (
            await session.execute(
                text(
                    "SELECT DISTINCT recommended_user_id FROM recommendation_items "
                    "WHERE viewer_user_id=:user_id AND status NOT IN ('invalidated','expired')"
                ),
                {"user_id": user_id},
            )
        ).all()
    }

    ranking_candidates: list[ranking.RankingCandidate] = []
    filtered = {"cooldown": 0, "popularity": 0, "already_recommended": 0}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_user_id"])
        if candidate_id in already_recommended:
            filtered["already_recommended"] += 1
            continue
        if exposure_rules.cooldown_active(
            policy=exposure_policy, days_since_last_exposure=last_seen.get(candidate_id)
        ):
            filtered["cooldown"] += 1
            continue
        if not exposure_rules.can_show_profile(
            policy=exposure_policy, shown_count_today=shown_today.get(candidate_id, 0)
        ).allowed:
            filtered["popularity"] += 1
            continue
        candidate_entry = await service.pool_entry(session, candidate["candidate_user_id"])
        projection = await service.projection_for(session, candidate["candidate_user_id"])
        payload = service.projection_payload(projection) if projection else {}
        ranking_candidates.append(
            ranking.RankingCandidate(
                candidate_pair_id=candidate["candidate_pair_id"],
                candidate_user_id=candidate["candidate_user_id"],
                base_score_bps=int(candidate["bidirectional_score_bps"]),
                minimum_directional_score_bps=int(candidate["minimum_directional_score_bps"]),
                confidence_bps=int(candidate["confidence_bps"]),
                profile_age_days=service._days_since(
                    candidate_entry.get("approved_at") if candidate_entry else None
                ),
                days_since_last_exposure=last_seen.get(candidate_id),
                shown_count_today=shown_today.get(candidate_id, 0),
                never_exposed=candidate_id in never_exposed,
                city_code=payload.get("city_code"),
                region_code=payload.get("region_code"),
                interest_codes=tuple(
                    code
                    for code in (payload.get("lifestyle_codes") or [])
                    if str(code).startswith("leisure_interest_codes:")
                ),
                lifestyle_codes=tuple(payload.get("lifestyle_codes") or []),
            )
        )

    report.update(filtered)
    tuning = await service.tuning_profile(session, user_id)
    region_size = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_pool_entries WHERE eligible = true "
                    "AND region_code IS NOT DISTINCT FROM :region AND user_id <> :user_id"
                ),
                {"region": entry.get("region_code"), "user_id": user_id},
            )
        ).scalar_one()
        or 0
    )
    assessment = cold_start.assess(
        account_age_days=service._days_since(entry.get("approved_at")),
        profile_approved_days=service._days_since(entry.get("approved_at")),
        stated_criteria_count=int(entry["stated_criteria_count"]),
        eligible_profiles_in_region=region_size,
        interaction_count=int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM recommendation_feedback_events WHERE viewer_user_id=:user_id"
                    ),
                    {"user_id": user_id},
                )
            ).scalar_one()
            or 0
        ),
        exploration_level=str(tuning["exploration_level"]),
        base_exploration_slots=settings.recommendation_exploration_slot_count,
    )

    batch_number = await _next_batch_number(session, user_id)
    seed = f"{user_id}:{batch_number}:{strategy['semantic_version']}:{period_key}"
    ranked = ranking.rank_candidates(
        ranking_candidates,
        seed=seed,
        limit=size,
        policy=ranking.RankingPolicy(exploration_slot_count=assessment.exploration_slots),
    )

    granted = await _reserve_received_capacity(
        session, user_id=user_id, budget_date=budget_date, requested=len(ranked)
    )
    if granted < len(ranked):
        ranked = ranked[:granted]

    expires_at = now + timedelta(days=settings.recommendation_batch_ttl_days)
    batch_row = (
        await session.execute(
            text(
                "INSERT INTO recommendation_batches "
                "(user_id,batch_number,batch_type,strategy_id,profile_projection_version,"
                "preference_version,privacy_settings_version,status,requested_size,ranking_seed,"
                "period_key,idempotency_key,generated_at,expires_at,generation_report) "
                "VALUES (:user_id,:batch_number,:batch_type,:strategy_id,:projection_version,"
                ":preference_version,:privacy_version,'building',:requested_size,:seed,:period_key,"
                ":idempotency_key,now(),:expires_at,CAST(:report AS jsonb)) "
                "ON CONFLICT (user_id,idempotency_key) DO NOTHING RETURNING *"
            ),
            {
                "user_id": user_id,
                "batch_number": batch_number,
                "batch_type": batch_type,
                "strategy_id": strategy["id"],
                "projection_version": entry["profile_projection_version"],
                "preference_version": entry["preference_version"],
                "privacy_version": entry["privacy_settings_version"],
                "requested_size": max(1, size),
                "seed": seed,
                "period_key": period_key,
                "idempotency_key": idempotency_key,
                "expires_at": expires_at,
                "report": service.json_value({**report, "cold_start": assessment.as_dict()}),
            },
        )
    ).mappings()
    batch = batch_row.first()
    if batch is None:
        await _release_received_capacity(
            session, user_id=user_id, budget_date=budget_date, amount=granted
        )
        duplicate = (
            await session.execute(
                text(
                    "SELECT * FROM recommendation_batches WHERE user_id=:user_id AND idempotency_key=:key"
                ),
                {"user_id": user_id, "key": idempotency_key},
            )
        ).mappings()
        existing_batch = duplicate.first()
        if existing_batch is None:  # pragma: no cover - conflict implies a row exists
            raise VavError(
                "RECOMMENDATION_BATCH_CONFLICT", "Batch could not be created.", status_code=409
            )
        return dict(existing_batch)

    batch_id = batch["id"]
    locale = str(member_settings.get("preferred_locale") or "zh-CN")
    created_items = 0
    for entry_rank in ranked:
        pair = (
            await session.execute(
                text(
                    "SELECT * FROM recommendation_candidate_pairs WHERE id=:id AND status <> 'invalidated'"
                ),
                {"id": entry_rank.candidate_pair_id},
            )
        ).mappings()
        pair_row = pair.first()
        if pair_row is None:
            continue
        snapshot = service._jsonb(pair_row["score_snapshot"]) or {}
        composed = _composed_from_snapshot(snapshot)
        viewer_score_row = await service.directional_score_row(
            session, pair_id=entry_rank.candidate_pair_id, source_user_id=user_id
        )
        if viewer_score_row is None:
            continue
        viewer_score = _score_from_row(
            viewer_score_row, source=user_id, target=entry_rank.candidate_user_id
        )
        hard_snapshot = service._jsonb(pair_row["hard_constraint_snapshot"]) or {}
        explanation = explanations.build_explanation(
            viewer_score=viewer_score,
            bidirectional=composed,
            locale=locale,
            relaxed_criteria=[
                code
                for code in (hard_snapshot.get("relaxed_codes") or [])
                if code.startswith("viewer_to_candidate")
            ],
        )
        visible = await _visible_snapshot(
            session, viewer_id=user_id, candidate_user_id=entry_rank.candidate_user_id
        )
        candidate_entry = await service.pool_entry(session, entry_rank.candidate_user_id)
        low, _high = canonical_pair(user_id, entry_rank.candidate_user_id)
        viewer_to_candidate = (
            composed.user_a_to_b_score_bps if low == user_id else composed.user_b_to_a_score_bps
        )
        candidate_to_viewer = (
            composed.user_b_to_a_score_bps if low == user_id else composed.user_a_to_b_score_bps
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_items "
                "(recommendation_batch_id,viewer_user_id,recommended_user_id,candidate_pair_id,"
                "candidate_projection_version,candidate_privacy_version,"
                "rank_position,viewer_to_candidate_score_bps,candidate_to_viewer_score_bps,"
                "bidirectional_score_bps,confidence_bps,explanation_snapshot,visible_profile_snapshot,"
                "available_from,expires_at) "
                "VALUES (:batch_id,:viewer,:recommended,:pair_id,:candidate_projection,:candidate_privacy,"
                ":rank,:viewer_score,:candidate_score,"
                ":bidirectional,:confidence,CAST(:explanation AS jsonb),CAST(:visible AS jsonb),now(),:expires_at)"
            ),
            {
                "batch_id": batch_id,
                "viewer": user_id,
                "recommended": entry_rank.candidate_user_id,
                "pair_id": entry_rank.candidate_pair_id,
                "candidate_projection": int(
                    candidate_entry["profile_projection_version"] if candidate_entry else 0
                ),
                "candidate_privacy": int(
                    candidate_entry["privacy_settings_version"] if candidate_entry else 0
                ),
                "rank": entry_rank.final_rank,
                "viewer_score": viewer_to_candidate,
                "candidate_score": candidate_to_viewer,
                "bidirectional": composed.combined_score_bps,
                "confidence": composed.confidence_bps,
                "explanation": service.json_value(explanation.as_dict()),
                "visible": service.json_value(visible),
                "expires_at": expires_at,
            },
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_rank_results "
                "(recommendation_batch_id,candidate_pair_id,base_score_bps,adjusted_score_bps,"
                "novelty_adjustment_bps,diversity_adjustment_bps,exposure_adjustment_bps,"
                "exploration_adjustment_bps,final_rank,adjustment_snapshot) "
                "VALUES (:batch_id,:pair_id,:base,:adjusted,:novelty,:diversity,:exposure,"
                ":exploration,:rank,CAST(:snapshot AS jsonb))"
            ),
            {
                "batch_id": batch_id,
                "pair_id": entry_rank.candidate_pair_id,
                "base": entry_rank.base_score_bps,
                "adjusted": entry_rank.adjusted_score_bps,
                "novelty": entry_rank.novelty_adjustment_bps,
                "diversity": entry_rank.diversity_adjustment_bps,
                "exposure": entry_rank.exposure_adjustment_bps,
                "exploration": entry_rank.exploration_adjustment_bps,
                "rank": entry_rank.final_rank,
                "snapshot": service.json_value(entry_rank.adjustment_snapshot),
            },
        )
        created_items += 1

    if created_items < granted:
        await _release_received_capacity(
            session, user_id=user_id, budget_date=budget_date, amount=granted - created_items
        )

    activated = (
        await session.execute(
            text(
                "UPDATE recommendation_batches SET status='active', generated_size=:size, "
                "activated_at=now() WHERE id=:id AND status='building' RETURNING *"
            ),
            {"size": created_items, "id": batch_id},
        )
    ).mappings()
    final = activated.first()
    if final is None:  # pragma: no cover - only reachable on concurrent cancellation
        raise VavError(
            "RECOMMENDATION_BATCH_CONFLICT", "Batch activation conflicted.", status_code=409
        )

    await service.audit(
        session,
        "recommendation.batch.activated",
        "recommendation_batch",
        batch_id,
        actor_id=actor_id,
        reason=reason,
        context={
            "batch_type": batch_type,
            "generated_size": created_items,
            "strategy_id": str(strategy["id"]),
        },
    )
    await NotificationGateway(session).queue_batch_ready(user_id, batch_id)
    return dict(final)


async def _require_current_batch_processed(session: AsyncSession, user_id: UUID) -> None:
    """A supplemental batch is only allowed once the current one is worked through."""
    pending = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_items i "
                    "JOIN recommendation_batches b ON b.id = i.recommendation_batch_id "
                    "WHERE i.viewer_user_id=:user_id AND b.status='active' AND i.status IN ('ready','exposed')"
                ),
                {"user_id": user_id},
            )
        ).scalar_one()
        or 0
    )
    if pending > 0:
        raise VavError(
            "RECOMMENDATION_BATCH_NOT_PROCESSED",
            "Work through the current recommendations before requesting more.",
            status_code=409,
        )


# --------------------------------------------------------------------------
# Reading a batch
# --------------------------------------------------------------------------


async def active_batch(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_batches WHERE user_id=:user_id AND status='active' "
                "ORDER BY batch_number DESC LIMIT 1"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    found = row.first()
    return dict(found) if found is not None else None


async def viewer_items(
    session: AsyncSession, *, viewer_id: UUID, batch_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Return a member's own recommendation items after a display-time recheck."""
    service.enabled()
    query = (
        "SELECT * FROM recommendation_items WHERE viewer_user_id=:viewer "
        "AND status IN ('ready','exposed','viewed') "
    )
    params: dict[str, Any] = {"viewer": viewer_id}
    if batch_id is not None:
        query += "AND recommendation_batch_id=:batch_id "
        params["batch_id"] = batch_id
    else:
        query += (
            "AND recommendation_batch_id IN (SELECT id FROM recommendation_batches "
            "WHERE user_id=:viewer AND status='active') "
        )
    query += "ORDER BY rank_position ASC"

    rows = (await session.execute(text(query), params)).mappings()
    visible: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item["expires_at"] is not None:
            expires = item["expires_at"]
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= service.utcnow():
                await _invalidate_item(session, item["id"], reason="expired", status="expired")
                continue
        if not await _still_displayable(session, viewer_id=viewer_id, item=item):
            continue
        item["explanation_snapshot"] = service._jsonb(item["explanation_snapshot"])
        item["visible_profile_snapshot"] = service._jsonb(item["visible_profile_snapshot"])
        visible.append(item)
    return visible


async def _still_displayable(
    session: AsyncSession, *, viewer_id: UUID, item: dict[str, Any]
) -> bool:
    """Recheck safety, privacy and profile status before showing a frozen item."""
    from vav.modules.recommendations.gateways import ModerationGateway

    candidate_id: UUID = item["recommended_user_id"]
    decision = await ModerationGateway(session).evaluate_recommendation_pair(
        viewer_user_id=viewer_id, candidate_user_id=candidate_id
    )
    if not decision.allowed:
        await _invalidate_item(session, item["id"], reason=decision.reason_code or "safety")
        return False

    entry = await service.pool_entry(session, candidate_id)
    if entry is None or not entry["eligible"]:
        await _invalidate_item(session, item["id"], reason="candidate_not_eligible")
        return False

    exclusions = await _pair_exclusion_types(session, viewer_id, candidate_id)
    if exclusions:
        await _invalidate_item(session, item["id"], reason=sorted(exclusions)[0])
        return False

    batch = (
        await session.execute(
            text(
                "SELECT privacy_settings_version, status FROM recommendation_batches WHERE id=:id"
            ),
            {"id": item["recommendation_batch_id"]},
        )
    ).mappings()
    batch_row = batch.first()
    if batch_row is None or str(batch_row["status"]) not in {"active", "exhausted"}:
        return False

    frozen_privacy = int(item.get("candidate_privacy_version") or 0)
    frozen_projection = int(item.get("candidate_projection_version") or 0)
    if frozen_privacy and frozen_privacy != int(entry["privacy_settings_version"]):
        await _invalidate_item(session, item["id"], reason="privacy_changed")
        return False
    if frozen_projection and frozen_projection != int(entry["profile_projection_version"]):
        await _invalidate_item(session, item["id"], reason="profile_updated")
        return False
    return True


async def _pair_exclusion_types(
    session: AsyncSession, viewer_id: UUID, candidate_id: UUID
) -> set[str]:
    low, high = canonical_pair(viewer_id, candidate_id)
    rows = (
        await session.execute(
            text(
                "SELECT exclusion_type FROM recommendation_pair_exclusions "
                "WHERE user_low_id=:low AND user_high_id=:high AND released_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > now())"
            ),
            {"low": low, "high": high},
        )
    ).all()
    return {str(row[0]) for row in rows}


async def _invalidate_item(
    session: AsyncSession, item_id: UUID, *, reason: str, status: str = "invalidated"
) -> None:
    await session.execute(
        text(
            "UPDATE recommendation_items SET status=:status, invalidated_at=now(), "
            "invalidation_reason=:reason WHERE id=:id AND status IN ('ready','exposed','viewed')"
        ),
        {"id": item_id, "reason": reason[:128], "status": status},
    )
    await service.audit(
        session,
        "recommendation.item.invalidated",
        "recommendation_item",
        item_id,
        reason=reason,
    )


async def invalidate_batch(
    session: AsyncSession, batch_id: UUID, *, reason: str, actor_id: UUID | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE recommendation_batches SET status='cancelled' WHERE id=:id "
            "AND status IN ('building','validating','ready','active','exhausted')"
        ),
        {"id": batch_id},
    )
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated', invalidated_at=now(), "
            "invalidation_reason=:reason WHERE recommendation_batch_id=:id "
            "AND status IN ('ready','exposed','viewed')"
        ),
        {"id": batch_id, "reason": reason[:128]},
    )
    await service.audit(
        session,
        "recommendation.batch.invalidated",
        "recommendation_batch",
        batch_id,
        actor_id=actor_id,
        reason=reason,
    )


async def expire_batches(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            "UPDATE recommendation_batches SET status='expired' "
            "WHERE status IN ('ready','active','exhausted') AND expires_at IS NOT NULL AND expires_at <= now()"
        )
    )
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='expired' WHERE status IN ('ready','exposed','viewed') "
            "AND expires_at IS NOT NULL AND expires_at <= now()"
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


# --------------------------------------------------------------------------
# Exposure
# --------------------------------------------------------------------------


async def record_exposure(
    session: AsyncSession,
    *,
    viewer_id: UUID,
    item_id: UUID,
    exposure_type: str,
    duration_ms: int | None = None,
    source: str = "recommendation_list",
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Record one exposure event, idempotently.

    A rendered card is not a seen card: only events that meet the visible
    threshold update the profile's exposure statistics.
    """
    service.enabled()
    settings = get_settings()
    moment = occurred_at or service.utcnow()
    item = (
        await session.execute(
            text("SELECT * FROM recommendation_items WHERE id=:id AND viewer_user_id=:viewer"),
            {"id": item_id, "viewer": viewer_id},
        )
    ).mappings()
    row = item.first()
    if row is None:
        raise VavError(
            "RECOMMENDATION_ITEM_NOT_FOUND", "Recommendation not found.", status_code=404
        )
    if str(row["status"]) in {"invalidated", "expired"}:
        raise VavError(
            "RECOMMENDATION_ITEM_UNAVAILABLE",
            "This recommendation is no longer available.",
            status_code=409,
        )

    policy = strategy_policies.exposure_policy(settings)
    counted = exposure_rules.counts_as_visible(
        exposure_type=exposure_type, duration_ms=duration_ms, policy=policy
    )
    key = exposure_rules.idempotency_key(
        viewer_user_id=viewer_id,
        recommendation_item_id=item_id,
        exposure_type=exposure_type,
        occurred_at=moment,
    )
    sequence = (
        int(
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(exposure_sequence),0) FROM recommendation_exposures "
                        "WHERE viewer_user_id=:viewer AND recommendation_item_id=:item"
                    ),
                    {"viewer": viewer_id, "item": item_id},
                )
            ).scalar_one()
            or 0
        )
        + 1
    )

    inserted = (
        await session.execute(
            text(
                "INSERT INTO recommendation_exposures "
                "(recommendation_item_id,viewer_user_id,exposed_user_id,exposure_type,"
                "exposure_sequence,source,counted_as_visible,exposed_at,duration_ms,idempotency_key) "
                "VALUES (:item,:viewer,:exposed,:type,:sequence,:source,:counted,:moment,:duration,:key) "
                "ON CONFLICT (viewer_user_id,idempotency_key) DO NOTHING RETURNING *"
            ),
            {
                "item": item_id,
                "viewer": viewer_id,
                "exposed": row["recommended_user_id"],
                "type": exposure_type,
                "sequence": sequence,
                "source": source,
                "counted": counted,
                "moment": moment,
                "duration": duration_ms,
                "key": key,
            },
        )
    ).mappings()
    created = inserted.first()
    if created is None:
        return {"recorded": False, "reason_code": "duplicate_event"}

    if counted:
        await session.execute(
            text(
                "INSERT INTO recommendation_profile_exposure_stats "
                "(user_id,total_exposures,distinct_viewers,first_exposed_at,last_exposed_at) "
                "VALUES (:user_id,1,1,:moment,:moment) "
                "ON CONFLICT (user_id) DO UPDATE SET total_exposures = recommendation_profile_exposure_stats.total_exposures + 1, "
                "last_exposed_at = EXCLUDED.last_exposed_at, updated_at = now()"
            ),
            {"user_id": row["recommended_user_id"], "moment": moment},
        )
        await session.execute(
            text(
                "UPDATE recommendation_exposure_budgets SET current_shown_count = current_shown_count + 1, "
                "updated_at = now() WHERE user_id=:user_id AND budget_date=:budget_date"
            ),
            {"user_id": row["recommended_user_id"], "budget_date": moment.date()},
        )

    if exposure_type in {"profile_opened", "photo_viewed"}:
        await session.execute(
            text(
                "UPDATE recommendation_items SET status='viewed', viewed_at=COALESCE(viewed_at, now()), "
                "exposed_at=COALESCE(exposed_at, now()) WHERE id=:id AND status IN ('ready','exposed')"
            ),
            {"id": item_id},
        )
        await service.audit(session, "recommendation.item.viewed", "recommendation_item", item_id)
    elif counted:
        await session.execute(
            text(
                "UPDATE recommendation_items SET status='exposed', exposed_at=COALESCE(exposed_at, now()) "
                "WHERE id=:id AND status='ready'"
            ),
            {"id": item_id},
        )
        await service.audit(session, "recommendation.item.exposed", "recommendation_item", item_id)

    return {"recorded": True, "counted_as_visible": counted, "exposure_sequence": sequence}


async def exposure_overview(session: AsyncSession) -> dict[str, Any]:
    """Aggregate exposure health used by the operations dashboard."""
    eligible = int(
        (
            await session.execute(
                text("SELECT count(*) FROM recommendation_pool_entries WHERE eligible = true")
            )
        ).scalar_one()
        or 0
    )
    exposed = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_profile_exposure_stats WHERE total_exposures > 0"
                )
            )
        ).scalar_one()
        or 0
    )
    counts = [
        int(row[0])
        for row in (
            await session.execute(
                text("SELECT total_exposures FROM recommendation_profile_exposure_stats")
            )
        ).all()
    ]
    from vav.modules.recommendations.evaluation import gini_bps

    return {
        "eligible_profiles": eligible,
        "exposed_profiles": exposed,
        "coverage_ratio_bps": exposure_rules.exposure_coverage_ratio(
            exposed_profiles=exposed, eligible_profiles=eligible
        ),
        "exposure_gini_bps": gini_bps(counts),
        "never_exposed_profiles": max(0, eligible - exposed),
    }
