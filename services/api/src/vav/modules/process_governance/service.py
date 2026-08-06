# ruff: noqa: E501

"""Durable process control-plane services.

The service records orchestration intent and typed command receipts. It never
updates a domain-owned table and therefore cannot manufacture domain success.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.process_governance.domain import (
    cancellation_outcome,
    ordered_event_disposition,
    simulate_faults,
    validate_resolution_command,
    verify_state_machine,
)
from vav.modules.process_governance.schemas import (
    CancellationCreate,
    CertificationEvaluate,
    CompensationRequest,
    EventReceive,
    InterventionResolve,
    ProcessStart,
    SimulationRequest,
    StepBegin,
    StepComplete,
)


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
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,'administrator',:action,:subject,:subject_id,CAST(:context AS jsonb),now())"
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
    counts = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM process_definitions WHERE status='active') active_definitions,"
                "(SELECT count(*) FROM state_machine_definitions WHERE verification_status='pass') verified_machines,"
                "(SELECT count(*) FROM process_instances WHERE status NOT IN ('succeeded','failed','cancelled','expired')) active_instances,"
                "(SELECT count(*) FROM process_stuck_findings WHERE status IN ('open','acknowledged')) open_stuck,"
                "(SELECT count(*) FROM process_compensation_executions WHERE status IN ('failed','manual_required')) compensation_failures,"
                "(SELECT count(*) FROM process_intervention_tasks WHERE status IN ('open','assigned')) interventions"
            )
        )
    ).first()
    return _row(counts) if counts else {}


async def list_section(session: AsyncSession, section: str) -> list[dict[str, Any]]:
    queries = {
        "definitions": "SELECT * FROM process_definitions ORDER BY process_code,version DESC LIMIT 250",
        "state-machines": "SELECT * FROM state_machine_definitions ORDER BY machine_code,version DESC LIMIT 250",
        "instances": "SELECT id,process_number,business_key,current_step_code,status,waiting_for,deadline_at,last_progress_at,failure_code FROM process_instances ORDER BY created_at DESC LIMIT 250",
        "sagas": "SELECT id,process_number,current_step_code,status,last_progress_at,deadline_at FROM process_instances WHERE status NOT IN ('succeeded','failed','cancelled','expired') ORDER BY last_progress_at LIMIT 250",
        "timeouts": "SELECT id,process_number,current_step_code,status,deadline_at,last_progress_at FROM process_instances WHERE deadline_at<=now() AND status NOT IN ('succeeded','failed','cancelled','expired') ORDER BY deadline_at LIMIT 250",
        "cancellations": "SELECT * FROM process_cancellation_requests ORDER BY created_at DESC LIMIT 250",
        "compensations": "SELECT * FROM process_compensation_executions ORDER BY created_at DESC LIMIT 250",
        "stuck": "SELECT * FROM process_stuck_findings ORDER BY detected_at DESC LIMIT 250",
        "interventions": "SELECT * FROM process_intervention_tasks ORDER BY due_at LIMIT 250",
        "simulations": "SELECT * FROM process_simulation_runs ORDER BY created_at DESC LIMIT 250",
        "certifications": "SELECT * FROM process_domain_certifications ORDER BY business_domain,evaluated_at DESC LIMIT 250",
        "release": "SELECT * FROM process_domain_certifications ORDER BY evaluated_at DESC LIMIT 250",
    }
    sql = queries.get(section)
    if not sql:
        raise VavError("PROCESS_SECTION_NOT_FOUND", "Process section not found.", status_code=404)
    return [dict(row) for row in (await session.execute(text(sql))).mappings()]


async def verify_machines(session: AsyncSession, actor_id: UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM state_machine_definitions WHERE status IN ('draft','active','invalid') ORDER BY machine_code"
            )
        )
    ).mappings()
    results: list[dict[str, Any]] = []
    for row in rows:
        machine = dict(row)
        manifest = {
            "initial": machine["initial_state"],
            "states": machine["state_manifest"],
            "transitions": machine["transition_manifest"],
        }
        findings = verify_state_machine(manifest)
        status = "pass" if not findings else "fail"
        lifecycle = "active" if not findings else "invalid"
        await session.execute(
            text(
                "UPDATE state_machine_definitions SET verification_status=:verification,verification_findings=CAST(:findings AS jsonb),status=:status,verified_at=now() WHERE id=:id"
            ),
            {
                "verification": status,
                "findings": _json(findings),
                "status": lifecycle,
                "id": machine["id"],
            },
        )
        results.append(
            {"machine_code": machine["machine_code"], "status": status, "findings": findings}
        )
    await _audit(
        session,
        actor_id,
        "process.state_machines.verified",
        "state_machine_registry",
        actor_id,
        {"machines": len(results), "failed": sum(item["status"] == "fail" for item in results)},
    )
    await session.commit()
    return {
        "results": results,
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
    }


async def start_process(
    session: AsyncSession, actor_id: UUID, payload: ProcessStart
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text("SELECT * FROM process_definitions WHERE process_code=:code AND status='active'"),
            {"code": payload.process_code},
        )
    ).first()
    if definition is None:
        raise VavError(
            "PROCESS_DEFINITION_NOT_ACTIVE", "No active process definition exists.", status_code=409
        )
    definition_row = _row(definition)
    context = dict(payload.context)
    if any(len(key) > 64 or len(value) > 256 for key, value in context.items()):
        raise VavError(
            "PROCESS_CONTEXT_INVALID",
            "Process context must contain bounded string values.",
            status_code=422,
        )
    first_step = await session.scalar(
        text(
            "SELECT step_code FROM process_step_definitions WHERE process_definition_id=:id ORDER BY sequence LIMIT 1"
        ),
        {"id": definition_row["id"]},
    )
    process_number = f"PRC-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(6).upper()}"
    deadline = datetime.now(UTC) + timedelta(seconds=definition_row["sla_seconds"])
    row = (
        await session.execute(
            text(
                "INSERT INTO process_instances (process_number,process_definition_id,business_key,actor_user_id,source_entity_type,source_entity_id,current_step_code,context_encrypted,context_hash,status,deadline_at) VALUES (:number,:definition,:business_key,:actor,:entity_type,:entity_id,:step,:context,:hash,'running',:deadline) ON CONFLICT (process_definition_id,business_key) DO NOTHING RETURNING *"
            ),
            {
                "number": process_number,
                "definition": definition_row["id"],
                "business_key": payload.business_key,
                "actor": actor_id,
                "entity_type": payload.source_entity_type,
                "entity_id": payload.source_entity_id,
                "step": first_step,
                "context": encrypt_private(context),
                "hash": _hash(context),
                "deadline": deadline,
            },
        )
    ).first()
    if row is None:
        existing = (
            await session.execute(
                text(
                    "SELECT * FROM process_instances WHERE process_definition_id=:definition AND business_key=:business_key"
                ),
                {"definition": definition_row["id"], "business_key": payload.business_key},
            )
        ).first()
        if existing is None:
            raise VavError(
                "PROCESS_START_CONFLICT", "Process could not be started.", status_code=409
            )
        return _safe_instance(_row(existing))
    result = _row(row)
    await _audit(
        session,
        actor_id,
        "process.instance.started",
        "process_instance",
        result["id"],
        {"process_code": payload.process_code},
    )
    await session.commit()
    return _safe_instance(result)


def _safe_instance(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("context_encrypted", None)
    return row


async def instance_detail(session: AsyncSession, instance_id: UUID) -> dict[str, Any]:
    instance = (
        await session.execute(
            text("SELECT * FROM process_instances WHERE id=:id"), {"id": instance_id}
        )
    ).first()
    if instance is None:
        raise VavError("PROCESS_INSTANCE_NOT_FOUND", "Process instance not found.", status_code=404)
    steps = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,step_definition_id,execution_number,idempotency_key,command_execution_id,status,attempt_count,expected_events,received_events,output_receipt,error_detail,next_retry_at,timeout_at,started_at,completed_at FROM process_step_executions WHERE process_instance_id=:id ORDER BY execution_number"
                ),
                {"id": instance_id},
            )
        ).mappings()
    ]
    compensations = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT * FROM process_compensation_executions WHERE process_instance_id=:id ORDER BY created_at"
                ),
                {"id": instance_id},
            )
        ).mappings()
    ]
    return {
        "instance": _safe_instance(_row(instance)),
        "steps": steps,
        "compensations": compensations,
    }


async def begin_step(
    session: AsyncSession, actor_id: UUID, instance_id: UUID, payload: StepBegin
) -> dict[str, Any]:
    instance = (
        await session.execute(
            text("SELECT * FROM process_instances WHERE id=:id FOR UPDATE"), {"id": instance_id}
        )
    ).first()
    if instance is None:
        raise VavError("PROCESS_INSTANCE_NOT_FOUND", "Process instance not found.", status_code=404)
    current = _row(instance)
    if current["status"] not in {
        "running",
        "waiting_event",
        "waiting_platform",
        "waiting_provider",
    }:
        raise VavError(
            "PROCESS_STEP_NOT_ALLOWED",
            "Process is not executable in its current state.",
            status_code=409,
        )
    if current["current_step_code"] != payload.step_code:
        raise VavError(
            "PROCESS_STEP_OUT_OF_ORDER",
            "Only the current registered step can execute.",
            status_code=409,
        )
    step = (
        await session.execute(
            text(
                "SELECT * FROM process_step_definitions WHERE process_definition_id=:definition AND step_code=:code"
            ),
            {"definition": current["process_definition_id"], "code": payload.step_code},
        )
    ).first()
    if step is None:
        raise VavError(
            "PROCESS_STEP_NOT_REGISTERED", "The step is not registered.", status_code=409
        )
    step_row = _row(step)
    request_hash = _hash(payload.input)
    existing = (
        await session.execute(
            text(
                "SELECT * FROM process_step_executions WHERE process_instance_id=:instance AND idempotency_key=:key"
            ),
            {"instance": instance_id, "key": payload.idempotency_key},
        )
    ).first()
    if existing:
        existing_row = _row(existing)
        if existing_row["request_hash"] != request_hash:
            raise VavError(
                "PROCESS_IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was reused with different input.",
                status_code=409,
            )
        return existing_row
    execution_number = int(
        await session.scalar(
            text(
                "SELECT COALESCE(max(execution_number),0)+1 FROM process_step_executions WHERE process_instance_id=:id"
            ),
            {"id": instance_id},
        )
        or 1
    )
    status = (
        "waiting_event"
        if step_row["step_type"] in {"event_wait", "human_task", "provider_call", "timer"}
        else "running"
    )
    timeout_at = (
        datetime.now(UTC) + timedelta(seconds=step_row["timeout_seconds"])
        if step_row["timeout_seconds"]
        else None
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO process_step_executions (process_instance_id,step_definition_id,execution_number,idempotency_key,request_hash,status,attempt_count,expected_events,timeout_at,started_at) VALUES (:instance,:step,:number,:key,:hash,:status,1,:events,:timeout,now()) RETURNING *"
            ),
            {
                "instance": instance_id,
                "step": step_row["id"],
                "number": execution_number,
                "key": payload.idempotency_key,
                "hash": request_hash,
                "status": status,
                "events": _json(step_row["expected_event_codes"]),
                "timeout": timeout_at,
            },
        )
    ).first()
    await session.execute(
        text(
            "UPDATE process_instances SET status=:status,waiting_for=:waiting,last_progress_at=now(),lock_version=lock_version+1 WHERE id=:id"
        ),
        {
            "status": status,
            "waiting": step_row["step_type"] if status == "waiting_event" else None,
            "id": instance_id,
        },
    )
    result = _row(row)
    await _audit(
        session,
        actor_id,
        "process.step.started",
        "process_step_execution",
        result["id"],
        {"step_code": payload.step_code},
    )
    await session.commit()
    return result


async def complete_step(
    session: AsyncSession, actor_id: UUID, instance_id: UUID, payload: StepComplete
) -> dict[str, Any]:
    execution = (
        await session.execute(
            text(
                "SELECT e.*,s.sequence,s.process_definition_id,s.step_code FROM process_step_executions e JOIN process_step_definitions s ON s.id=e.step_definition_id WHERE e.process_instance_id=:instance AND e.idempotency_key=:key FOR UPDATE OF e"
            ),
            {"instance": instance_id, "key": payload.idempotency_key},
        )
    ).first()
    if execution is None:
        raise VavError(
            "PROCESS_STEP_EXECUTION_NOT_FOUND", "Step execution not found.", status_code=404
        )
    execution_row = _row(execution)
    if execution_row["status"] == "succeeded":
        return execution_row
    if execution_row["status"] not in {"running", "waiting_event"}:
        raise VavError(
            "PROCESS_STEP_COMPLETION_INVALID",
            "Step cannot be completed from its current status.",
            status_code=409,
        )
    next_step = (
        await session.execute(
            text(
                "SELECT step_code FROM process_step_definitions WHERE process_definition_id=:definition AND sequence>:sequence ORDER BY sequence LIMIT 1"
            ),
            {
                "definition": execution_row["process_definition_id"],
                "sequence": execution_row["sequence"],
            },
        )
    ).scalar_one_or_none()
    await session.execute(
        text(
            "UPDATE process_step_executions SET status='succeeded',output_receipt=CAST(:receipt AS jsonb),completed_at=now() WHERE id=:id"
        ),
        {"receipt": _json(payload.receipt), "id": execution_row["id"]},
    )
    if next_step:
        await session.execute(
            text(
                "UPDATE process_instances SET status='running',current_step_code=:step,waiting_for=NULL,last_progress_at=now(),lock_version=lock_version+1 WHERE id=:id AND status NOT IN ('cancelled','expired','safety_frozen')"
            ),
            {"step": next_step, "id": instance_id},
        )
    else:
        await session.execute(
            text(
                "UPDATE process_instances SET status='succeeded',current_step_code=NULL,waiting_for=NULL,final_outcome='success',last_progress_at=now(),completed_at=now(),lock_version=lock_version+1 WHERE id=:id AND status NOT IN ('cancelled','expired','safety_frozen')"
            ),
            {"id": instance_id},
        )
    await _audit(
        session,
        actor_id,
        "process.step.completed",
        "process_step_execution",
        execution_row["id"],
        {"receipt_hash": _hash(payload.receipt)},
    )
    await session.commit()
    return await instance_detail(session, instance_id)


async def receive_event(
    session: AsyncSession, instance_id: UUID, payload: EventReceive
) -> dict[str, Any]:
    duplicate = (
        await session.execute(
            text(
                "SELECT * FROM process_event_inbox WHERE consumer_code=:consumer AND event_id=:event"
            ),
            {"consumer": payload.consumer_code, "event": payload.event_id},
        )
    ).first()
    if duplicate:
        duplicate_row = _row(duplicate)
        duplicate_row["duplicate"] = True
        return duplicate_row
    current_version = int(
        await session.scalar(
            text(
                "SELECT COALESCE(max(aggregate_version),0) FROM process_event_inbox WHERE consumer_code=:consumer AND aggregate_type=:aggregate_type AND aggregate_id=:aggregate_id AND disposition='accepted'"
            ),
            {
                "consumer": payload.consumer_code,
                "aggregate_type": payload.aggregate_type,
                "aggregate_id": payload.aggregate_id,
            },
        )
        or 0
    )
    disposition = ordered_event_disposition(
        current_version=current_version, event_version=payload.aggregate_version
    )
    inserted = (
        await session.execute(
            text(
                "INSERT INTO process_event_inbox (consumer_code,event_id,event_code,aggregate_type,aggregate_id,aggregate_version,payload_hash,disposition,process_instance_id) VALUES (:consumer,:event,:event_code,:aggregate_type,:aggregate_id,:version,:hash,:disposition,:instance) RETURNING *"
            ),
            {
                "consumer": payload.consumer_code,
                "event": payload.event_id,
                "event_code": payload.event_code,
                "aggregate_type": payload.aggregate_type,
                "aggregate_id": payload.aggregate_id,
                "version": payload.aggregate_version,
                "hash": payload.payload_hash,
                "disposition": disposition,
                "instance": instance_id,
            },
        )
    ).first()
    await session.commit()
    result = _row(inserted)
    result["duplicate"] = False
    return result


async def cancel(
    session: AsyncSession, actor_id: UUID, instance_id: UUID, payload: CancellationCreate
) -> dict[str, Any]:
    existing = (
        await session.execute(
            text("SELECT * FROM process_cancellation_requests WHERE cancellation_key=:key"),
            {"key": payload.cancellation_key},
        )
    ).first()
    if existing:
        return _row(existing)
    instance = (
        await session.execute(
            text("SELECT * FROM process_instances WHERE id=:id FOR UPDATE"), {"id": instance_id}
        )
    ).first()
    if instance is None:
        raise VavError("PROCESS_INSTANCE_NOT_FOUND", "Process instance not found.", status_code=404)
    current = _row(instance)
    if current["lock_version"] != payload.expected_lock_version:
        raise VavError(
            "PROCESS_CONCURRENCY_CONFLICT",
            "Process version changed; reload before cancelling.",
            status_code=409,
        )
    outcome = cancellation_outcome(status=current["status"], request_type=payload.request_type)
    accepted = outcome in {"cancelling", "safety_frozen"}
    row = (
        await session.execute(
            text(
                "INSERT INTO process_cancellation_requests (process_instance_id,cancellation_key,request_type,reason_code,requested_by,expected_lock_version,status,rejection_code,completed_at) VALUES (:instance,:key,:type,:reason,:actor,:version,:status,:rejection,CASE WHEN :accepted THEN now() ELSE NULL END) RETURNING *"
            ),
            {
                "instance": instance_id,
                "key": payload.cancellation_key,
                "type": payload.request_type,
                "reason": payload.reason_code,
                "actor": actor_id,
                "version": payload.expected_lock_version,
                "status": "completed" if accepted else "rejected",
                "rejection": None if accepted else outcome,
                "accepted": accepted,
            },
        )
    ).first()
    if accepted:
        final_status = "safety_frozen" if outcome == "safety_frozen" else "cancelled"
        if final_status == "cancelled":
            await session.execute(
                text(
                    "UPDATE process_instances SET status='cancelled',final_outcome='cancelled',waiting_for=NULL,last_progress_at=now(),completed_at=now(),lock_version=lock_version+1 WHERE id=:id"
                ),
                {"id": instance_id},
            )
        else:
            await session.execute(
                text(
                    "UPDATE process_instances SET status='safety_frozen',final_outcome='safety_frozen',waiting_for=NULL,last_progress_at=now(),completed_at=NULL,lock_version=lock_version+1 WHERE id=:id"
                ),
                {"id": instance_id},
            )
    await _audit(
        session,
        actor_id,
        "process.cancellation.requested",
        "process_instance",
        instance_id,
        {"request_type": payload.request_type, "outcome": outcome},
    )
    await session.commit()
    return _row(row)


async def request_compensation(
    session: AsyncSession, actor_id: UUID, instance_id: UUID, payload: CompensationRequest
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM process_compensation_definitions WHERE compensation_code=:code AND active=true"
            ),
            {"code": payload.compensation_code},
        )
    ).first()
    if definition is None:
        raise VavError(
            "PROCESS_COMPENSATION_NOT_REGISTERED",
            "Compensation command is not registered.",
            status_code=409,
        )
    definition_row = _row(definition)
    existing = (
        await session.execute(
            text("SELECT * FROM process_compensation_executions WHERE idempotency_key=:key"),
            {"key": payload.idempotency_key},
        )
    ).first()
    if existing:
        return _row(existing)
    step = (
        await session.execute(
            text(
                "SELECT * FROM process_step_executions WHERE id=:step AND process_instance_id=:instance AND status='succeeded'"
            ),
            {"step": payload.step_execution_id, "instance": instance_id},
        )
    ).first()
    if step is None:
        raise VavError(
            "PROCESS_COMPENSATION_SOURCE_INVALID",
            "Only a completed step can be compensated.",
            status_code=409,
        )
    status = "pending" if definition_row["human_approval_required"] else "approved"
    row = (
        await session.execute(
            text(
                "INSERT INTO process_compensation_executions (process_instance_id,step_execution_id,compensation_definition_id,idempotency_key,status,requested_by) VALUES (:instance,:step,:definition,:key,:status,:actor) RETURNING *"
            ),
            {
                "instance": instance_id,
                "step": payload.step_execution_id,
                "definition": definition_row["id"],
                "key": payload.idempotency_key,
                "status": status,
                "actor": actor_id,
            },
        )
    ).first()
    await session.execute(
        text(
            "UPDATE process_instances SET status='compensating',last_progress_at=now(),lock_version=lock_version+1 WHERE id=:id"
        ),
        {"id": instance_id},
    )
    result = _row(row)
    await _audit(
        session,
        actor_id,
        "process.compensation.requested",
        "process_compensation",
        result["id"],
        {"command": definition_row["target_command_code"]},
    )
    await session.commit()
    return result


async def scan_stuck(session: AsyncSession, actor_id: UUID) -> dict[str, Any]:
    candidates = (
        await session.execute(
            text(
                "SELECT i.*,d.criticality,d.owner_team,d.stuck_policy FROM process_instances i JOIN process_definitions d ON d.id=i.process_definition_id WHERE i.status NOT IN ('succeeded','failed','cancelled','expired') AND (i.deadline_at<now() OR i.last_progress_at < now() - make_interval(secs => GREATEST(60,LEAST(d.sla_seconds,(d.stuck_policy->>'progress_sla_seconds')::int)))) FOR UPDATE OF i"
            )
        )
    ).mappings()
    created = 0
    for row in candidates:
        item = dict(row)
        finding_type = (
            "process_sla_exceeded"
            if item["deadline_at"] < datetime.now(UTC)
            else "state_sla_exceeded"
        )
        code = f"{item['id']}:{finding_type}"
        finding = (
            await session.execute(
                text(
                    "INSERT INTO process_stuck_findings (finding_code,process_instance_id,finding_type,severity,evidence) VALUES (:code,:instance,:type,:severity,CAST(:evidence AS jsonb)) ON CONFLICT (finding_code) DO NOTHING RETURNING id"
                ),
                {
                    "code": code,
                    "instance": item["id"],
                    "type": finding_type,
                    "severity": item["criticality"],
                    "evidence": _json(
                        {
                            "last_progress_at": item["last_progress_at"],
                            "deadline_at": item["deadline_at"],
                        }
                    ),
                },
            )
        ).scalar_one_or_none()
        if finding:
            created += 1
            await session.execute(
                text(
                    "INSERT INTO process_intervention_tasks (process_instance_id,stuck_finding_id,priority,allowed_resolution_commands,due_at) VALUES (:instance,:finding,:priority,CAST(:commands AS jsonb),now()+interval '4 hours')"
                ),
                {
                    "instance": item["id"],
                    "finding": finding,
                    "priority": item["criticality"],
                    "commands": _json(
                        item["stuck_policy"].get(
                            "allowed_recovery_commands",
                            ["process.retry_registered_step", "process.rebuild_projection"],
                        )
                    ),
                },
            )
            await session.execute(
                text(
                    "UPDATE process_instances SET status='manual_intervention',waiting_for='operator' WHERE id=:id AND status<>'safety_frozen'"
                ),
                {"id": item["id"]},
            )
    await _audit(
        session, actor_id, "process.stuck.scan", "process_registry", actor_id, {"created": created}
    )
    await session.commit()
    return {"created": created}


async def resolve_intervention(
    session: AsyncSession, actor_id: UUID, task_id: UUID, payload: InterventionResolve
) -> dict[str, Any]:
    task = (
        await session.execute(
            text(
                "SELECT * FROM process_intervention_tasks WHERE id=:id AND status IN ('open','assigned') FOR UPDATE"
            ),
            {"id": task_id},
        )
    ).first()
    if task is None:
        raise VavError(
            "PROCESS_INTERVENTION_NOT_OPEN", "Intervention task is not open.", status_code=409
        )
    current = _row(task)
    try:
        validate_resolution_command(
            payload.resolution_command, set(current["allowed_resolution_commands"])
        )
    except ValueError as exc:
        raise VavError("PROCESS_UNREGISTERED_REPAIR_REJECTED", str(exc), status_code=403) from exc
    row = (
        await session.execute(
            text(
                "UPDATE process_intervention_tasks SET status='resolved',resolution_command=:command,resolution_receipt=CAST(:receipt AS jsonb),resolved_by=:actor,resolved_at=now() WHERE id=:id RETURNING *"
            ),
            {
                "command": payload.resolution_command,
                "receipt": _json(payload.receipt),
                "actor": actor_id,
                "id": task_id,
            },
        )
    ).first()
    await session.execute(
        text("UPDATE process_stuck_findings SET status='resolved',resolved_at=now() WHERE id=:id"),
        {"id": current["stuck_finding_id"]},
    )
    await _audit(
        session,
        actor_id,
        "process.intervention.resolved",
        "process_intervention",
        task_id,
        {"command": payload.resolution_command, "receipt_hash": _hash(payload.receipt)},
    )
    await session.commit()
    return _row(row)


async def run_simulation(
    session: AsyncSession,
    actor_id: UUID,
    payload: SimulationRequest,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    scenario = next((item for item in scenarios if item["code"] == payload.scenario_code), None)
    if not scenario:
        raise VavError(
            "PROCESS_SIMULATION_NOT_FOUND",
            "Simulation scenario is not registered.",
            status_code=404,
        )
    result = simulate_faults(scenario["process"], scenario["faults"], scenario["expected"])
    row = (
        await session.execute(
            text(
                "INSERT INTO process_simulation_runs (scenario_code,process_code,synthetic_seed,virtual_clock_start,fault_manifest,expected_outcome,observed_outcome,invariant_results,status,run_by) VALUES (:scenario,:process,:seed,now(),CAST(:faults AS jsonb),CAST(:expected AS jsonb),CAST(:observed AS jsonb),CAST(:invariants AS jsonb),:status,:actor) RETURNING *"
            ),
            {
                "scenario": scenario["code"],
                "process": scenario["process"],
                "seed": payload.synthetic_seed,
                "faults": _json(scenario["faults"]),
                "expected": _json({"outcome": scenario["expected"]}),
                "observed": _json({"outcome": result.outcome}),
                "invariants": _json(result.invariants),
                "status": result.status,
                "actor": actor_id,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def evaluate_certification(
    session: AsyncSession, actor_id: UUID, payload: CertificationEvaluate
) -> dict[str, Any]:
    required_paths = {
        "normal",
        "failure",
        "timeout",
        "cancellation",
        "compensation",
        "concurrency",
        "manual_recovery",
    }
    open_critical = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM process_stuck_findings f JOIN process_instances i ON i.id=f.process_instance_id JOIN process_definitions d ON d.id=i.process_definition_id WHERE d.business_domain=:domain AND f.severity='critical' AND f.status IN ('open','acknowledged')"
            ),
            {"domain": payload.business_domain},
        )
        or 0
    )
    technical = (
        "pass"
        if required_paths.issubset(payload.path_results)
        and all(payload.path_results[path] == "pass" for path in required_paths)
        and open_critical == 0
        else "fail"
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO process_domain_certifications (business_domain,git_commit,environment,path_results,unresolved_critical_stuck,technical_status,production_status,evidence_checksum_sha256,evaluated_by) VALUES (:domain,:commit,:environment,CAST(:paths AS jsonb),:stuck,:technical,'not_certified',:evidence,:actor) ON CONFLICT (business_domain,git_commit,environment) DO UPDATE SET path_results=EXCLUDED.path_results,unresolved_critical_stuck=EXCLUDED.unresolved_critical_stuck,technical_status=EXCLUDED.technical_status,production_status='not_certified',evidence_checksum_sha256=EXCLUDED.evidence_checksum_sha256,evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now(),certified_by=NULL,certified_at=NULL RETURNING *"
            ),
            {
                "domain": payload.business_domain,
                "commit": payload.git_commit,
                "environment": payload.environment,
                "paths": _json(payload.path_results),
                "stuck": open_critical,
                "technical": technical,
                "evidence": payload.evidence_checksum_sha256,
                "actor": actor_id,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def decide_certification(
    session: AsyncSession, actor_id: UUID, certification_id: UUID, decision: str, reason: str
) -> dict[str, Any]:
    certification = (
        await session.execute(
            text("SELECT * FROM process_domain_certifications WHERE id=:id FOR UPDATE"),
            {"id": certification_id},
        )
    ).first()
    if certification is None:
        raise VavError(
            "PROCESS_CERTIFICATION_NOT_FOUND", "Certification not found.", status_code=404
        )
    current = _row(certification)
    if current["evaluated_by"] == actor_id:
        raise VavError(
            "PROCESS_INDEPENDENT_REVIEW_REQUIRED",
            "Evaluator cannot certify their own result.",
            status_code=403,
        )
    if decision == "certified" and (
        current["technical_status"] != "pass" or current["environment"] != "production"
    ):
        raise VavError(
            "PROCESS_CERTIFICATION_NOT_ELIGIBLE",
            "Production certification requires passing production-bound evidence.",
            status_code=409,
        )
    row = (
        await session.execute(
            text(
                "UPDATE process_domain_certifications SET production_status=:decision,certified_by=:actor,certified_at=now() WHERE id=:id RETURNING *"
            ),
            {"decision": decision, "actor": actor_id, "id": certification_id},
        )
    ).first()
    await _audit(
        session,
        actor_id,
        "process.certification.decided",
        "process_certification",
        certification_id,
        {"decision": decision, "reason": reason},
    )
    await session.commit()
    return _row(row)
