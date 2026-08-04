"""Admin recommendation operations centre."""

# ruff: noqa: B008, E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.recommendations import constraints, evaluation, service
from vav.modules.recommendations import exposure as exposure_rules
from vav.modules.recommendations.schemas import (
    EvaluationRunRequest,
    ExperimentCreateRequest,
    ExperimentDecisionRequest,
    RebuildRequest,
    StrategyCreateRequest,
    StrategyDecisionRequest,
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
    service.enabled()
    pool_total = await session.scalar(text("SELECT count(*) FROM recommendation_pool_entries"))
    pool_eligible = await session.scalar(
        text("SELECT count(*) FROM recommendation_pool_entries WHERE eligible=true")
    )
    pairs = await session.scalar(
        text("SELECT count(*) FROM recommendation_candidate_pairs WHERE invalidated_at IS NULL")
    )
    passed_pairs = await session.scalar(
        text(
            "SELECT count(*) FROM recommendation_candidate_pairs WHERE status='eligible' AND invalidated_at IS NULL"
        )
    )
    batches = await session.scalar(text("SELECT count(*) FROM recommendation_batches"))
    active_batches = await session.scalar(
        text("SELECT count(*) FROM recommendation_batches WHERE status='active'")
    )
    exposures = await session.scalar(text("SELECT count(*) FROM recommendation_exposures"))
    feedback = await session.scalar(text("SELECT count(*) FROM recommendation_feedback_events"))
    negative = await session.scalar(
        text(
            "SELECT count(*) FROM recommendation_feedback_events WHERE feedback_type IN "
            "('skipped','not_relevant','reported','blocked')"
        )
    )
    safety_feedback = await session.scalar(
        text(
            "SELECT count(*) FROM recommendation_feedback_events WHERE feedback_type IN ('reported','blocked')"
        )
    )
    users_without_batch = int(pool_eligible or 0) - int(
        await session.scalar(
            text(
                "SELECT count(DISTINCT user_id) FROM recommendation_batches WHERE generated_size > 0"
            )
        )
        or 0
    )
    fairness_rows = (
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
    fairness = exposure_rules.exposure_fairness(
        {str(row["user_id"]): int(row["exposures"]) for row in fairness_rows}, len(fairness_rows)
    )
    return success(
        {
            "pool_users": int(pool_total or 0),
            "pool_eligible_users": int(pool_eligible or 0),
            "candidate_pairs": int(pairs or 0),
            "hard_constraint_pass_rate_bps": (
                round(int(passed_pairs or 0) * 10000 / int(pairs or 1)) if pairs else 0
            ),
            "average_candidates_per_user": (
                round(int(pairs or 0) / int(pool_eligible or 1), 2) if pool_eligible else 0
            ),
            "users_without_recommendations": max(0, users_without_batch),
            "batches_generated": int(batches or 0),
            "active_batches": int(active_batches or 0),
            "exposures": int(exposures or 0),
            "feedback_events": int(feedback or 0),
            "negative_feedback_events": int(negative or 0),
            "safety_feedback_events": int(safety_feedback or 0),
            "exposure_fairness": fairness,
        },
        request_id_from_request(request),
    )


@router.get("/strategies")
async def list_strategies(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,strategy_code,semantic_version,status,evaluation_passed,created_by,approved_by,"
                    "created_at,approved_at,activated_at FROM recommendation_strategies ORDER BY created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/strategies/{strategy_id}")
async def strategy_detail(
    strategy_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    row = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_strategies WHERE id=:id"), {"id": strategy_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("RECOMMENDATION_STRATEGY_NOT_FOUND", "Strategy not found.", status_code=404)
    return success(dict(row), request_id_from_request(request))


@router.post("/strategies", status_code=201)
async def create_strategy(
    payload: StrategyCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    strategy_id = await session.scalar(
        text(
            "INSERT INTO recommendation_strategies (strategy_code,semantic_version,status,"
            "hard_constraint_policy,feature_manifest,scoring_policy,bidirectional_policy,ranking_policy,"
            "diversification_policy,exposure_policy,explanation_policy,cold_start_policy,created_by) "
            "VALUES (:code,:version,'draft',CAST(:hard AS jsonb),CAST(:features AS jsonb),CAST(:scoring AS jsonb),"
            "CAST(:bidirectional AS jsonb),CAST(:ranking AS jsonb),CAST(:diversification AS jsonb),"
            "CAST(:exposure AS jsonb),CAST(:explanation AS jsonb),CAST(:cold_start AS jsonb),:actor) RETURNING id"
        ),
        {
            "code": payload.strategy_code,
            "version": payload.semantic_version,
            "hard": service.json_value(payload.hard_constraint_policy),
            "features": service.json_value(payload.feature_manifest),
            "scoring": service.json_value(payload.scoring_policy),
            "bidirectional": service.json_value(payload.bidirectional_policy),
            "ranking": service.json_value(payload.ranking_policy),
            "diversification": service.json_value(payload.diversification_policy),
            "exposure": service.json_value(payload.exposure_policy),
            "explanation": service.json_value(payload.explanation_policy),
            "cold_start": service.json_value(payload.cold_start_policy),
            "actor": principal.user.id,
        },
    )
    await service.audit(
        session,
        "recommendation.strategy.created",
        "recommendation_strategy",
        UUID(str(strategy_id)),
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(
        {"strategy_id": str(strategy_id), "status": "draft"}, request_id_from_request(request)
    )


@router.post("/strategies/{strategy_id}/approve")
async def approve_strategy(
    strategy_id: UUID,
    payload: StrategyDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Approval is separate from authorship and from activation."""
    service.enabled()
    author = await session.scalar(
        text("SELECT created_by FROM recommendation_strategies WHERE id=:id"), {"id": strategy_id}
    )
    if author is None:
        raise VavError("RECOMMENDATION_STRATEGY_NOT_FOUND", "Strategy not found.", status_code=404)
    if author == principal.user.id:
        raise VavError(
            "RECOMMENDATION_SELF_APPROVAL_FORBIDDEN",
            "A strategy cannot be approved by its own author.",
            status_code=403,
        )
    await session.execute(
        text(
            "UPDATE recommendation_strategies SET status='approved',approved_by=:actor,approved_at=now() "
            "WHERE id=:id AND status='draft'"
        ),
        {"id": strategy_id, "actor": principal.user.id},
    )
    await service.audit(
        session,
        "recommendation.strategy.approved",
        "recommendation_strategy",
        strategy_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"strategy_id": str(strategy_id), "status": "approved"}, request_id_from_request(request)
    )


@router.post("/strategies/{strategy_id}/activate")
async def activate_strategy(
    strategy_id: UUID,
    payload: StrategyDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.activate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Activation requires approval plus a passing evaluation, enforced in SQL."""
    service.enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT strategy_code,status,approved_by,evaluation_passed FROM recommendation_strategies WHERE id=:id"
                ),
                {"id": strategy_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("RECOMMENDATION_STRATEGY_NOT_FOUND", "Strategy not found.", status_code=404)
    if row["approved_by"] is None:
        raise VavError(
            "RECOMMENDATION_STRATEGY_NOT_APPROVED",
            "This strategy has not been approved.",
            status_code=409,
        )
    if not row["evaluation_passed"]:
        raise VavError(
            "RECOMMENDATION_STRATEGY_NOT_EVALUATED",
            "This strategy has not passed an evaluation.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE recommendation_strategies SET status='superseded' WHERE strategy_code=:code AND status='active'"
        ),
        {"code": row["strategy_code"]},
    )
    await session.execute(
        text(
            "UPDATE recommendation_strategies SET status='active',activated_by=:actor,activated_at=now() WHERE id=:id"
        ),
        {"id": strategy_id, "actor": principal.user.id},
    )
    await service.audit(
        session,
        "recommendation.strategy.activated",
        "recommendation_strategy",
        strategy_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"strategy_id": str(strategy_id), "status": "active"}, request_id_from_request(request)
    )


@router.post("/strategies/{strategy_id}/rollback")
async def rollback_strategy(
    strategy_id: UUID,
    payload: StrategyDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.strategies.rollback")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    await session.execute(
        text(
            "UPDATE recommendation_strategies SET status='rolled_back' WHERE id=:id AND status='active'"
        ),
        {"id": strategy_id},
    )
    await service.audit(
        session,
        "recommendation.strategy.rolled_back",
        "recommendation_strategy",
        strategy_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"strategy_id": str(strategy_id), "status": "rolled_back"}, request_id_from_request(request)
    )


@router.get("/features")
async def list_features(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.features.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS

    rows = (
        (
            await session.execute(
                text(
                    "SELECT feature_code,semantic_version,feature_group,scoring_function_code,sensitivity,"
                    "explainable,user_configurable,status FROM recommendation_feature_definitions ORDER BY feature_group,feature_code"
                )
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            # Operators cannot add these through the console either.
            "prohibited_signals": sorted(PROHIBITED_SCORING_SIGNALS),
        },
        request_id_from_request(request),
    )


@router.get("/constraints")
async def list_constraints(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.constraints.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    strategy = await service.active_strategy(session)
    return success(
        {
            "hard_constraint_policy": strategy["hard_constraint_policy"],
            "auto_relaxation_enabled": get_settings().recommendation_hard_constraint_auto_relax,
        },
        request_id_from_request(request),
    )


@router.get("/batches")
async def list_batches(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.batches.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    total = await session.scalar(text("SELECT count(*) FROM recommendation_batches"))
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,user_id,batch_number,batch_type,status,requested_size,generated_size,"
                    "generated_at,activated_at,expires_at,created_at FROM recommendation_batches "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"limit": min(page_size, 100), "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        },
        request_id_from_request(request),
    )


@router.get("/batches/{batch_id}")
async def batch_detail(
    batch_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.batches.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    batch = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_batches WHERE id=:id"), {"id": batch_id}
            )
        )
        .mappings()
        .first()
    )
    if batch is None:
        raise VavError("RECOMMENDATION_BATCH_NOT_FOUND", "Batch not found.", status_code=404)
    ranks = (
        (
            await session.execute(
                text(
                    "SELECT candidate_pair_id,base_score_bps,adjusted_score_bps,novelty_adjustment_bps,"
                    "diversity_adjustment_bps,exposure_adjustment_bps,exploration_adjustment_bps,final_rank "
                    "FROM recommendation_rank_results WHERE recommendation_batch_id=:id ORDER BY final_rank"
                ),
                {"id": batch_id},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "batch": dict(batch),
            "rank_results": [dict(row) for row in ranks],
            "adjusted_scores_are_not_compatibility": True,
        },
        request_id_from_request(request),
    )


@router.post("/batches/{batch_id}/invalidate")
async def invalidate_batch(
    batch_id: UUID,
    payload: RebuildRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.batches.invalidate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    await session.execute(
        text("UPDATE recommendation_batches SET status='cancelled' WHERE id=:id"), {"id": batch_id}
    )
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated',invalidation_reason='batch_cancelled' "
            "WHERE recommendation_batch_id=:id AND status IN ('ready','exposed')"
        ),
        {"id": batch_id},
    )
    await service.audit(
        session,
        "recommendation.batch.invalidated",
        "recommendation_batch",
        batch_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"batch_id": str(batch_id), "status": "cancelled"}, request_id_from_request(request)
    )


@router.post("/users/{user_id}/rebuild")
async def rebuild_for_user(
    user_id: UUID,
    payload: RebuildRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.batches.rebuild")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Rebuild one member's pool entry and candidates. Never hand-place a pair."""
    service.enabled()
    await service.sync_pool_entry(session, user_id)
    await session.commit()
    result = await service.generate_candidates(session, user_id)
    await service.audit(
        session,
        "recommendation.candidates.generated",
        "user",
        user_id,
        actor_id=principal.user.id,
        reason=payload.reason,
        context={"manual_rebuild": True},
    )
    await session.commit()
    return success(
        {**result, "manual_pair_placement_supported": False}, request_id_from_request(request)
    )


@router.post("/pool/rebuild")
async def rebuild_pool(
    payload: RebuildRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.batches.rebuild")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    result = await service.rebuild_pool(session)
    await service.audit(
        session,
        "recommendation.pool.user_added",
        "recommendation_pool",
        None,
        actor_id=principal.user.id,
        reason=payload.reason,
        context=result,
    )
    await session.commit()
    return success(result, request_id_from_request(request))


@router.get("/diagnostics/{user_id}")
async def diagnostics(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.diagnostics.run")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Aggregate diagnostics. Individual private criteria are never shown."""
    service.enabled()
    entry = (
        (
            await session.execute(
                text("SELECT * FROM recommendation_pool_entries WHERE user_id=:id"), {"id": user_id}
            )
        )
        .mappings()
        .first()
    )
    snapshots = (
        (
            await session.execute(
                text(
                    "SELECT hard_constraint_snapshot FROM recommendation_candidate_pairs "
                    "WHERE (user_low_id=:id OR user_high_id=:id) AND invalidated_at IS NULL LIMIT 1000"
                ),
                {"id": user_id},
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
        for snapshot in snapshots
    ]
    batch_size = await session.scalar(
        text(
            "SELECT generated_size FROM recommendation_batches WHERE user_id=:id AND status='active' LIMIT 1"
        ),
        {"id": user_id},
    )
    sensitive = "recommendations.candidates.sensitive.read" in principal.permissions
    return success(
        {
            "pool_entry": dict(entry) if entry else None,
            "candidate_diagnostics": constraints.diagnostic_summary(evaluations),
            "active_batch_size": int(batch_size or 0),
            "sensitive_access_granted": sensitive,
            "individual_preference_criteria_shown": False,
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
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.user_id, count(e.id) AS exposures FROM recommendation_pool_entries p "
                    "LEFT JOIN recommendation_exposures e ON e.exposed_user_id=p.user_id "
                    "WHERE p.eligible=true GROUP BY p.user_id ORDER BY exposures DESC LIMIT 200"
                )
            )
        )
        .mappings()
        .all()
    )
    counts = {str(row["user_id"]): int(row["exposures"]) for row in rows}
    return success(
        {
            "fairness": exposure_rules.exposure_fairness(counts, len(counts)),
            "top_exposed": [dict(row) for row in rows[:20]],
        },
        request_id_from_request(request),
    )


@router.get("/feedback")
async def feedback_summary(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.feedback.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Aggregate feedback only. Free-text reasons stay encrypted."""
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT feedback_type, reason_code, count(*) AS total FROM recommendation_feedback_events "
                    "GROUP BY feedback_type, reason_code ORDER BY total DESC"
                )
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "free_text_reasons_returned": False,
            "sensitive_access_granted": "recommendations.feedback.sensitive.read"
            in principal.permissions,
        },
        request_id_from_request(request),
    )


@router.get("/evaluations")
async def list_evaluations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.evaluations.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,dataset_id,strategy_id,status,passed,guardrail_failures,started_at,completed_at "
                    "FROM recommendation_evaluation_runs ORDER BY started_at DESC LIMIT 100"
                )
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/evaluations/run", status_code=201)
async def run_evaluation(
    payload: EvaluationRunRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.evaluations.run")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await evaluation.run(
            session,
            principal.user,
            dataset_id=payload.dataset_id,
            strategy_id=payload.strategy_id,
        ),
        request_id_from_request(request),
    )


@router.get("/experiments")
async def list_experiments(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,experiment_code,name,status,control_strategy_id,starts_at,ends_at,"
                    "approved_by,created_at FROM recommendation_experiments ORDER BY created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "experiments_enabled": get_settings().recommendation_experiments_enabled,
        },
        request_id_from_request(request),
    )


@router.post("/experiments", status_code=201)
async def create_experiment(
    payload: ExperimentCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    guardrails = payload.guardrail_metrics or list(evaluation.GUARDRAIL_THRESHOLDS)
    experiment_id = await session.scalar(
        text(
            "INSERT INTO recommendation_experiments (experiment_code,name,hypothesis,status,"
            "control_strategy_id,treatment_strategy_ids,eligibility_definition,allocation_policy,"
            "primary_metrics,guardrail_metrics,created_by) "
            "VALUES (:code,:name,:hypothesis,'draft',:control,CAST(:treatments AS jsonb),"
            "CAST(:eligibility AS jsonb),CAST(:allocation AS jsonb),CAST(:primary AS jsonb),"
            "CAST(:guardrails AS jsonb),:actor) RETURNING id"
        ),
        {
            "code": payload.experiment_code,
            "name": payload.name,
            "hypothesis": payload.hypothesis,
            "control": payload.control_strategy_id,
            "treatments": service.json_value(
                [str(item) for item in payload.treatment_strategy_ids]
            ),
            "eligibility": service.json_value(payload.eligibility_definition),
            "allocation": service.json_value(payload.allocation_policy),
            "primary": service.json_value(payload.primary_metrics),
            "guardrails": service.json_value(guardrails),
            "actor": principal.user.id,
        },
    )
    await session.commit()
    return success(
        {"experiment_id": str(experiment_id), "status": "draft", "guardrail_metrics": guardrails},
        request_id_from_request(request),
    )


@router.post("/experiments/{experiment_id}/start")
async def start_experiment(
    experiment_id: UUID,
    payload: ExperimentDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("recommendations.experiments.start")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Starting requires the feature flag plus a separate approver."""
    service.enabled()
    settings = get_settings()
    if not settings.recommendation_experiments_enabled:
        raise VavError(
            "RECOMMENDATION_EXPERIMENTS_DISABLED",
            "Recommendation experiments are disabled on this platform.",
            status_code=409,
        )
    approved = await session.scalar(
        text("SELECT approved_by FROM recommendation_experiments WHERE id=:id"),
        {"id": experiment_id},
    )
    if approved is None:
        raise VavError(
            "RECOMMENDATION_EXPERIMENT_NOT_APPROVED",
            "This experiment has not been approved.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE recommendation_experiments SET status='running',starts_at=now() WHERE id=:id AND status='approved'"
        ),
        {"id": experiment_id},
    )
    await service.audit(
        session,
        "recommendation.experiment.started",
        "recommendation_experiment",
        experiment_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"experiment_id": str(experiment_id), "status": "running"}, request_id_from_request(request)
    )


@router.get("/audit")
async def audit_events(
    request: Request,
    subject_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: AuthenticatedPrincipal = Depends(require_permission("recommendations.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    clause = "WHERE subject_id=:subject_id" if subject_id else ""
    params: dict[str, Any] = {"subject_id": subject_id} if subject_id else {}
    total = await session.scalar(
        text(f"SELECT count(*) FROM recommendation_audit_events {clause}"), params
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,event_type,actor_id,subject_type,subject_id,reason,safe_context,created_at "
                    f"FROM recommendation_audit_events {clause} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params | {"limit": min(page_size, 200), "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        },
        request_id_from_request(request),
    )
