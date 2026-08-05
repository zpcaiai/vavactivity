"""Offline evaluation runs and guarded strategy experiments.

Experiments are disabled by default, require approval, pin their strategies and
are stopped by guardrails — never promoted on click-through alone.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.recommendations import evaluation as evaluation_engine
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import ExperimentStatus

EXPERIMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    ExperimentStatus.DRAFT.value: frozenset({ExperimentStatus.APPROVED.value}),
    ExperimentStatus.APPROVED.value: frozenset(
        {ExperimentStatus.RUNNING.value, ExperimentStatus.STOPPED.value}
    ),
    ExperimentStatus.RUNNING.value: frozenset(
        {
            ExperimentStatus.PAUSED.value,
            ExperimentStatus.STOPPED.value,
            ExperimentStatus.COMPLETED.value,
        }
    ),
    ExperimentStatus.PAUSED.value: frozenset(
        {ExperimentStatus.RUNNING.value, ExperimentStatus.STOPPED.value}
    ),
    ExperimentStatus.STOPPED.value: frozenset(),
    ExperimentStatus.COMPLETED.value: frozenset(),
}


# --------------------------------------------------------------------------
# Evaluation runs
# --------------------------------------------------------------------------


async def dataset_by_code(session: AsyncSession, dataset_code: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_evaluation_datasets WHERE dataset_code=:code"),
            {"code": dataset_code},
        )
    ).mappings()
    found = row.first()
    if found is None:
        raise VavError(
            "RECOMMENDATION_DATASET_NOT_FOUND", "Evaluation dataset not found.", status_code=404
        )
    return dict(found)


async def run_evaluation(
    session: AsyncSession,
    *,
    dataset_code: str,
    strategy_id: UUID,
    metrics: dict[str, int],
    guardrail_thresholds: dict[str, int] | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Store an evaluation run and apply the release rules to its metrics."""
    dataset = await dataset_by_code(session, dataset_code)
    strategy = await service.strategy_by_id(session, strategy_id)
    await service.audit(
        session,
        "recommendation.evaluation.started",
        "recommendation_strategy",
        strategy_id,
        actor_id=actor_id,
        context={"dataset_code": dataset_code},
    )
    result = evaluation_engine.evaluate(
        dataset_code=dataset_code,
        strategy_code=str(strategy["strategy_code"]),
        strategy_version=str(strategy["semantic_version"]),
        metrics=metrics,
        guardrail_thresholds=guardrail_thresholds,
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO recommendation_evaluation_runs "
                "(dataset_id,strategy_id,status,metrics,blocking_failures,guardrail_failures,completed_at) "
                "VALUES (:dataset_id,:strategy_id,:status,CAST(:metrics AS jsonb),"
                "CAST(:blocking AS jsonb),CAST(:guardrails AS jsonb),now()) RETURNING *"
            ),
            {
                "dataset_id": dataset["id"],
                "strategy_id": strategy_id,
                "status": "passed" if result.passed else "failed",
                "metrics": service.json_value(result.metrics),
                "blocking": service.json_value(result.blocking_failures),
                "guardrails": service.json_value(result.guardrail_failures),
            },
        )
    ).mappings()
    created = row.first()
    if created is None:  # pragma: no cover - insert always returns
        raise VavError("RECOMMENDATION_EVALUATION_FAILED", "Evaluation failed.", status_code=500)
    await session.execute(
        text("UPDATE recommendation_strategies SET evaluation_run_id=:run WHERE id=:id"),
        {"run": created["id"], "id": strategy_id},
    )
    await service.audit(
        session,
        "recommendation.evaluation.completed",
        "recommendation_strategy",
        strategy_id,
        actor_id=actor_id,
        context={
            "passed": result.passed,
            "blocking_failures": result.blocking_failures,
            "guardrail_failures": result.guardrail_failures,
        },
    )
    if not result.passed:
        await service.audit(
            session,
            "recommendation.release.blocked",
            "recommendation_strategy",
            strategy_id,
            actor_id=actor_id,
            reason="evaluation_failed",
        )
    return {"run": dict(created), "result": result.as_dict()}


# --------------------------------------------------------------------------
# Experiments
# --------------------------------------------------------------------------


async def create_experiment(
    session: AsyncSession, *, payload: dict[str, Any], actor_id: UUID | None
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO recommendation_experiments "
                "(experiment_code,name,hypothesis,status,control_strategy_id,treatment_strategy_ids,"
                "eligibility_definition,allocation_policy,primary_metrics,guardrail_metrics,"
                "guardrail_thresholds,created_by) "
                "VALUES (:code,:name,:hypothesis,'draft',:control,CAST(:treatments AS jsonb),"
                "CAST(:eligibility AS jsonb),CAST(:allocation AS jsonb),CAST(:primary AS jsonb),"
                "CAST(:guardrails AS jsonb),CAST(:thresholds AS jsonb),:actor) RETURNING *"
            ),
            {
                "code": payload["experiment_code"],
                "name": payload["name"],
                "hypothesis": payload["hypothesis"],
                "control": payload["control_strategy_id"],
                "treatments": service.json_value(payload.get("treatment_strategy_ids", [])),
                "eligibility": service.json_value(payload.get("eligibility_definition", {})),
                "allocation": service.json_value(payload.get("allocation_policy", {})),
                "primary": service.json_value(payload.get("primary_metrics", [])),
                "guardrails": service.json_value(
                    payload.get("guardrail_metrics", list(evaluation_engine.GUARDRAIL_METRICS))
                ),
                "thresholds": service.json_value(payload.get("guardrail_thresholds", {})),
                "actor": actor_id,
            },
        )
    ).mappings()
    created = row.first()
    if created is None:  # pragma: no cover
        raise VavError("RECOMMENDATION_EXPERIMENT_FAILED", "Experiment failed.", status_code=500)
    await service.audit(
        session,
        "recommendation.experiment.created",
        "recommendation_experiment",
        created["id"],
        actor_id=actor_id,
        context={"experiment_code": payload["experiment_code"]},
    )
    return dict(created)


async def transition_experiment(
    session: AsyncSession,
    *,
    experiment_id: UUID,
    target_status: str,
    actor_id: UUID | None,
    reason: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_experiments WHERE id=:id"), {"id": experiment_id}
        )
    ).mappings()
    current = row.first()
    if current is None:
        raise VavError(
            "RECOMMENDATION_EXPERIMENT_NOT_FOUND", "Experiment not found.", status_code=404
        )
    allowed = EXPERIMENT_TRANSITIONS.get(str(current["status"]), frozenset())
    if target_status not in allowed:
        raise VavError(
            "RECOMMENDATION_EXPERIMENT_TRANSITION_INVALID",
            f"An experiment cannot move from {current['status']} to {target_status}.",
            status_code=409,
        )
    if target_status == ExperimentStatus.RUNNING.value:
        if not settings.recommendation_experiments_enabled:
            raise VavError(
                "RECOMMENDATION_EXPERIMENTS_DISABLED",
                "Recommendation experiments are disabled.",
                status_code=409,
            )
        if settings.recommendation_experiment_approval_required and current["approved_by"] is None:
            raise VavError(
                "RECOMMENDATION_EXPERIMENT_NOT_APPROVED",
                "An experiment must be approved before it starts.",
                status_code=409,
            )
        await _require_passing_treatments(session, current)

    assignment = ""
    if target_status == ExperimentStatus.APPROVED.value:
        assignment = "approved_by=:actor, approved_at=now(), "
    elif target_status == ExperimentStatus.RUNNING.value:
        assignment = "starts_at=COALESCE(starts_at, now()), "
    elif target_status in {ExperimentStatus.STOPPED.value, ExperimentStatus.COMPLETED.value}:
        assignment = "ends_at=now(), stop_reason=:reason, "

    updated = (
        await session.execute(
            text(
                "UPDATE recommendation_experiments SET status=:status, "
                f"{assignment}id=id WHERE id=:id AND status=:expected RETURNING *"
            ),
            {
                "status": target_status,
                "id": experiment_id,
                "expected": current["status"],
                "actor": actor_id,
                "reason": (reason or "")[:128] or None,
            },
        )
    ).mappings()
    result = updated.first()
    if result is None:
        raise VavError(
            "RECOMMENDATION_EXPERIMENT_CONFLICT",
            "The experiment changed while this request was in flight.",
            status_code=409,
        )
    event = {
        ExperimentStatus.APPROVED.value: "recommendation.experiment.approved",
        ExperimentStatus.RUNNING.value: "recommendation.experiment.started",
        ExperimentStatus.STOPPED.value: "recommendation.experiment.stopped",
        ExperimentStatus.COMPLETED.value: "recommendation.experiment.stopped",
    }.get(target_status, "recommendation.experiment.created")
    await service.audit(
        session,
        event,
        "recommendation_experiment",
        experiment_id,
        actor_id=actor_id,
        reason=reason,
        context={"status": target_status},
    )
    return dict(result)


async def _require_passing_treatments(session: AsyncSession, experiment: Any) -> None:
    treatments = service._jsonb(experiment["treatment_strategy_ids"]) or []
    for strategy_id in treatments:
        row = (
            await session.execute(
                text(
                    "SELECT status FROM recommendation_evaluation_runs WHERE strategy_id=:id "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"id": strategy_id},
            )
        ).mappings()
        latest = row.first()
        if latest is None or str(latest["status"]) != "passed":
            raise VavError(
                "RECOMMENDATION_EXPERIMENT_EVALUATION_REQUIRED",
                "Every treatment strategy needs a passing evaluation.",
                status_code=409,
            )


def assignment_hash(experiment_code: str, user_id: UUID, salt: str = "vav") -> str:
    return hashlib.sha256(f"{salt}:{experiment_code}:{user_id}".encode()).hexdigest()


async def assign(
    session: AsyncSession, *, experiment_id: UUID, user_id: UUID
) -> dict[str, Any] | None:
    """Assign a member to a variant, stably and only while the experiment runs."""
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_experiments WHERE id=:id"), {"id": experiment_id}
        )
    ).mappings()
    experiment = row.first()
    if experiment is None or str(experiment["status"]) != ExperimentStatus.RUNNING.value:
        return None
    existing = (
        await session.execute(
            text(
                "SELECT * FROM recommendation_experiment_assignments "
                "WHERE experiment_id=:experiment AND user_id=:user_id"
            ),
            {"experiment": experiment_id, "user_id": user_id},
        )
    ).mappings()
    found = existing.first()
    if found is not None:
        return dict(found)

    digest = assignment_hash(str(experiment["experiment_code"]), user_id)
    treatments = service._jsonb(experiment["treatment_strategy_ids"]) or []
    variants = ["control", *[f"treatment_{index + 1}" for index in range(len(treatments))]]
    variant = variants[int(digest[:8], 16) % len(variants)]
    inserted = (
        await session.execute(
            text(
                "INSERT INTO recommendation_experiment_assignments "
                "(experiment_id,user_id,variant_code,assignment_hash) "
                "VALUES (:experiment,:user_id,:variant,:hash) "
                "ON CONFLICT (experiment_id,user_id) DO NOTHING RETURNING *"
            ),
            {
                "experiment": experiment_id,
                "user_id": user_id,
                "variant": variant,
                "hash": digest,
            },
        )
    ).mappings()
    created = inserted.first()
    return dict(created) if created is not None else dict(found) if found else None


async def check_guardrails(
    session: AsyncSession,
    *,
    experiment_id: UUID,
    metrics: dict[str, int],
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Stop a running experiment as soon as a guardrail is breached."""
    row = (
        await session.execute(
            text("SELECT * FROM recommendation_experiments WHERE id=:id"), {"id": experiment_id}
        )
    ).mappings()
    experiment = row.first()
    if experiment is None:
        raise VavError(
            "RECOMMENDATION_EXPERIMENT_NOT_FOUND", "Experiment not found.", status_code=404
        )
    thresholds = service._jsonb(experiment["guardrail_thresholds"]) or {}
    breached = [
        name for name, threshold in thresholds.items() if int(metrics.get(name, 0)) > int(threshold)
    ]
    if breached and str(experiment["status"]) == ExperimentStatus.RUNNING.value:
        await transition_experiment(
            session,
            experiment_id=experiment_id,
            target_status=ExperimentStatus.STOPPED.value,
            actor_id=actor_id,
            reason=f"guardrail_breached:{breached[0]}",
        )
    return {"breached": breached, "stopped": bool(breached)}
