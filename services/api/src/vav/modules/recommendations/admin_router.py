"""Recommendation operations centre.

Operators supervise the engine: strategies, batches, diagnostics, exposure,
fairness, evaluations and experiments. They cannot push two specific members
together, edit a score, bypass a hard constraint or read a member's private
preference list — those actions simply do not exist here.
"""

# ruff: noqa: B008, E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.recommendations import batches, service
from vav.modules.recommendations import experiments as experiment_service
from vav.modules.recommendations import feedback as feedback_service
from vav.modules.recommendations.domain import (
    SUPPORTED_HARD_CONSTRAINTS,
    RecommendationStrategyStatus,
    canonical_pair,
)
from vav.modules.recommendations.features import feature_manifest
from vav.modules.recommendations.schemas import (
    BatchInvalidateRequest,
    BatchRebuildRequest,
    EvaluationRunRequest,
    ExperimentCreateRequest,
    ExperimentGuardrailRequest,
    ExperimentTransitionRequest,
    StrategyCreateRequest,
    StrategyTransitionRequest,
)

router = APIRouter(prefix="/admin/recommendations")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.analytics.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    pool = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE eligible) AS eligible, count(*) AS total "
                    "FROM recommendation_pool_entries"
                )
            )
        )
        .mappings()
        .one()
    )
    pairs = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status='eligible') AS eligible, count(*) AS total "
                    "FROM recommendation_candidate_pairs"
                )
            )
        )
        .mappings()
        .one()
    )
    batch_stats = (
        (
            await session.execute(
                text(
                    "SELECT count(*) AS total, count(*) FILTER (WHERE status='active') AS active, "
                    "count(*) FILTER (WHERE status='failed') AS failed, "
                    "COALESCE(AVG(generated_size),0) AS average_size, "
                    "count(*) FILTER (WHERE generated_size = 0) AS empty_batches "
                    "FROM recommendation_batches"
                )
            )
        )
        .mappings()
        .one()
    )
    exposure = await batches.exposure_overview(session)
    feedback_stats = await feedback_service.feedback_summary(session)
    cold_start_users = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_pool_entries WHERE eligible = true "
                    "AND stated_criteria_count < 3"
                )
            )
        ).scalar_one()
        or 0
    )
    return success(
        {
            "pool": {"eligible": int(pool["eligible"] or 0), "total": int(pool["total"] or 0)},
            "candidate_pairs": {
                "eligible": int(pairs["eligible"] or 0),
                "total": int(pairs["total"] or 0),
            },
            "batches": {
                "total": int(batch_stats["total"] or 0),
                "active": int(batch_stats["active"] or 0),
                "failed": int(batch_stats["failed"] or 0),
                "average_size": float(batch_stats["average_size"] or 0),
                "empty_batches": int(batch_stats["empty_batches"] or 0),
            },
            "exposure": exposure,
            "feedback": feedback_stats,
            "cold_start_users": cold_start_users,
        },
        request_id_from_request(request),
    )


# --------------------------------------------------------------------------
# Strategies, features and constraints
# --------------------------------------------------------------------------


@router.get("/strategies")
async def list_strategies(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id, strategy_code, semantic_version, status, created_at, approved_at, activated_at "
                "FROM recommendation_strategies ORDER BY created_at DESC LIMIT 100"
            )
        )
    ).mappings()
    return success({"strategies": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/strategies/{strategy_id}")
async def get_strategy(
    request: Request,
    strategy_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    strategy = await service.strategy_by_id(session, strategy_id)
    evaluation = (
        await session.execute(
            text(
                "SELECT id, status, metrics, blocking_failures, guardrail_failures, completed_at "
                "FROM recommendation_evaluation_runs WHERE strategy_id=:id ORDER BY started_at DESC LIMIT 5"
            ),
            {"id": strategy_id},
        )
    ).mappings()
    return success(
        {"strategy": strategy, "evaluations": [dict(row) for row in evaluation]},
        request_id_from_request(request),
    )


@router.post("/strategies")
async def create_strategy(
    request: Request,
    payload: StrategyCreateRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    created = await service.create_strategy(
        session, payload=payload.model_dump(), actor_id=principal.user.id
    )
    await session.commit()
    return success({"strategy_id": str(created["id"])}, request_id_from_request(request))


@router.post("/strategies/{strategy_id}/approve")
async def approve_strategy(
    request: Request,
    strategy_id: UUID,
    payload: StrategyTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await service.transition_strategy(
        session,
        strategy_id=strategy_id,
        target_status=RecommendationStrategyStatus.APPROVED.value,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": updated["status"]}, request_id_from_request(request))


@router.post("/strategies/{strategy_id}/activate")
async def activate_strategy(
    request: Request,
    strategy_id: UUID,
    payload: StrategyTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.activate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await service.transition_strategy(
        session,
        strategy_id=strategy_id,
        target_status=RecommendationStrategyStatus.ACTIVE.value,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": updated["status"]}, request_id_from_request(request))


@router.post("/strategies/{strategy_id}/rollback")
async def rollback_strategy(
    request: Request,
    strategy_id: UUID,
    payload: StrategyTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.rollback")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Roll the active strategy back and re-activate the previous version."""
    if not payload.reason:
        raise VavError(
            "RECOMMENDATION_ROLLBACK_REASON_REQUIRED",
            "A rollback requires a reason.",
            status_code=422,
        )
    current = await service.strategy_by_id(session, strategy_id)
    previous = (
        await session.execute(
            text(
                "SELECT id FROM recommendation_strategies WHERE strategy_code=:code "
                "AND status='superseded' ORDER BY activated_at DESC NULLS LAST LIMIT 1"
            ),
            {"code": current["strategy_code"]},
        )
    ).scalar()
    updated = await service.transition_strategy(
        session,
        strategy_id=strategy_id,
        target_status=RecommendationStrategyStatus.ROLLED_BACK.value,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    restored: str | None = None
    if previous is not None:
        await session.execute(
            text(
                "UPDATE recommendation_strategies SET status='active', activated_at=now() WHERE id=:id"
            ),
            {"id": previous},
        )
        restored = str(previous)
    await session.commit()
    return success(
        {"status": updated["status"], "restored_strategy_id": restored},
        request_id_from_request(request),
    )


@router.get("/features")
async def list_features(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.features.read")
    ),
) -> dict[str, Any]:
    return success({"features": feature_manifest()}, request_id_from_request(request))


@router.get("/constraints")
async def list_constraints(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.constraints.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    strategy = await service.active_strategy(session)
    return success(
        {
            "supported_criteria": list(SUPPORTED_HARD_CONSTRAINTS),
            "policy": service._jsonb(strategy["hard_constraint_policy"]),
        },
        request_id_from_request(request),
    )


# --------------------------------------------------------------------------
# Batches and diagnostics
# --------------------------------------------------------------------------


@router.get("/batches")
async def list_batches(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.batches.read")),
    session: AsyncSession = Depends(get_database_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id, user_id, batch_number, batch_type, status, generated_size, requested_size, "
                "created_at, activated_at, expires_at FROM recommendation_batches "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).mappings()
    return success({"batches": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/batches/{batch_id}")
async def get_batch(
    request: Request,
    batch_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.batches.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_batches WHERE id=:id"), {"id": batch_id}
        )
    ).mappings()
    batch = row.first()
    if batch is None:
        raise VavError("RECOMMENDATION_BATCH_NOT_FOUND", "Batch not found.", status_code=404)
    ranks = (
        await session.execute(
            text(
                "SELECT candidate_pair_id, base_score_bps, adjusted_score_bps, novelty_adjustment_bps, "
                "diversity_adjustment_bps, exposure_adjustment_bps, exploration_adjustment_bps, final_rank "
                "FROM recommendation_rank_results WHERE recommendation_batch_id=:id ORDER BY final_rank"
            ),
            {"id": batch_id},
        )
    ).mappings()
    return success(
        {
            "batch": dict(batch),
            "rank_results": [dict(rank) for rank in ranks],
        },
        request_id_from_request(request),
    )


@router.post("/batches/{batch_id}/invalidate")
async def invalidate_batch(
    request: Request,
    batch_id: UUID,
    payload: BatchInvalidateRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.batches.invalidate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await batches.invalidate_batch(
        session, batch_id, reason=payload.reason, actor_id=principal.user.id
    )
    await session.commit()
    return success({"invalidated": True}, request_id_from_request(request))


@router.post("/users/{user_id}/rebuild")
async def rebuild_user(
    request: Request,
    user_id: UUID,
    payload: BatchRebuildRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.batches.rebuild")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Rebuild one member's pool entry and recommendation batch.

    A rebuild re-runs the same pipeline for that member; it cannot inject a
    chosen candidate or alter a score.
    """
    await service.rebuild_pool_entry(session, user_id)
    await service.invalidate_candidates(session, user_id, reason=f"manual_rebuild:{payload.reason}")
    batch = await batches.generate_batch(
        session,
        user_id,
        batch_type=payload.batch_type,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"batch_id": str(batch["id"]), "generated_size": batch["generated_size"]},
        request_id_from_request(request),
    )


@router.get("/users/{user_id}/diagnostics")
async def user_diagnostics(
    request: Request,
    user_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.diagnostics.run")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Aggregate funnel diagnostics for one member.

    Counts and criterion codes only: no candidate identities and no private
    preference values.
    """
    diagnostics = await service.candidate_diagnostics(session, user_id)
    await session.commit()
    return success(diagnostics, request_id_from_request(request))


@router.get("/pairs/{pair_id}")
async def pair_diagnostics(
    request: Request,
    pair_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.candidates.sensitive.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Feature-code level diagnostics for one candidate pair.

    Requires the separate sensitive permission and still returns only codes,
    results and versions — never the underlying profile values.
    """
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_candidate_pairs WHERE id=:id"), {"id": pair_id}
        )
    ).mappings()
    pair = row.first()
    if pair is None:
        raise VavError(
            "RECOMMENDATION_PAIR_NOT_FOUND", "Candidate pair not found.", status_code=404
        )
    scores = (
        await session.execute(
            text(
                "SELECT source_user_id, total_score_bps, confidence_bps, unknown_feature_count, "
                "feature_scores, missing_information, scoring_policy_version, feature_registry_version "
                "FROM recommendation_directional_scores WHERE candidate_pair_id=:id"
            ),
            {"id": pair_id},
        )
    ).mappings()
    hard = service._jsonb(pair["hard_constraint_snapshot"]) or {}
    directional = []
    for score in scores:
        record = dict(score)
        record["feature_scores"] = [
            {
                "feature_code": item["feature_code"],
                "raw_match_bps": item["raw_match_bps"],
                "importance_weight": item["importance_weight"],
                "information_available": item["information_available"],
            }
            for item in (service._jsonb(record["feature_scores"]) or [])
        ]
        record["missing_information"] = service._jsonb(record["missing_information"])
        directional.append(record)
    await service.audit(
        session,
        "recommendation.score.generated",
        "recommendation_candidate_pair",
        pair_id,
        actor_id=principal.user.id,
        reason="sensitive_pair_diagnostics_read",
    )
    await session.commit()
    return success(
        {
            "pair": {
                "id": str(pair["id"]),
                "status": pair["status"],
                "strategy_id": str(pair["strategy_id"]),
                "low_profile_projection_version": pair["low_profile_projection_version"],
                "high_profile_projection_version": pair["high_profile_projection_version"],
                "low_preference_version": pair["low_preference_version"],
                "high_preference_version": pair["high_preference_version"],
                "valid_until": pair["valid_until"],
                "invalidation_reason": pair["invalidation_reason"],
            },
            "hard_constraints": {
                "passed": hard.get("passed"),
                "blocking_codes": hard.get("blocking_codes", []),
                "unknown_codes": hard.get("unknown_codes", []),
                "relaxed_codes": hard.get("relaxed_codes", []),
                "policy_version": hard.get("policy_version"),
            },
            "directional_scores": directional,
            "score_snapshot": service._jsonb(pair["score_snapshot"]),
        },
        request_id_from_request(request),
    )


@router.get("/exposures")
async def exposures(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.exposures.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    overview = await batches.exposure_overview(session)
    top = (
        await session.execute(
            text(
                "SELECT total_exposures, last_exposed_at FROM recommendation_profile_exposure_stats "
                "ORDER BY total_exposures DESC LIMIT 10"
            )
        )
    ).mappings()
    return success(
        {
            "overview": overview,
            "most_exposed_profiles": [
                {
                    "total_exposures": int(row["total_exposures"]),
                    "last_exposed_at": row["last_exposed_at"],
                }
                for row in top
            ],
        },
        request_id_from_request(request),
    )


@router.get("/cold-start")
async def cold_start_dashboard(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.analytics.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE stated_criteria_count < 3) AS sparse_preferences, "
                    "count(*) FILTER (WHERE approved_at > now() - interval '14 days') AS new_profiles, "
                    "count(*) AS eligible FROM recommendation_pool_entries WHERE eligible = true"
                )
            )
        )
        .mappings()
        .one()
    )
    never_exposed = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM recommendation_pool_entries p "
                    "LEFT JOIN recommendation_profile_exposure_stats s ON s.user_id = p.user_id "
                    "WHERE p.eligible = true AND COALESCE(s.total_exposures,0) = 0"
                )
            )
        ).scalar_one()
        or 0
    )
    return success(
        {
            "eligible_profiles": int(rows["eligible"] or 0),
            "sparse_preference_members": int(rows["sparse_preferences"] or 0),
            "new_profiles": int(rows["new_profiles"] or 0),
            "never_exposed_profiles": never_exposed,
        },
        request_id_from_request(request),
    )


@router.get("/feedback")
async def feedback_dashboard(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.feedback.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Aggregate feedback only. Free-text reasons stay encrypted and private."""
    return success(
        await feedback_service.feedback_summary(session), request_id_from_request(request)
    )


# --------------------------------------------------------------------------
# Evaluations and experiments
# --------------------------------------------------------------------------


@router.get("/evaluations")
async def list_evaluations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.evaluations.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT r.id, r.strategy_id, r.status, r.metrics, r.blocking_failures, "
                "r.guardrail_failures, r.started_at, r.completed_at, d.dataset_code "
                "FROM recommendation_evaluation_runs r "
                "JOIN recommendation_evaluation_datasets d ON d.id = r.dataset_id "
                "ORDER BY r.started_at DESC LIMIT 50"
            )
        )
    ).mappings()
    return success({"runs": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/evaluations")
async def run_evaluation(
    request: Request,
    payload: EvaluationRunRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.evaluations.run")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await experiment_service.run_evaluation(
        session,
        dataset_code=payload.dataset_code,
        strategy_id=payload.strategy_id,
        metrics=payload.metrics,
        guardrail_thresholds=payload.guardrail_thresholds,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(result["result"], request_id_from_request(request))


@router.get("/experiments")
async def list_experiments(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id, experiment_code, name, status, control_strategy_id, treatment_strategy_ids, "
                "starts_at, ends_at, stop_reason FROM recommendation_experiments ORDER BY created_at DESC LIMIT 50"
            )
        )
    ).mappings()
    return success({"experiments": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/experiments")
async def create_experiment(
    request: Request,
    payload: ExperimentCreateRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    created = await experiment_service.create_experiment(
        session,
        payload={
            **payload.model_dump(),
            "treatment_strategy_ids": [str(item) for item in payload.treatment_strategy_ids],
            "control_strategy_id": payload.control_strategy_id,
        },
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"experiment_id": str(created["id"])}, request_id_from_request(request))


@router.post("/experiments/{experiment_id}/approve")
async def approve_experiment(
    request: Request,
    experiment_id: UUID,
    payload: ExperimentTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await experiment_service.transition_experiment(
        session,
        experiment_id=experiment_id,
        target_status="approved",
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": updated["status"]}, request_id_from_request(request))


@router.post("/experiments/{experiment_id}/start")
async def start_experiment(
    request: Request,
    experiment_id: UUID,
    payload: ExperimentTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.start")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await experiment_service.transition_experiment(
        session,
        experiment_id=experiment_id,
        target_status="running",
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": updated["status"]}, request_id_from_request(request))


@router.post("/experiments/{experiment_id}/stop")
async def stop_experiment(
    request: Request,
    experiment_id: UUID,
    payload: ExperimentTransitionRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.stop")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await experiment_service.transition_experiment(
        session,
        experiment_id=experiment_id,
        target_status="stopped",
        actor_id=principal.user.id,
        reason=payload.reason or "manual_stop",
    )
    await session.commit()
    return success({"status": updated["status"]}, request_id_from_request(request))


@router.post("/experiments/{experiment_id}/guardrails")
async def evaluate_guardrails(
    request: Request,
    experiment_id: UUID,
    payload: ExperimentGuardrailRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.stop")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await experiment_service.check_guardrails(
        session,
        experiment_id=experiment_id,
        metrics=payload.metrics,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(result, request_id_from_request(request))


@router.get("/incidents")
async def incidents(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.incidents.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT event_type, subject_type, subject_id, reason, safe_context, created_at "
                "FROM recommendation_audit_events WHERE event_type IN "
                "('recommendation.release.blocked','recommendation.experiment.stopped',"
                "'recommendation.batch.invalidated','recommendation.hard_constraint.failed') "
                "ORDER BY created_at DESC LIMIT 100"
            )
        )
    ).mappings()
    return success({"incidents": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/audit")
async def audit_log(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.audit.read")),
    session: AsyncSession = Depends(get_database_session),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT event_type, actor_id, subject_type, subject_id, reason, safe_context, created_at "
                "FROM recommendation_audit_events ORDER BY created_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).mappings()
    return success({"events": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/candidates")
async def candidate_overview(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.candidates.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Aggregate candidate statistics; no member identities are listed."""
    rows = (
        await session.execute(
            text(
                "SELECT status, count(*) AS total FROM recommendation_candidate_pairs GROUP BY status"
            )
        )
    ).mappings()
    exclusions = (
        await session.execute(
            text(
                "SELECT exclusion_type, count(*) AS total FROM recommendation_pair_exclusions "
                "WHERE released_at IS NULL GROUP BY exclusion_type"
            )
        )
    ).mappings()
    return success(
        {
            "pairs_by_status": {str(row["status"]): int(row["total"]) for row in rows},
            "active_exclusions": {
                str(row["exclusion_type"]): int(row["total"]) for row in exclusions
            },
        },
        request_id_from_request(request),
    )


@router.post("/pair-exclusions/{low_id}/{high_id}/release")
async def release_exclusion(
    request: Request,
    low_id: UUID,
    high_id: UUID,
    payload: BatchInvalidateRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.exposures.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Release a cooldown exclusion. Safety blocks are never released here."""
    low, high = canonical_pair(low_id, high_id)
    result = await session.execute(
        text(
            "UPDATE recommendation_pair_exclusions SET released_at=now() "
            "WHERE user_low_id=:low AND user_high_id=:high AND released_at IS NULL "
            "AND exclusion_type = 'skip_cooldown'"
        ),
        {"low": low, "high": high},
    )
    await service.audit(
        session,
        "recommendation.candidate.invalidated",
        "recommendation_pair_exclusion",
        None,
        actor_id=principal.user.id,
        reason=payload.reason,
        context={"released": int(getattr(result, "rowcount", 0) or 0)},
    )
    await session.commit()
    return success(
        {"released": int(getattr(result, "rowcount", 0) or 0)}, request_id_from_request(request)
    )
