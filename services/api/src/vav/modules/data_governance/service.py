# ruff: noqa: E501

"""Data-integrity control-plane persistence and orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.data_governance.domain import event_disposition, minimize_evidence
from vav.modules.data_governance.schemas import (
    BackfillAction,
    BackfillStart,
    ErasurePlanCreate,
    ErasureTaskComplete,
    EventEnvelope,
    ExternalIdentifierCreate,
    InboxApply,
    IntegrityEvaluate,
    ProjectionRebuild,
    QualityEvaluationCreate,
    ReconciliationRun,
    RepairRequest,
)
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _row(value: Any) -> dict[str, Any]:
    return dict(value._mapping)


async def _audit(
    session: AsyncSession,
    actor_id: UUID,
    action: str,
    subject_type: str,
    subject_id: UUID,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) VALUES (:actor,'administrator',:action,:subject,:subject_id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "action": action,
            "subject": subject_type,
            "subject_id": str(subject_id),
            "context": _json(context or {}),
        },
    )


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM data_assets WHERE lifecycle_status='active') active_assets,(SELECT count(*) FROM data_contracts WHERE status='active') active_contracts,(SELECT count(*) FROM data_event_gaps WHERE status IN ('open','recovering')) open_event_gaps,(SELECT count(*) FROM data_dead_letters WHERE status IN ('open','quarantined')) open_dead_letters,(SELECT count(*) FROM data_reconciliation_differences WHERE status IN ('open','quarantined','repair_planned')) open_differences,(SELECT count(*) FROM data_erasure_plans WHERE status='verification_failed') erasure_failures,(SELECT count(*) FROM data_backfill_runs WHERE status IN ('running','paused')) active_backfills"
            )
        )
    ).first()
    return _row(row) if row else {}


async def list_section(session: AsyncSession, section: str) -> list[dict[str, Any]]:
    queries = {
        "assets": "SELECT * FROM data_assets ORDER BY asset_code LIMIT 500",
        "contracts": "SELECT c.*,a.asset_code FROM data_contracts c JOIN data_assets a ON a.id=c.asset_id ORDER BY c.contract_code,c.semantic_version DESC LIMIT 500",
        "lineage": "SELECT e.*,s.asset_code source_asset_code,t.asset_code target_asset_code FROM data_lineage_edges e JOIN data_assets s ON s.id=e.source_asset_id JOIN data_assets t ON t.id=e.target_asset_id ORDER BY s.asset_code,t.asset_code LIMIT 500",
        "events": "SELECT id,event_id,event_type,aggregate_type,aggregate_id,aggregate_version,status,attempt_count,published_at,created_at FROM data_event_outbox ORDER BY created_at DESC LIMIT 250",
        "event-gaps": "SELECT * FROM data_event_gaps ORDER BY detected_at DESC LIMIT 250",
        "dead-letters": "SELECT id,event_id,consumer_code,event_type,affected_entity_type,affected_entity_id,failure_code,status,replay_count,created_at,resolved_at FROM data_dead_letters ORDER BY created_at DESC LIMIT 250",
        "quality": "SELECT r.*,a.asset_code FROM data_quality_rules r JOIN data_assets a ON a.id=r.asset_id ORDER BY r.severity DESC,r.rule_code LIMIT 500",
        "reconciliations": "SELECT d.*,s.asset_code source_asset_code,t.asset_code target_asset_code FROM data_reconciliation_definitions d JOIN data_assets s ON s.id=d.source_asset_id JOIN data_assets t ON t.id=d.target_asset_id ORDER BY d.reconciliation_code LIMIT 250",
        "differences": "SELECT * FROM data_reconciliation_differences ORDER BY severity DESC,id DESC LIMIT 250",
        "backfills": "SELECT r.*,d.backfill_code FROM data_backfill_runs r JOIN data_backfill_definitions d ON d.id=r.definition_id ORDER BY r.started_at DESC NULLS LAST LIMIT 250",
        "repairs": "SELECT * FROM data_repair_definitions ORDER BY repair_code LIMIT 250",
        "projections": "SELECT r.*,a.asset_code FROM data_projection_rebuilds r JOIN data_assets a ON a.id=r.asset_id ORDER BY r.created_at DESC LIMIT 250",
        "erasures": "SELECT * FROM data_erasure_plans ORDER BY created_at DESC LIMIT 250",
        "certifications": "SELECT * FROM data_integrity_certifications ORDER BY evaluated_at DESC LIMIT 250",
        "release": "SELECT * FROM data_integrity_certifications ORDER BY evaluated_at DESC LIMIT 250",
    }
    sql = queries.get(section)
    if not sql:
        raise VavError(
            "DATA_SECTION_NOT_FOUND", "Data governance section not found.", status_code=404
        )
    return [dict(row) for row in (await session.execute(text(sql))).mappings()]


async def register_external_identifier(
    session: AsyncSession, actor_id: UUID, payload: ExternalIdentifierCreate
) -> dict[str, Any]:
    """Persist a provider identifier without exposing its plaintext representation."""
    identifier_hash = searchable_hmac(payload.external_identifier)
    row = (
        await session.execute(
            text(
                "INSERT INTO canonical_external_identifiers (entity_type,canonical_entity_id,provider_code,external_identifier_hash,external_identifier_encrypted) VALUES (:entity_type,:canonical_id,:provider,:identifier_hash,:ciphertext) ON CONFLICT (entity_type,provider_code,external_identifier_hash) DO UPDATE SET canonical_entity_id=EXCLUDED.canonical_entity_id,status='active',revoked_at=NULL RETURNING id,entity_type,canonical_entity_id,provider_code,external_identifier_hash,status,created_at,revoked_at"
            ),
            {
                "entity_type": payload.entity_type,
                "canonical_id": payload.canonical_entity_id,
                "provider": payload.provider_code,
                "identifier_hash": identifier_hash,
                "ciphertext": encrypt_private(payload.external_identifier),
            },
        )
    ).first()
    result = _row(row)
    await _audit(
        session,
        actor_id,
        "data.external_identifier.registered",
        "canonical_external_identifier",
        result["id"],
        {"entity_type": payload.entity_type, "provider_code": payload.provider_code},
    )
    await session.commit()
    return result


async def evaluate_quality(
    session: AsyncSession, payload: QualityEvaluationCreate
) -> dict[str, Any]:
    rule = (
        await session.execute(
            text(
                "SELECT * FROM data_quality_rules WHERE rule_code=:code AND status='active' ORDER BY version DESC LIMIT 1"
            ),
            {"code": payload.rule_code},
        )
    ).first()
    if not rule:
        raise VavError("DATA_QUALITY_RULE_NOT_FOUND", "Quality rule not found.", status_code=404)
    current = _row(rule)
    threshold = float(current["declarative_rule"].get("maximum_failure_rate", 0))
    failure_rate = (
        payload.failed_records / payload.evaluated_records if payload.evaluated_records else 0
    )
    status = "pass" if failure_rate <= threshold else "fail"
    row = (
        await session.execute(
            text(
                "INSERT INTO data_quality_evaluations (rule_id,evaluated_records,failed_records,failure_rate,minimized_sample,status) VALUES (:rule,:evaluated,:failed,:rate,CAST(:sample AS jsonb),:status) RETURNING *"
            ),
            {
                "rule": current["id"],
                "evaluated": payload.evaluated_records,
                "failed": payload.failed_records,
                "rate": failure_rate,
                "sample": _json(minimize_evidence(payload.sample)),
                "status": status,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def request_repair(
    session: AsyncSession, actor_id: UUID, payload: RepairRequest
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text("SELECT * FROM data_repair_definitions WHERE repair_code=:code AND active=true"),
            {"code": payload.repair_code},
        )
    ).first()
    if not definition:
        raise VavError("DATA_REPAIR_NOT_REGISTERED", "Repair is not registered.", status_code=404)
    row = (
        await session.execute(
            text(
                "INSERT INTO data_repair_executions (repair_definition_id,reconciliation_difference_id,idempotency_key,input_mapping,status,requested_by) VALUES (:definition,:difference,:key,CAST(:input AS jsonb),'requested',:actor) ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key RETURNING *"
            ),
            {
                "definition": _row(definition)["id"],
                "difference": payload.reconciliation_difference_id,
                "key": payload.idempotency_key,
                "input": _json(minimize_evidence(payload.input_mapping)),
                "actor": actor_id,
            },
        )
    ).first()
    result = _row(row)
    await _audit(
        session,
        actor_id,
        "data.repair.requested",
        "data_repair_execution",
        result["id"],
        {"repair_code": payload.repair_code},
    )
    await session.commit()
    return result


async def enqueue_outbox(session: AsyncSession, envelope: EventEnvelope) -> dict[str, Any]:
    """Enqueue inside the caller's domain transaction; this function does not commit."""
    checksum = _hash(envelope.payload)
    existing = (
        await session.execute(
            text("SELECT * FROM data_event_outbox WHERE event_id=:id"), {"id": envelope.event_id}
        )
    ).first()
    if existing:
        current = _row(existing)
        if current["payload_checksum_sha256"] != checksum:
            raise VavError(
                "DATA_EVENT_ID_REUSED",
                "Event ID was reused with different payload.",
                status_code=409,
            )
        return current
    row = (
        await session.execute(
            text(
                "INSERT INTO data_event_outbox (event_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_version,sequence_number,occurred_at,producer_module,correlation_id,causation_id,subject_user_id,payload,metadata,payload_checksum_sha256) VALUES (:event_id,:event_type,:event_version,:aggregate_type,:aggregate_id,:aggregate_version,:sequence,:occurred_at,:producer,:correlation,:causation,:subject,CAST(:payload AS jsonb),CAST(:metadata AS jsonb),:checksum) ON CONFLICT (event_id) DO NOTHING RETURNING *"
            ),
            {
                "event_id": envelope.event_id,
                "event_type": envelope.event_type,
                "event_version": envelope.event_version,
                "aggregate_type": envelope.aggregate_type,
                "aggregate_id": envelope.aggregate_id,
                "aggregate_version": envelope.aggregate_version,
                "sequence": envelope.sequence_number,
                "occurred_at": datetime.now(UTC),
                "producer": envelope.producer_module,
                "correlation": envelope.correlation_id,
                "causation": envelope.causation_id,
                "subject": envelope.subject_user_id,
                "payload": _json(envelope.payload),
                "metadata": _json(envelope.metadata),
                "checksum": checksum,
            },
        )
    ).first()
    if row:
        return _row(row)
    concurrent = (
        await session.execute(
            text("SELECT * FROM data_event_outbox WHERE event_id=:id"), {"id": envelope.event_id}
        )
    ).first()
    if not concurrent or _row(concurrent)["payload_checksum_sha256"] != checksum:
        raise VavError(
            "DATA_EVENT_ID_REUSED", "Event ID was reused with different payload.", status_code=409
        )
    return _row(concurrent)


async def apply_inbox(session: AsyncSession, payload: InboxApply) -> dict[str, Any]:
    envelope = payload.envelope
    checksum = _hash(envelope.payload)
    duplicate = (
        await session.execute(
            text(
                "SELECT * FROM data_event_inbox WHERE consumer_code=:consumer AND event_id=:event"
            ),
            {"consumer": payload.consumer_code, "event": envelope.event_id},
        )
    ).first()
    if duplicate:
        result = _row(duplicate)
        result["duplicate"] = True
        return result
    current_version = int(
        await session.scalar(
            text(
                "SELECT COALESCE(max(aggregate_version),0) FROM data_event_inbox WHERE consumer_code=:consumer AND aggregate_type=:type AND aggregate_id=:aggregate AND disposition='accepted'"
            ),
            {
                "consumer": payload.consumer_code,
                "type": envelope.aggregate_type,
                "aggregate": envelope.aggregate_id,
            },
        )
        or 0
    )
    disposition = event_disposition(current_version, envelope.aggregate_version)
    row = (
        await session.execute(
            text(
                "INSERT INTO data_event_inbox (consumer_code,event_id,event_type,aggregate_type,aggregate_id,aggregate_version,payload_checksum_sha256,disposition,effect_receipt,applied_at) VALUES (:consumer,:event,:event_type,:aggregate_type,:aggregate_id,:version,:checksum,:disposition,CAST(:receipt AS jsonb),CASE WHEN :accepted THEN now() ELSE NULL END) ON CONFLICT (consumer_code,event_id) DO NOTHING RETURNING *"
            ),
            {
                "consumer": payload.consumer_code,
                "event": envelope.event_id,
                "event_type": envelope.event_type,
                "aggregate_type": envelope.aggregate_type,
                "aggregate_id": envelope.aggregate_id,
                "version": envelope.aggregate_version,
                "checksum": checksum,
                "disposition": disposition,
                "receipt": _json(minimize_evidence(payload.effect_receipt)),
                "accepted": disposition == "accepted",
            },
        )
    ).first()
    if row is None:
        concurrent = (
            await session.execute(
                text(
                    "SELECT * FROM data_event_inbox WHERE consumer_code=:consumer AND event_id=:event"
                ),
                {"consumer": payload.consumer_code, "event": envelope.event_id},
            )
        ).first()
        await session.commit()
        result = _row(concurrent)
        result["duplicate"] = True
        return result
    if disposition == "buffered_future":
        expected = current_version + 1
        await session.execute(
            text(
                "INSERT INTO data_event_gaps (gap_code,consumer_code,aggregate_type,aggregate_id,expected_version,received_version,severity) VALUES (:code,:consumer,:type,:aggregate,:expected,:received,'critical') ON CONFLICT (gap_code) DO NOTHING"
            ),
            {
                "code": f"{payload.consumer_code}:{envelope.aggregate_type}:{envelope.aggregate_id}:{expected}",
                "consumer": payload.consumer_code,
                "type": envelope.aggregate_type,
                "aggregate": envelope.aggregate_id,
                "expected": expected,
                "received": envelope.aggregate_version,
            },
        )
    await session.commit()
    result = _row(row)
    result["duplicate"] = False
    return result


async def run_reconciliation(
    session: AsyncSession, actor_id: UUID, payload: ReconciliationRun
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM data_reconciliation_definitions WHERE reconciliation_code=:code AND active=true"
            ),
            {"code": payload.reconciliation_code},
        )
    ).first()
    if not definition:
        raise VavError(
            "DATA_RECONCILIATION_NOT_REGISTERED",
            "Reconciliation is not registered.",
            status_code=404,
        )
    definition_row = _row(definition)
    run_id = await session.scalar(
        text(
            "INSERT INTO data_reconciliation_runs (definition_id,status) VALUES (:definition,'running') RETURNING id"
        ),
        {"definition": definition_row["id"]},
    )
    differences = 0
    for comparison in payload.comparisons:
        key = str(comparison.get("key", ""))[:255]
        source = comparison.get("source")
        target = comparison.get("target")
        source_hash, target_hash = _hash(source), _hash(target)
        if source_hash == target_hash:
            continue
        differences += 1
        await session.execute(
            text(
                "INSERT INTO data_reconciliation_differences (run_id,difference_key,category,severity,source_fingerprint,target_fingerprint,minimized_evidence) VALUES (:run,:key,'value_mismatch',:severity,:source,:target,CAST(:evidence AS jsonb)) ON CONFLICT (run_id,difference_key) DO NOTHING"
            ),
            {
                "run": run_id,
                "key": key,
                "severity": definition_row["severity"],
                "source": source_hash,
                "target": target_hash,
                "evidence": _json(
                    {
                        "authoritative_side": definition_row["authoritative_side"],
                        "repair_command_code": definition_row["repair_command_code"],
                    }
                ),
            },
        )
    await session.execute(
        text(
            "UPDATE data_reconciliation_runs SET compared_count=:compared,difference_count=:differences,status='completed',completed_at=now() WHERE id=:id"
        ),
        {"compared": len(payload.comparisons), "differences": differences, "id": run_id},
    )
    await _audit(
        session,
        actor_id,
        "data.reconciliation.completed",
        "data_reconciliation_run",
        run_id,
        {"compared": len(payload.comparisons), "differences": differences},
    )
    await session.commit()
    return {
        "run_id": run_id,
        "compared_count": len(payload.comparisons),
        "difference_count": differences,
        "repair_command_code": definition_row["repair_command_code"],
    }


async def start_backfill(
    session: AsyncSession, actor_id: UUID, payload: BackfillStart
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM data_backfill_definitions WHERE backfill_code=:code AND active=true"
            ),
            {"code": payload.backfill_code},
        )
    ).first()
    if not definition:
        raise VavError(
            "DATA_BACKFILL_NOT_REGISTERED", "Backfill is not registered.", status_code=404
        )
    definition_row = _row(definition)
    existing = (
        await session.execute(
            text(
                "SELECT r.*,d.backfill_code FROM data_backfill_runs r JOIN data_backfill_definitions d ON d.id=r.definition_id WHERE r.idempotency_key=:key"
            ),
            {"key": payload.idempotency_key},
        )
    ).first()
    if existing:
        current = _row(existing)
        if current["stable_candidate_hash"] != payload.stable_candidate_hash:
            raise VavError(
                "DATA_BACKFILL_KEY_REUSED",
                "Backfill idempotency key conflicts with candidate set.",
                status_code=409,
            )
        return current
    if (
        payload.environment == "production"
        and not payload.dry_run
        and not definition_row["approval_required"]
    ):
        raise VavError(
            "DATA_PRODUCTION_BACKFILL_APPROVAL_POLICY_INVALID",
            "Production mutation requires approval policy.",
            status_code=409,
        )
    status = (
        "created" if payload.environment == "production" and not payload.dry_run else "approved"
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO data_backfill_runs (definition_id,environment,dry_run,idempotency_key,stable_candidate_hash,status,requested_by) VALUES (:definition,:environment,:dry_run,:key,:candidate,:status,:actor) ON CONFLICT (idempotency_key) DO NOTHING RETURNING *"
            ),
            {
                "definition": definition_row["id"],
                "environment": payload.environment,
                "dry_run": payload.dry_run,
                "key": payload.idempotency_key,
                "candidate": payload.stable_candidate_hash,
                "status": status,
                "actor": actor_id,
            },
        )
    ).first()
    if row is None:
        concurrent = (
            await session.execute(
                text("SELECT * FROM data_backfill_runs WHERE idempotency_key=:key"),
                {"key": payload.idempotency_key},
            )
        ).first()
        if (
            not concurrent
            or _row(concurrent)["stable_candidate_hash"] != payload.stable_candidate_hash
        ):
            raise VavError(
                "DATA_BACKFILL_KEY_REUSED",
                "Backfill idempotency key conflicts with candidate set.",
                status_code=409,
            )
        row = concurrent
    await session.commit()
    return _row(row)


async def act_backfill(
    session: AsyncSession, actor_id: UUID, run_id: UUID, payload: BackfillAction
) -> dict[str, Any]:
    run = (
        await session.execute(
            text("SELECT * FROM data_backfill_runs WHERE id=:id FOR UPDATE"), {"id": run_id}
        )
    ).first()
    if not run:
        raise VavError("DATA_BACKFILL_RUN_NOT_FOUND", "Backfill run not found.", status_code=404)
    current = _row(run)
    transitions = {
        "approve": ({"created"}, "approved"),
        "start": ({"approved", "paused"}, "running"),
        "pause": ({"running"}, "paused"),
        "resume": ({"paused"}, "running"),
        "complete": ({"running"}, "completed"),
        "fail": ({"running", "paused"}, "failed"),
        "cancel": ({"created", "approved", "running", "paused"}, "cancelled"),
    }
    allowed, target = transitions[payload.action]
    if current["status"] not in allowed:
        raise VavError(
            "DATA_BACKFILL_TRANSITION_INVALID", "Backfill transition is invalid.", status_code=409
        )
    if payload.action == "approve" and current["requested_by"] == actor_id:
        raise VavError(
            "DATA_BACKFILL_INDEPENDENT_APPROVAL_REQUIRED",
            "Requester cannot approve production Backfill.",
            status_code=403,
        )
    if payload.processed_delta != payload.success_delta + payload.failure_delta:
        raise VavError(
            "DATA_BACKFILL_COUNTS_INVALID",
            "Processed delta must equal successful and failed deltas.",
            status_code=422,
        )
    completed = target in {"completed", "failed", "cancelled"}
    row = (
        await session.execute(
            text(
                "UPDATE data_backfill_runs SET status=:status,cursor_value=COALESCE(:cursor,cursor_value),processed_count=processed_count+:processed,success_count=success_count+:success,failure_count=failure_count+:failure,approved_by=CASE WHEN :approval THEN :actor ELSE approved_by END,started_at=CASE WHEN :running AND started_at IS NULL THEN now() ELSE started_at END,completed_at=CASE WHEN :completed THEN now() ELSE NULL END WHERE id=:id RETURNING *"
            ),
            {
                "status": target,
                "cursor": payload.cursor_value,
                "processed": payload.processed_delta,
                "success": payload.success_delta,
                "failure": payload.failure_delta,
                "approval": payload.action == "approve",
                "actor": actor_id,
                "running": target == "running",
                "completed": completed,
                "id": run_id,
            },
        )
    ).first()
    await _audit(
        session,
        actor_id,
        f"data.backfill.{payload.action}",
        "data_backfill_run",
        run_id,
        {"cursor": payload.cursor_value},
    )
    await session.commit()
    return _row(row)


async def request_projection_rebuild(
    session: AsyncSession, actor_id: UUID, payload: ProjectionRebuild
) -> dict[str, Any]:
    asset = (
        await session.execute(
            text("SELECT * FROM data_assets WHERE asset_code=:code AND lifecycle_status='active'"),
            {"code": payload.asset_code},
        )
    ).first()
    if not asset:
        raise VavError("DATA_ASSET_NOT_FOUND", "Data asset not found.", status_code=404)
    asset_row = _row(asset)
    if not asset_row["projection"] or not asset_row["rebuildable"]:
        raise VavError(
            "DATA_SOURCE_OF_TRUTH_REBUILD_FORBIDDEN",
            "Only rebuildable projections may be rebuilt.",
            status_code=409,
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO data_projection_rebuilds (asset_id,scope,scope_key,source_checkpoint,shadow_build,status,requested_by) VALUES (:asset,:scope,:key,CAST(:checkpoint AS jsonb),:shadow,'created',:actor) RETURNING *"
            ),
            {
                "asset": asset_row["id"],
                "scope": payload.scope,
                "key": payload.scope_key,
                "checkpoint": _json(payload.source_checkpoint),
                "shadow": payload.shadow_build,
                "actor": actor_id,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def create_erasure_plan(
    session: AsyncSession, actor_id: UUID, payload: ErasurePlanCreate
) -> dict[str, Any]:
    existing = (
        await session.execute(
            text(
                "SELECT * FROM data_erasure_plans WHERE privacy_request_id=:request AND lineage_release_version=:release"
            ),
            {"request": payload.privacy_request_id, "release": payload.lineage_release_version},
        )
    ).first()
    if existing:
        return _row(existing)
    assets = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT * FROM data_assets WHERE lifecycle_status='active' AND classification IN ('restricted','highly_restricted') ORDER BY asset_code"
                )
            )
        ).mappings()
    ]
    plan_id = await session.scalar(
        text(
            "INSERT INTO data_erasure_plans (privacy_request_id,subject_user_id,lineage_release_version,task_count) VALUES (:request,:subject,:release,:count) RETURNING id"
        ),
        {
            "request": payload.privacy_request_id,
            "subject": payload.subject_user_id,
            "release": payload.lineage_release_version,
            "count": len(assets),
        },
    )
    for asset in assets:
        action = _erasure_action_from_row(asset)
        await session.execute(
            text(
                "INSERT INTO data_erasure_tasks (plan_id,asset_id,action,idempotency_key) VALUES (:plan,:asset,:action,:key)"
            ),
            {
                "plan": plan_id,
                "asset": asset["id"],
                "action": action,
                "key": f"erasure:{plan_id}:{asset['id']}",
            },
        )
    await _audit(
        session,
        actor_id,
        "data.erasure.plan.created",
        "data_erasure_plan",
        plan_id,
        {"tasks": len(assets), "lineage_release": payload.lineage_release_version},
    )
    await session.commit()
    return _row(
        (
            await session.execute(
                text("SELECT * FROM data_erasure_plans WHERE id=:id"), {"id": plan_id}
            )
        ).first()
    )


def _erasure_action_from_row(asset: dict[str, Any]) -> str:
    asset_type = asset["asset_type"]
    if asset_type == "cache":
        return "invalidate_cache"
    if asset_type == "search_index":
        return "remove_search"
    if asset_type == "vector_index":
        return "remove_vector"
    if asset_type == "object_collection":
        return "remove_object"
    if asset_type == "file_export":
        return "remove_export"
    if asset["projection"]:
        return "remove_projection"
    if "anonymize" in asset["erasure_policy_code"] or "minimize" in asset["erasure_policy_code"]:
        return "anonymize"
    return "delete"


async def complete_erasure_task(
    session: AsyncSession, actor_id: UUID, task_id: UUID, payload: ErasureTaskComplete
) -> dict[str, Any]:
    task = (
        await session.execute(
            text("SELECT * FROM data_erasure_tasks WHERE id=:id FOR UPDATE"), {"id": task_id}
        )
    ).first()
    if not task:
        raise VavError("DATA_ERASURE_TASK_NOT_FOUND", "Erasure task not found.", status_code=404)
    if payload.status == "retained_legal_hold" and not payload.legal_hold_reference:
        raise VavError(
            "DATA_LEGAL_HOLD_REFERENCE_REQUIRED",
            "Legal hold reference is required.",
            status_code=422,
        )
    if payload.status == "completed" and payload.residual_count not in {0, None}:
        raise VavError(
            "DATA_ERASURE_RESIDUAL_REMAINS",
            "Completed erasure cannot retain residual data.",
            status_code=409,
        )
    current = _row(task)
    row = (
        await session.execute(
            text(
                "UPDATE data_erasure_tasks SET status=:status,execution_receipt=CAST(:receipt AS jsonb),residual_count=:residual,legal_hold_reference=:hold,completed_at=CASE WHEN :done THEN now() ELSE NULL END WHERE id=:id RETURNING *"
            ),
            {
                "status": payload.status,
                "receipt": _json(minimize_evidence(payload.execution_receipt)),
                "residual": payload.residual_count,
                "hold": payload.legal_hold_reference,
                "done": payload.status != "failed",
                "id": task_id,
            },
        )
    ).first()
    counts = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE status='completed') completed,count(*) FILTER (WHERE status='failed') failed,count(*) FILTER (WHERE status='retained_legal_hold') held,count(*) total FROM data_erasure_tasks WHERE plan_id=:plan"
            ),
            {"plan": current["plan_id"]},
        )
    ).first()
    summary = _row(counts)
    if summary["failed"]:
        plan_status = "verification_failed"
    elif summary["completed"] + summary["held"] == summary["total"]:
        plan_status = "completed" if summary["held"] == 0 else "blocked_legal_hold"
    else:
        plan_status = "running"
    await session.execute(
        text(
            "UPDATE data_erasure_plans SET completed_count=:completed,failed_count=:failed,legal_hold_count=:held,status=:status,completed_at=CASE WHEN :terminal THEN now() ELSE NULL END WHERE id=:plan"
        ),
        {
            "completed": summary["completed"],
            "failed": summary["failed"],
            "held": summary["held"],
            "status": plan_status,
            "terminal": plan_status in {"completed", "blocked_legal_hold"},
            "plan": current["plan_id"],
        },
    )
    await _audit(
        session,
        actor_id,
        "data.erasure.task.updated",
        "data_erasure_task",
        task_id,
        {"status": payload.status, "residual_count": payload.residual_count},
    )
    await session.commit()
    return _row(row)


async def issue_erasure_certificate(
    session: AsyncSession, actor_id: UUID, plan_id: UUID
) -> dict[str, Any]:
    plan = (
        await session.execute(
            text("SELECT * FROM data_erasure_plans WHERE id=:id FOR UPDATE"), {"id": plan_id}
        )
    ).first()
    if not plan:
        raise VavError("DATA_ERASURE_PLAN_NOT_FOUND", "Erasure plan not found.", status_code=404)
    current = _row(plan)
    if current["status"] not in {"completed", "blocked_legal_hold"} or current["failed_count"] > 0:
        raise VavError(
            "DATA_ERASURE_VERIFICATION_INCOMPLETE",
            "Erasure certificate requires complete residual verification.",
            status_code=409,
        )
    tasks = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT a.asset_code,t.action,t.status,t.residual_count,t.legal_hold_reference FROM data_erasure_tasks t JOIN data_assets a ON a.id=t.asset_id WHERE t.plan_id=:plan ORDER BY a.asset_code"
                ),
                {"plan": plan_id},
            )
        ).mappings()
    ]
    if any(
        item["status"] == "completed" and item["residual_count"] not in {0, None} for item in tasks
    ):
        raise VavError(
            "DATA_ERASURE_RESIDUAL_REMAINS",
            "Residual data prevents certification.",
            status_code=409,
        )
    summary = {
        "deleted_or_anonymized": sum(item["status"] == "completed" for item in tasks),
        "retained_legal_hold": sum(item["status"] == "retained_legal_hold" for item in tasks),
        "tasks": tasks,
    }
    row = (
        await session.execute(
            text(
                "INSERT INTO data_erasure_certificates (plan_id,subject_pseudonym,result_summary,evidence_checksum_sha256,issued_by) VALUES (:plan,:subject,CAST(:summary AS jsonb),:checksum,:actor) ON CONFLICT (plan_id) DO UPDATE SET result_summary=EXCLUDED.result_summary,evidence_checksum_sha256=EXCLUDED.evidence_checksum_sha256 RETURNING *"
            ),
            {
                "plan": plan_id,
                "subject": hashlib.sha256(str(current["subject_user_id"]).encode()).hexdigest(),
                "summary": _json(summary),
                "checksum": _hash(summary),
                "actor": actor_id,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def evaluate_integrity(
    session: AsyncSession, actor_id: UUID, payload: IntegrityEvaluate
) -> dict[str, Any]:
    counts = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM data_event_gaps WHERE severity='critical' AND status IN ('open','recovering')) gaps,(SELECT count(*) FROM data_dead_letters WHERE status IN ('open','quarantined')) dead_letters,(SELECT count(*) FROM data_reconciliation_differences WHERE severity='critical' AND status IN ('open','quarantined','repair_planned')) differences,(SELECT count(*) FROM data_erasure_plans WHERE status='verification_failed') erasure_failures"
            )
        )
    ).first()
    metrics = _row(counts)
    required = {
        "contracts",
        "lineage",
        "events",
        "quality",
        "reconciliation",
        "backfill",
        "erasure",
    }
    technical = (
        "pass"
        if required.issubset(payload.evidence_results)
        and all(payload.evidence_results[key] == "pass" for key in required)
        and all(int(value) == 0 for value in metrics.values())
        else "fail"
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO data_integrity_certifications (business_domain,git_commit,environment,evidence_results,open_critical_event_gaps,open_critical_dead_letters,open_critical_differences,erasure_failures,technical_status,production_status,evidence_checksum_sha256,evaluated_by) VALUES (:domain,:commit,:environment,CAST(:evidence AS jsonb),:gaps,:dead_letters,:differences,:erasure_failures,:technical,'not_certified',:checksum,:actor) ON CONFLICT (business_domain,git_commit,environment) DO UPDATE SET evidence_results=EXCLUDED.evidence_results,open_critical_event_gaps=EXCLUDED.open_critical_event_gaps,open_critical_dead_letters=EXCLUDED.open_critical_dead_letters,open_critical_differences=EXCLUDED.open_critical_differences,erasure_failures=EXCLUDED.erasure_failures,technical_status=EXCLUDED.technical_status,production_status='not_certified',evidence_checksum_sha256=EXCLUDED.evidence_checksum_sha256,evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now(),certified_by=NULL,certified_at=NULL RETURNING *"
            ),
            {
                "domain": payload.business_domain,
                "commit": payload.git_commit,
                "environment": payload.environment,
                "evidence": _json(payload.evidence_results),
                "gaps": metrics["gaps"],
                "dead_letters": metrics["dead_letters"],
                "differences": metrics["differences"],
                "erasure_failures": metrics["erasure_failures"],
                "technical": technical,
                "checksum": payload.evidence_checksum_sha256,
                "actor": actor_id,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def decide_integrity(
    session: AsyncSession, actor_id: UUID, certification_id: UUID, decision: str, reason: str
) -> dict[str, Any]:
    record = (
        await session.execute(
            text("SELECT * FROM data_integrity_certifications WHERE id=:id FOR UPDATE"),
            {"id": certification_id},
        )
    ).first()
    if not record:
        raise VavError(
            "DATA_CERTIFICATION_NOT_FOUND", "Data certification not found.", status_code=404
        )
    current = _row(record)
    if current["evaluated_by"] == actor_id:
        raise VavError(
            "DATA_INDEPENDENT_REVIEW_REQUIRED",
            "Evaluator cannot certify their own result.",
            status_code=403,
        )
    if decision == "certified" and (
        current["technical_status"] != "pass" or current["environment"] != "production"
    ):
        raise VavError(
            "DATA_CERTIFICATION_NOT_ELIGIBLE",
            "Certification requires passing production-bound evidence.",
            status_code=409,
        )
    row = (
        await session.execute(
            text(
                "UPDATE data_integrity_certifications SET production_status=:decision,certified_by=:actor,certified_at=now() WHERE id=:id RETURNING *"
            ),
            {"decision": decision, "actor": actor_id, "id": certification_id},
        )
    ).first()
    await _audit(
        session,
        actor_id,
        "data.certification.decided",
        "data_integrity_certification",
        certification_id,
        {"decision": decision, "reason": reason},
    )
    await session.commit()
    return _row(row)
