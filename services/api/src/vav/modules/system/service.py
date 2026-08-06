"""Auditable production operations control plane.

The control plane stores release identity and operational evidence, never secret values or backup
payloads. Infrastructure automation remains the authority for deployment and restoration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.system.schemas import (
    BackupRecordRequest,
    CapacityBaselineRecordRequest,
    DeploymentEvidenceRequest,
    FeatureFlagCreateRequest,
    FeatureFlagUpdateRequest,
    MaintenanceChangeRequest,
    ReleaseRecordCreateRequest,
    RestoreDrillRecordRequest,
)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


async def _audit(
    session: AsyncSession,
    *,
    actor_id: UUID,
    action: str,
    subject_type: str,
    subject_id: UUID | str | None,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events "
            "(actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,'admin',:action,:type,:subject,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "action": action,
            "type": subject_type,
            "subject": str(subject_id) if subject_id else None,
            "context": _json(context or {}),
        },
    )


async def system_status(session: AsyncSession, environment: str) -> dict[str, Any]:
    revision = await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    pending_outbox = await session.scalar(
        text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
    )
    failed_notifications = await session.scalar(
        text("SELECT count(*) FROM notification_dead_letters WHERE status='open'")
    )
    active_release = (
        (
            await session.execute(
                text(
                    "SELECT release_version,git_commit,database_revision,deployed_at "
                    "FROM system_release_records WHERE status='active' "
                    "ORDER BY deployed_at DESC NULLS LAST LIMIT 1"
                )
            )
        )
        .mappings()
        .first()
    )
    maintenance = (
        (
            await session.execute(
                text(
                    "SELECT status,write_scope,public_message,updated_at "
                    "FROM system_maintenance_states WHERE environment=:environment"
                ),
                {"environment": environment},
            )
        )
        .mappings()
        .first()
    )
    latest_backup = (
        (
            await session.execute(
                text(
                    "SELECT backup_type,status,verified_at,completed_at "
                    "FROM system_backup_records WHERE environment=:environment "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"environment": environment},
            )
        )
        .mappings()
        .first()
    )
    return {
        "environment": environment,
        "database_revision": revision,
        "release": dict(active_release) if active_release else None,
        "maintenance": dict(maintenance) if maintenance else {"status": "disabled"},
        "queues": {
            "outbox_pending": int(pending_outbox or 0),
            "dead_letters_open": int(failed_notifications or 0),
        },
        "backup": dict(latest_backup) if latest_backup else None,
        "providers": {
            "ai": "degraded_allowed",
            "email": "degraded_allowed",
            "payment": "transactional_fail_closed",
        },
    }


async def list_rows(session: AsyncSession, table: str) -> list[dict[str, Any]]:
    allowed = {
        "releases": "system_release_records",
        "jobs": "system_backfill_jobs",
        "feature-flags": "system_feature_flags",
        "maintenance": "system_maintenance_states",
        "backups": "system_backup_records",
        "restore-drills": "system_restore_drills",
        "capacity-baselines": "system_capacity_baselines",
    }
    resolved = allowed.get(table)
    if resolved is None:
        raise VavError("SYSTEM_VIEW_NOT_FOUND", "System view was not found.", status_code=404)
    rows = (
        await session.execute(text(f"SELECT * FROM {resolved} ORDER BY created_at DESC LIMIT 200"))
    ).mappings()
    return [dict(row) for row in rows]


async def create_feature_flag(
    session: AsyncSession, actor_id: UUID, payload: FeatureFlagCreateRequest
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO system_feature_flags "
                "(flag_code,status,targeting_policy,default_value,description,created_by) "
                "VALUES (:code,'draft',CAST(:targeting AS jsonb),CAST(:default AS jsonb),"
                ":description,:actor) RETURNING *"
            ),
            {
                "code": payload.flag_code,
                "targeting": _json(payload.targeting_policy),
                "default": _json(payload.default_value),
                "description": payload.description,
                "actor": actor_id,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action="system.feature_flag.updated",
        subject_type="system_feature_flag",
        subject_id=result["id"],
        context={"flag_code": payload.flag_code, "status": "draft"},
    )
    await session.commit()
    return result


async def update_feature_flag(
    session: AsyncSession,
    flag_id: UUID,
    actor_id: UUID,
    payload: FeatureFlagUpdateRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE system_feature_flags SET default_value=CAST(:default AS jsonb),"
                "targeting_policy=CAST(:targeting AS jsonb),"
                "description=:description,status='draft',approved_by=NULL,version=version+1,"
                "updated_at=now() WHERE id=:id AND version=:version RETURNING *"
            ),
            {
                "id": flag_id,
                "default": _json(payload.default_value),
                "targeting": _json(payload.targeting_policy),
                "description": payload.description,
                "version": payload.expected_version,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_FLAG_VERSION_CONFLICT", "Feature flag version changed.", status_code=409
        )
    await _audit(
        session,
        actor_id=actor_id,
        action="system.feature_flag.updated",
        subject_type="system_feature_flag",
        subject_id=flag_id,
        context={"version": payload.expected_version + 1},
    )
    await session.commit()
    return _mapping(row)


async def approve_feature_flag(
    session: AsyncSession, flag_id: UUID, approver_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE system_feature_flags SET status='approved',approved_by=:actor,"
                "updated_at=now() "
                "WHERE id=:id AND status='draft' AND created_by<>:actor RETURNING *"
            ),
            {"id": flag_id, "actor": approver_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_FLAG_APPROVAL_REJECTED",
            "Approval requires a draft flag and a different administrator.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id=approver_id,
        action="system.feature_flag.approved",
        subject_type="system_feature_flag",
        subject_id=flag_id,
    )
    await session.commit()
    return _mapping(row)


async def activate_feature_flag(
    session: AsyncSession, flag_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE system_feature_flags SET status='active',activated_at=now(),"
                "updated_at=now() "
                "WHERE id=:id AND status='approved' AND approved_by IS NOT NULL RETURNING *"
            ),
            {"id": flag_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_FLAG_NOT_APPROVED",
            "Only an independently approved flag can activate.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id=actor_id,
        action="system.feature_flag.activated",
        subject_type="system_feature_flag",
        subject_id=flag_id,
    )
    await session.commit()
    return _mapping(row)


async def create_release_record(
    session: AsyncSession, actor_id: UUID, payload: ReleaseRecordCreateRequest
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO system_release_records "
                "(release_version,git_commit,status,image_digests,database_revision,"
                "contract_checksums,configuration_fingerprint,evidence_manifest,created_by) "
                "VALUES (:version,:commit,'candidate',CAST(:images AS jsonb),:revision,"
                "CAST(:contracts AS jsonb),CAST(:config AS jsonb),CAST(:evidence AS jsonb),:actor) "
                "RETURNING *"
            ),
            {
                "version": payload.release_version,
                "commit": payload.git_commit,
                "images": _json(payload.image_digests),
                "revision": payload.database_revision,
                "contracts": _json(payload.contract_checksums),
                "config": _json(payload.configuration_fingerprint),
                "evidence": _json(payload.evidence_manifest),
                "actor": actor_id,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action="system.release.created",
        subject_type="system_release",
        subject_id=result["id"],
        context={"release_version": payload.release_version},
    )
    await session.commit()
    return result


async def set_maintenance(
    session: AsyncSession,
    *,
    environment: str,
    enabled: bool,
    actor_id: UUID,
    payload: MaintenanceChangeRequest,
) -> dict[str, Any]:
    approval_id = UUID(payload.approval_actor_id) if payload.approval_actor_id else None
    if environment in {"production", "dr"} and (approval_id is None or approval_id == actor_id):
        raise VavError(
            "SYSTEM_MAINTENANCE_APPROVAL_REQUIRED",
            "Production maintenance requires an independent approver.",
            status_code=409,
        )
    now = datetime.now(UTC)
    row = (
        await session.execute(
            text(
                "INSERT INTO system_maintenance_states "
                "(environment,status,write_scope,public_message,reason_code,changed_by,approved_by,"
                "enabled_at,disabled_at) VALUES "
                "(:environment,:status,CAST(:scope AS jsonb),:message,:reason,:actor,"
                ":approver,:enabled_at,:disabled_at) ON CONFLICT (environment) DO UPDATE SET "
                "status=excluded.status,write_scope=excluded.write_scope,public_message=excluded.public_message,"
                "reason_code=excluded.reason_code,changed_by=excluded.changed_by,approved_by=excluded.approved_by,"
                "enabled_at=excluded.enabled_at,disabled_at=excluded.disabled_at,"
                "updated_at=now() RETURNING *"
            ),
            {
                "environment": environment,
                "status": "enabled" if enabled else "disabled",
                "scope": _json(payload.write_scope),
                "message": payload.public_message,
                "reason": payload.reason_code,
                "actor": actor_id,
                "approver": approval_id,
                "enabled_at": now if enabled else None,
                "disabled_at": None if enabled else now,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action="system.maintenance.enabled" if enabled else "system.maintenance.disabled",
        subject_type="system_maintenance",
        subject_id=result["id"],
        context={"environment": environment, "reason_code": payload.reason_code},
    )
    await session.commit()
    return result


async def approve_release(
    session: AsyncSession, release_id: UUID, approver_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE system_release_records SET status='approved',approved_by=:actor,"
                "updated_at=now() WHERE id=:id AND status IN ('candidate','staging') "
                "AND created_by<>:actor RETURNING *"
            ),
            {"id": release_id, "actor": approver_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_RELEASE_APPROVAL_REJECTED",
            "Release approval requires an eligible candidate and a different administrator.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id=approver_id,
        action="system.release.approved",
        subject_type="system_release",
        subject_id=release_id,
    )
    await session.commit()
    return _mapping(row)


async def record_release_deployment(
    session: AsyncSession,
    *,
    release_id: UUID,
    actor_id: UUID,
    environment: str,
    payload: DeploymentEvidenceRequest,
) -> dict[str, Any]:
    if environment not in {"staging", "production"}:
        raise VavError(
            "SYSTEM_RELEASE_ENVIRONMENT_INVALID",
            "Invalid deployment environment.",
            status_code=422,
        )
    required_status = "candidate" if environment == "staging" else "approved"
    target_status = "staging" if environment == "staging" else "active"
    action = (
        "system.release.staging_deployed"
        if environment == "staging"
        else "system.release.production_deployed"
    )
    if environment == "production":
        await session.execute(
            text(
                "UPDATE system_release_records SET status='rolled_back',rolled_back_at=now(),"
                "updated_at=now() WHERE status='active' AND id<>:id"
            ),
            {"id": release_id},
        )
    row = (
        await session.execute(
            text(
                "UPDATE system_release_records SET status=:target,deployed_at=:completed,"
                "evidence_manifest=evidence_manifest || CAST(:evidence AS jsonb),updated_at=now() "
                "WHERE id=:id AND status=:required RETURNING *"
            ),
            {
                "id": release_id,
                "target": target_status,
                "required": required_status,
                "completed": payload.completed_at,
                "evidence": _json(
                    {
                        environment: {
                            "artifact_sha256": payload.artifact_sha256,
                            "completed_at": payload.completed_at.isoformat(),
                            **payload.evidence,
                        }
                    }
                ),
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_RELEASE_DEPLOYMENT_REJECTED",
            f"Release is not eligible for {environment} deployment recording.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id=actor_id,
        action=action,
        subject_type="system_release",
        subject_id=release_id,
        context={"artifact_sha256": payload.artifact_sha256},
    )
    await session.commit()
    return _mapping(row)


async def rollback_release(
    session: AsyncSession, release_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE system_release_records SET status='rolled_back',rolled_back_at=now(),"
                "updated_at=now() WHERE id=:id "
                "AND status IN ('staging','approved','active','failed') "
                "RETURNING *"
            ),
            {"id": release_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_RELEASE_ROLLBACK_REJECTED",
            "Release cannot be rolled back.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id=actor_id,
        action="system.release.rolled_back",
        subject_type="system_release",
        subject_id=release_id,
        context={"reason_code": reason_code},
    )
    await session.commit()
    return _mapping(row)


async def transition_backfill(
    session: AsyncSession, job_id: UUID, actor_id: UUID, operation: str, reason_code: str
) -> dict[str, Any]:
    transitions = {
        "retry": ("pending", ("failed", "paused")),
        "cancel": ("cancelled", ("pending", "running", "paused", "failed")),
    }
    if operation not in transitions:
        raise VavError("SYSTEM_JOB_OPERATION_INVALID", "Invalid job operation.", status_code=422)
    target, eligible = transitions[operation]
    row = (
        await session.execute(
            text(
                "UPDATE system_backfill_jobs SET status=:target,updated_at=now(),"
                "started_at=CASE WHEN :target='pending' THEN NULL ELSE started_at END "
                "WHERE id=:id AND status=ANY(:eligible) RETURNING *"
            ),
            {"id": job_id, "target": target, "eligible": list(eligible)},
        )
    ).first()
    if row is None:
        raise VavError(
            "SYSTEM_JOB_TRANSITION_REJECTED", "Job transition was rejected.", status_code=409
        )
    await _audit(
        session,
        actor_id=actor_id,
        action="system.job.retried" if operation == "retry" else "system.job.cancelled",
        subject_type="system_backfill_job",
        subject_id=job_id,
        context={"reason_code": reason_code},
    )
    await session.commit()
    return _mapping(row)


async def replay_dead_letter(
    session: AsyncSession, dead_letter_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    dead = (
        (
            await session.execute(
                text(
                    "SELECT * FROM notification_dead_letters "
                    "WHERE id=:id AND status='open' FOR UPDATE"
                ),
                {"id": dead_letter_id},
            )
        )
        .mappings()
        .first()
    )
    if dead is None:
        raise VavError("SYSTEM_DEAD_LETTER_NOT_OPEN", "Dead letter is not open.", status_code=409)
    source_type = str(dead["source_type"])
    if source_type == "notification_event":
        await session.execute(
            text(
                "UPDATE notification_events SET processing_status='received',processed_at=NULL,"
                "error_code=NULL WHERE id=:id"
            ),
            {"id": dead["source_id"]},
        )
    elif source_type == "notification_delivery":
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status='pending',next_attempt_at=now(),"
                "processing_lease_until=NULL,updated_at=now() WHERE id=:id"
            ),
            {"id": dead["source_id"]},
        )
    else:
        raise VavError(
            "SYSTEM_DEAD_LETTER_SOURCE_UNSUPPORTED",
            "This dead-letter source requires its owning module runbook.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE notification_dead_letters SET status='resolved',resolved_at=now(),"
            "resolution_reason=:reason WHERE id=:id"
        ),
        {"id": dead_letter_id, "reason": reason_code},
    )
    await _audit(
        session,
        actor_id=actor_id,
        action="system.dead_letter.replayed",
        subject_type="notification_dead_letter",
        subject_id=dead_letter_id,
        context={"reason_code": reason_code, "source_type": source_type},
    )
    await session.commit()
    return {"id": str(dead_letter_id), "status": "replayed", "source_type": source_type}


async def record_backup(
    session: AsyncSession, actor_id: UUID, payload: BackupRecordRequest
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO system_backup_records "
                "(backup_type,environment,status,started_at,completed_at,backup_reference_encrypted,"
                "checksum_manifest,source_release_version,source_database_revision,"
                "verified_at,expires_at) "
                "VALUES (:type,:environment,:status,:started,:completed,:reference,"
                "CAST(:checksums AS jsonb),"
                ":release,:revision,:verified,:expires) RETURNING *"
            ),
            {
                "type": payload.backup_type,
                "environment": payload.environment,
                "status": payload.status,
                "started": payload.started_at,
                "completed": payload.completed_at,
                "reference": payload.backup_reference_encrypted,
                "checksums": _json(payload.checksum_manifest),
                "release": payload.source_release_version,
                "revision": payload.source_database_revision,
                "verified": payload.verified_at,
                "expires": payload.expires_at,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action=f"system.backup.{payload.status}",
        subject_type="system_backup",
        subject_id=result["id"],
    )
    await session.commit()
    return result


async def record_restore_drill(
    session: AsyncSession, actor_id: UUID, payload: RestoreDrillRecordRequest
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO system_restore_drills "
                "(drill_code,environment,backup_record_id,status,target_release_version,"
                "target_database_revision,verification_manifest,failure_summary,"
                "started_at,completed_at) "
                "VALUES (:code,:environment,:backup,:status,:release,:revision,"
                "CAST(:verification AS jsonb),"
                ":failure,:started,:completed) RETURNING *"
            ),
            {
                "code": payload.drill_code,
                "environment": payload.environment,
                "backup": payload.backup_record_id,
                "status": payload.status,
                "release": payload.target_release_version,
                "revision": payload.target_database_revision,
                "verification": _json(payload.verification_manifest),
                "failure": payload.failure_summary,
                "started": payload.started_at,
                "completed": payload.completed_at,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action=f"system.restore_drill.{payload.status}",
        subject_type="system_restore_drill",
        subject_id=result["id"],
    )
    await session.commit()
    return result


async def record_capacity_baseline(
    session: AsyncSession, actor_id: UUID, payload: CapacityBaselineRecordRequest
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO system_capacity_baselines "
                "(release_version,environment,scenario_code,infrastructure_snapshot,load_snapshot,"
                "result_metrics,status,tested_at) VALUES "
                "(:release,:environment,:scenario,CAST(:infrastructure AS jsonb),"
                "CAST(:load AS jsonb),"
                "CAST(:metrics AS jsonb),:status,:tested) ON CONFLICT "
                "(release_version,environment,scenario_code) DO UPDATE SET "
                "infrastructure_snapshot=excluded.infrastructure_snapshot,"
                "load_snapshot=excluded.load_snapshot,result_metrics=excluded.result_metrics,"
                "status=excluded.status,tested_at=excluded.tested_at "
                "RETURNING *"
            ),
            {
                "release": payload.release_version,
                "environment": payload.environment,
                "scenario": payload.scenario_code,
                "infrastructure": _json(payload.infrastructure_snapshot),
                "load": _json(payload.load_snapshot),
                "metrics": _json(payload.result_metrics),
                "status": payload.status,
                "tested": payload.tested_at,
            },
        )
    ).first()
    assert row is not None
    result = _mapping(row)
    await _audit(
        session,
        actor_id=actor_id,
        action="system.performance_test.completed",
        subject_type="system_capacity_baseline",
        subject_id=result["id"],
        context={"status": payload.status},
    )
    await session.commit()
    return result
