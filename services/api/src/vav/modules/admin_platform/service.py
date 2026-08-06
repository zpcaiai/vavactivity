# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.admin_platform.domain import (
    mask_value,
    minimize,
    stable_hash,
    step_up_current,
    validate_query,
)
from vav.modules.admin_platform.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    BulkPlan,
    CertificationEvaluate,
    ConfigurationAction,
    ConfigurationCreate,
    MaskRequest,
    RevealCreate,
    SavedViewCreate,
)
from vav.modules.privacy.crypto import encrypt_private


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _row(value: Any) -> dict[str, Any]:
    return dict(value._mapping)


async def _audit(
    session: AsyncSession,
    actor: UUID,
    action: str,
    subject: str,
    subject_id: UUID,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) VALUES (:actor,'administrator',:action,:subject,:id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor),
            "action": action,
            "subject": subject,
            "id": str(subject_id),
            "context": _json(minimize(context or {})),
        },
    )


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM admin_capability_definitions WHERE lifecycle_status='active') capabilities,(SELECT count(*) FROM admin_work_items WHERE status NOT IN ('resolved','cancelled','expired','invalidated')) open_work_items,(SELECT count(*) FROM admin_work_items WHERE due_at<now() AND status NOT IN ('resolved','cancelled','expired','invalidated')) overdue,(SELECT count(*) FROM admin_approval_requests WHERE status IN ('submitted','in_review')) pending_approvals,(SELECT count(*) FROM admin_exception_items WHERE status<>'resolved') open_exceptions,(SELECT count(*) FROM admin_bulk_jobs WHERE status='partially_failed') partial_bulk_jobs,(SELECT count(*) FROM admin_sensitive_reveal_grants WHERE status='active' AND expires_at>now()) active_reveals,(SELECT count(*) FROM admin_domain_certifications WHERE status<>'certified') uncertified_domains"
            )
        )
    ).first()
    return _row(row) if row else {}


async def list_section(session: AsyncSession, section: str) -> list[dict[str, Any]]:
    queries = {
        "capabilities": "SELECT * FROM admin_capability_definitions ORDER BY owning_module,capability_code LIMIT 500",
        "work-items": "SELECT * FROM admin_work_items ORDER BY priority DESC,due_at NULLS LAST,created_at LIMIT 500",
        "saved-views": "SELECT * FROM admin_saved_views ORDER BY updated_at DESC LIMIT 500",
        "bulk-jobs": "SELECT j.*,d.operation_code FROM admin_bulk_jobs j JOIN admin_bulk_operation_definitions d ON d.id=j.operation_definition_id ORDER BY j.created_at DESC LIMIT 500",
        "approvals": "SELECT * FROM admin_approval_requests ORDER BY created_at DESC LIMIT 500",
        "exceptions": "SELECT * FROM admin_exception_items ORDER BY severity DESC,detected_at LIMIT 500",
        "configurations": "SELECT v.*,n.namespace_code FROM admin_configuration_versions v JOIN admin_configuration_namespaces n ON n.id=v.namespace_id ORDER BY v.created_at DESC LIMIT 500",
        "field-access": "SELECT * FROM admin_field_access_policies ORDER BY asset_code,field_path LIMIT 500",
        "reveal-history": "SELECT id,admin_user_id,policy_id,entity_type,entity_id,purpose_code,status,issued_at,expires_at,revoked_at FROM admin_sensitive_reveal_grants ORDER BY issued_at DESC LIMIT 500",
        "certifications": "SELECT * FROM admin_domain_certifications ORDER BY business_domain,evaluated_at DESC LIMIT 500",
        "audit": "SELECT * FROM admin_operation_receipts ORDER BY executed_at DESC LIMIT 500",
        "releases": "SELECT * FROM admin_domain_certifications ORDER BY release_version DESC,business_domain LIMIT 500",
    }
    if section not in queries:
        raise VavError(
            "ADMIN_SECTION_NOT_FOUND", "Administration section not found.", status_code=404
        )
    return [dict(row) for row in (await session.execute(text(queries[section]))).mappings()]


async def sync_exception_work_items(session: AsyncSession) -> dict[str, int]:
    process_rows = list(
        (
            await session.execute(
                text(
                    "SELECT f.id,f.finding_code,f.finding_type,f.severity,f.detected_at,t.allowed_resolution_commands FROM process_stuck_findings f LEFT JOIN process_intervention_tasks t ON t.stuck_finding_id=f.id WHERE f.status IN ('open','acknowledged')"
                )
            )
        ).mappings()
    )
    data_rows = list(
        (
            await session.execute(
                text(
                    "SELECT d.id,('data-difference-'||d.id::text) code,d.category type,d.severity,r.started_at detected,def.repair_command_code repair FROM data_reconciliation_differences d JOIN data_reconciliation_runs r ON r.id=d.run_id JOIN data_reconciliation_definitions def ON def.id=r.definition_id WHERE d.status IN ('open','quarantined','repair_planned')"
                )
            )
        ).mappings()
    )
    created = 0
    for item in process_rows:
        result = await session.execute(
            text(
                "INSERT INTO admin_exception_items (exception_code,exception_type,source_module,source_reference_type,source_reference_id,severity,safe_summary,evidence_reference,allowed_diagnostic_codes,allowed_repair_codes,assigned_team,detected_at) VALUES (:code,:type,'process','process_stuck_finding',:id,:severity,'Process requires controlled intervention','{}'::jsonb,'[\"process.inspect_timeline\"]'::jsonb,CAST(:repairs AS jsonb),'platform-operations',:detected) ON CONFLICT (exception_code) DO NOTHING RETURNING id"
            ),
            {
                "code": item["finding_code"],
                "type": item["finding_type"],
                "id": item["id"],
                "severity": item["severity"],
                "repairs": _json(item["allowed_resolution_commands"] or []),
                "detected": item["detected_at"],
            },
        )
        created += int(result.scalar_one_or_none() is not None)
    for item in data_rows:
        result = await session.execute(
            text(
                "INSERT INTO admin_exception_items (exception_code,exception_type,source_module,source_reference_type,source_reference_id,severity,safe_summary,evidence_reference,allowed_diagnostic_codes,allowed_repair_codes,assigned_team,detected_at) VALUES (:code,:type,'data_governance','reconciliation_difference',:id,:severity,'Authoritative and derived data differ','{}'::jsonb,'[\"data.reconciliation.inspect\"]'::jsonb,CAST(:repairs AS jsonb),'data-operations',:detected) ON CONFLICT (exception_code) DO NOTHING RETURNING id"
            ),
            {
                "code": item["code"],
                "type": item["type"],
                "id": item["id"],
                "severity": item["severity"],
                "repairs": _json([item["repair"]] if item["repair"] else []),
                "detected": item["detected"],
            },
        )
        created += int(result.scalar_one_or_none() is not None)
    exceptions = list(
        (
            await session.execute(
                text("SELECT * FROM admin_exception_items WHERE status<>'resolved'")
            )
        ).mappings()
    )
    for item in exceptions:
        await session.execute(
            text(
                "INSERT INTO admin_work_items (work_item_code,work_item_type,source_module,source_entity_type,source_entity_id,priority,title_snapshot,safe_summary,assigned_team,required_capability_code,action_route_code,deduplication_key,due_at) VALUES (:code,'exception',:module,:type,:id,:priority,'Administration exception',:summary,:team,'ADMIN-DATA-DIFFERENCE-REPAIR','ROUTE-ADMIN-EXCEPTION',:dedupe,now()+interval '4 hours') ON CONFLICT (deduplication_key) DO NOTHING"
            ),
            {
                "code": f"work-{item['exception_code']}",
                "module": item["source_module"],
                "type": item["source_reference_type"],
                "id": item["source_reference_id"],
                "priority": "critical" if item["severity"] == "critical" else "high",
                "summary": item["safe_summary"],
                "team": item["assigned_team"],
                "dedupe": f"exception:{item['id']}",
            },
        )
    await session.commit()
    return {
        "sources": len(process_rows) + len(data_rows),
        "created": created,
        "projected": len(exceptions),
    }


async def assign_work_item(
    session: AsyncSession, actor: UUID, item_id: UUID, assignee: UUID | None
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE admin_work_items SET assigned_to=:assignee,status=CASE WHEN :assignee IS NULL THEN 'available' ELSE 'assigned' END WHERE id=:id AND status IN ('available','assigned','in_progress') RETURNING *"
            ),
            {"assignee": assignee, "id": item_id},
        )
    ).first()
    if not row:
        raise VavError(
            "ADMIN_WORK_ITEM_NOT_ASSIGNABLE", "Work item cannot be assigned.", status_code=409
        )
    await _audit(
        session,
        actor,
        "admin.work_item.assigned",
        "admin_work_item",
        item_id,
        {"assigned_to": str(assignee) if assignee else None},
    )
    await session.commit()
    return _row(row)


async def entity_view(
    session: AsyncSession, entity_type: str, entity_id: UUID, permissions: set[str]
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM admin_entity_view_definitions WHERE entity_type=:type AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"type": entity_type},
        )
    ).first()
    if not definition:
        raise VavError(
            "ADMIN_ENTITY_VIEW_NOT_FOUND", "Entity view is not registered.", status_code=404
        )
    current = _row(definition)
    sections = []
    for section in current["section_manifest"]:
        required = set(section.get("permissions", []))
        allowed = required.issubset(permissions)
        sections.append(
            {
                "section_code": section["code"],
                "title": section["title"],
                "status": "available" if allowed else "masked",
                "fields": [] if allowed else [{"value": "[REDACTED]"}],
                "related_entities": [],
                "allowed_operations": [],
                "source_module": section["module"],
                "source_version": current["semantic_version"],
            }
        )
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "sections": sections,
        "partial": any(item["status"] != "available" for item in sections),
    }


async def create_saved_view(
    session: AsyncSession, actor: UUID, payload: SavedViewCreate
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM admin_query_definitions WHERE query_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.query_code},
        )
    ).first()
    if not definition:
        raise VavError("ADMIN_QUERY_NOT_FOUND", "Query definition not found.", status_code=404)
    validate_query(_row(definition), payload.filters, payload.sort, payload.columns)
    if payload.visibility == "team" and not payload.shared_team:
        raise VavError("ADMIN_SHARED_TEAM_REQUIRED", "Team view requires a team.", status_code=422)
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_saved_views (owner_user_id,query_code,name,filter_definition,sort_definition,column_definition,visibility,shared_team) VALUES (:actor,:query,:name,CAST(:filters AS jsonb),CAST(:sort AS jsonb),CAST(:columns AS jsonb),:visibility,:team) RETURNING *"
            ),
            {
                "actor": actor,
                "query": payload.query_code,
                "name": payload.name,
                "filters": _json(payload.filters),
                "sort": _json({"field": payload.sort}),
                "columns": _json(payload.columns),
                "visibility": payload.visibility,
                "team": payload.shared_team,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def plan_bulk(session: AsyncSession, actor: UUID, payload: BulkPlan) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM admin_bulk_operation_definitions WHERE operation_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.operation_code},
        )
    ).first()
    if not definition:
        raise VavError(
            "ADMIN_BULK_OPERATION_NOT_FOUND", "Bulk operation is not registered.", status_code=404
        )
    current = _row(definition)
    unique_ids = list(dict.fromkeys(payload.target_ids))
    if current["dry_run_required"] and not payload.dry_run:
        raise VavError(
            "ADMIN_BULK_DRY_RUN_REQUIRED", "Bulk operation requires Dry Run.", status_code=409
        )
    if len(unique_ids) > current["maximum_batch_size"]:
        raise VavError(
            "ADMIN_BULK_LIMIT_EXCEEDED", "Bulk selection exceeds registered limit.", status_code=422
        )
    selection = [
        {"entity_id": str(item), "expected_version": payload.expected_versions.get(str(item))}
        for item in unique_ids
    ]
    input_hash = stable_hash({"selection": selection, "parameters": payload.parameters})
    existing = (
        await session.execute(
            text("SELECT * FROM admin_bulk_jobs WHERE idempotency_key=:key"),
            {"key": payload.idempotency_key},
        )
    ).first()
    if existing:
        result = _row(existing)
        if result["input_hash"] != input_hash:
            raise VavError(
                "ADMIN_BULK_KEY_REUSED",
                "Idempotency key conflicts with another selection.",
                status_code=409,
            )
        return result
    status = (
        "dry_run_completed"
        if payload.dry_run
        else ("approval_required" if current["approval_policy_code"] else "approved")
    )
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_bulk_jobs (operation_definition_id,requested_by,selection_type,selection_snapshot,input_parameters_encrypted,input_hash,dry_run,status,total_count,eligible_count,idempotency_key) VALUES (:definition,:actor,'explicit_ids',CAST(:selection AS jsonb),CAST(:parameters AS jsonb),:hash,:dry_run,:status,:count,:count,:key) RETURNING *"
            ),
            {
                "definition": current["id"],
                "actor": actor,
                "selection": _json(selection),
                "parameters": _json({"ciphertext": encrypt_private(payload.parameters)}),
                "hash": input_hash,
                "dry_run": payload.dry_run,
                "status": status,
                "count": len(unique_ids),
                "key": payload.idempotency_key,
            },
        )
    ).first()
    result = _row(row)
    for item in selection:
        await session.execute(
            text(
                "INSERT INTO admin_bulk_job_items (bulk_job_id,target_entity_id,expected_entity_version,status) VALUES (:job,:entity,:version,'eligible')"
            ),
            {"job": result["id"], "entity": item["entity_id"], "version": item["expected_version"]},
        )
    await _audit(
        session,
        actor,
        "admin.bulk_job.planned",
        "admin_bulk_job",
        result["id"],
        {"total": len(unique_ids), "dry_run": payload.dry_run},
    )
    await session.commit()
    return result


async def create_approval(
    session: AsyncSession, actor: UUID, payload: ApprovalCreate
) -> dict[str, Any]:
    policy = (
        await session.execute(
            text(
                "SELECT * FROM admin_approval_policies WHERE policy_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.policy_code},
        )
    ).first()
    if not policy:
        raise VavError(
            "ADMIN_APPROVAL_POLICY_NOT_FOUND", "Approval policy not found.", status_code=404
        )
    current = _row(policy)
    if (
        payload.capability_code not in current["applicable_capability_codes"]
        and "*" not in current["applicable_capability_codes"]
    ):
        raise VavError(
            "ADMIN_APPROVAL_POLICY_MISMATCH", "Policy does not cover capability.", status_code=422
        )
    request_hash = stable_hash(
        {
            "capability": payload.capability_code,
            "target": payload.target_entity_id,
            "payload": payload.payload,
            "state": payload.business_state_snapshot,
        }
    )
    number = f"APR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_approval_requests (approval_number,policy_id,requested_capability_code,target_entity_type,target_entity_id,requested_by,request_payload_encrypted,request_hash,business_state_snapshot,expires_at) VALUES (:number,:policy,:capability,:type,:entity,:actor,CAST(:payload AS jsonb),:hash,CAST(:state AS jsonb),:expires) RETURNING *"
            ),
            {
                "number": number,
                "policy": current["id"],
                "capability": payload.capability_code,
                "type": payload.target_entity_type,
                "entity": payload.target_entity_id,
                "actor": actor,
                "payload": _json({"ciphertext": encrypt_private(payload.payload)}),
                "hash": request_hash,
                "state": _json(payload.business_state_snapshot),
                "expires": datetime.now(UTC) + timedelta(seconds=current["validity_seconds"]),
            },
        )
    ).first()
    result = _row(row)
    await _audit(
        session,
        actor,
        "admin.approval.requested",
        "admin_approval_request",
        result["id"],
        {"capability": payload.capability_code},
    )
    await session.commit()
    return result


async def decide_approval(
    session: AsyncSession, reviewer: UUID, request_id: UUID, payload: ApprovalDecision
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT r.*,p.approval_steps FROM admin_approval_requests r JOIN admin_approval_policies p ON p.id=r.policy_id WHERE r.id=:id FOR UPDATE"
            ),
            {"id": request_id},
        )
    ).first()
    if not row:
        raise VavError("ADMIN_APPROVAL_NOT_FOUND", "Approval request not found.", status_code=404)
    current = _row(row)
    if current["requested_by"] == reviewer:
        raise VavError(
            "ADMIN_SELF_APPROVAL_DENIED",
            "Requester cannot approve their own request.",
            status_code=403,
        )
    if current["expires_at"] <= datetime.now(UTC):
        await session.execute(
            text("UPDATE admin_approval_requests SET status='expired' WHERE id=:id"),
            {"id": request_id},
        )
        await session.commit()
        raise VavError("ADMIN_APPROVAL_EXPIRED", "Approval request has expired.", status_code=409)
    if current["status"] not in {"submitted", "in_review"}:
        raise VavError(
            "ADMIN_APPROVAL_NOT_REVIEWABLE", "Approval request is not reviewable.", status_code=409
        )
    prior = int(
        await session.scalar(
            text(
                "SELECT count(DISTINCT reviewer_user_id) FROM admin_approval_decisions WHERE approval_request_id=:id AND decision='approved'"
            ),
            {"id": request_id},
        )
        or 0
    )
    step = prior + 1
    await session.execute(
        text(
            "INSERT INTO admin_approval_decisions (approval_request_id,step_number,reviewer_user_id,decision,reason_code,rationale_encrypted) VALUES (:request,:step,:reviewer,:decision,:reason,:rationale)"
        ),
        {
            "request": request_id,
            "step": step,
            "reviewer": reviewer,
            "decision": payload.decision,
            "reason": payload.reason_code,
            "rationale": encrypt_private(payload.rationale),
        },
    )
    required = int(current["approval_steps"].get("reviewers", 1))
    status = (
        "rejected"
        if payload.decision == "rejected"
        else ("approved" if step >= required else "in_review")
    )
    decided_column = (
        ",rejected_at=now()"
        if status == "rejected"
        else (",approved_at=now()" if status == "approved" else "")
    )
    updated = (
        await session.execute(
            text(
                f"UPDATE admin_approval_requests SET status=:status{decided_column} WHERE id=:id RETURNING *"
            ),
            {"status": status, "id": request_id},
        )
    ).first()
    await _audit(
        session,
        reviewer,
        f"admin.approval.{payload.decision}",
        "admin_approval_request",
        request_id,
        {"step": step},
    )
    await session.commit()
    return _row(updated)


def _reject_inline_secrets(configuration: dict[str, Any], secret_fields: list[str]) -> None:
    for field in secret_fields:
        if field in configuration and not (
            isinstance(configuration[field], str) and configuration[field].startswith("secret://")
        ):
            raise VavError(
                "ADMIN_CONFIGURATION_SECRET_REFERENCE_REQUIRED",
                "Secrets must use secret references.",
                status_code=422,
            )


async def create_configuration(
    session: AsyncSession, actor: UUID, payload: ConfigurationCreate
) -> dict[str, Any]:
    namespace = (
        await session.execute(
            text(
                "SELECT * FROM admin_configuration_namespaces WHERE namespace_code=:code AND lifecycle_status='active'"
            ),
            {"code": payload.namespace_code},
        )
    ).first()
    if not namespace:
        raise VavError(
            "ADMIN_CONFIGURATION_NAMESPACE_NOT_FOUND",
            "Configuration namespace not found.",
            status_code=404,
        )
    current = _row(namespace)
    _reject_inline_secrets(payload.configuration, current["secret_fields"])
    version = int(
        await session.scalar(
            text(
                "SELECT COALESCE(max(version_number),0)+1 FROM admin_configuration_versions WHERE namespace_id=:id AND environment=:environment"
            ),
            {"id": current["id"], "environment": payload.environment},
        )
        or 1
    )
    status = "review_required" if payload.environment == "production" else "draft"
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_configuration_versions (namespace_id,environment,version_number,semantic_version,configuration_encrypted,non_secret_checksum,status,created_by) VALUES (:namespace,:environment,:version,:semantic,CAST(:configuration AS jsonb),:checksum,:status,:actor) RETURNING *"
            ),
            {
                "namespace": current["id"],
                "environment": payload.environment,
                "version": version,
                "semantic": payload.semantic_version,
                "configuration": _json({"ciphertext": encrypt_private(payload.configuration)}),
                "checksum": stable_hash(payload.configuration),
                "status": status,
                "actor": actor,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def act_configuration(
    session: AsyncSession, actor: UUID, version_id: UUID, payload: ConfigurationAction
) -> dict[str, Any]:
    record = (
        await session.execute(
            text("SELECT * FROM admin_configuration_versions WHERE id=:id FOR UPDATE"),
            {"id": version_id},
        )
    ).first()
    if not record:
        raise VavError(
            "ADMIN_CONFIGURATION_VERSION_NOT_FOUND",
            "Configuration version not found.",
            status_code=404,
        )
    current = _row(record)
    if payload.action in {"approve", "activate"} and current["created_by"] == actor:
        raise VavError(
            "ADMIN_CONFIGURATION_SELF_APPROVAL_DENIED",
            "Creator cannot approve or activate production configuration.",
            status_code=403,
        )
    transitions = {
        "approve": ({"review_required"}, "approved"),
        "activate": ({"approved", "draft"}, "active"),
        "rollback": ({"active", "superseded"}, "rolled_back"),
        "reject": ({"review_required", "approved"}, "rejected"),
    }
    allowed, target = transitions[payload.action]
    if current["status"] not in allowed or (
        current["environment"] == "production"
        and payload.action == "activate"
        and current["status"] != "approved"
    ):
        raise VavError(
            "ADMIN_CONFIGURATION_TRANSITION_INVALID",
            "Configuration transition is invalid.",
            status_code=409,
        )
    if target == "active":
        await session.execute(
            text(
                "UPDATE admin_configuration_versions SET status='superseded' WHERE namespace_id=:namespace AND environment=:environment AND status='active'"
            ),
            {"namespace": current["namespace_id"], "environment": current["environment"]},
        )
    row = (
        await session.execute(
            text(
                "UPDATE admin_configuration_versions SET status=:status,approved_by=CASE WHEN :approve THEN :actor ELSE approved_by END,approved_at=CASE WHEN :approve THEN now() ELSE approved_at END,activated_at=CASE WHEN :activate THEN now() ELSE activated_at END WHERE id=:id RETURNING *"
            ),
            {
                "status": target,
                "approve": payload.action == "approve",
                "activate": payload.action == "activate",
                "actor": actor,
                "id": version_id,
            },
        )
    ).first()
    await _audit(
        session,
        actor,
        f"admin.configuration.{payload.action}",
        "admin_configuration_version",
        version_id,
    )
    await session.commit()
    return _row(row)


async def create_reveal(
    session: AsyncSession, actor: UUID, payload: RevealCreate
) -> dict[str, Any]:
    policy = (
        await session.execute(
            text(
                "SELECT * FROM admin_field_access_policies WHERE policy_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.policy_code},
        )
    ).first()
    if not policy:
        raise VavError("ADMIN_FIELD_POLICY_NOT_FOUND", "Field policy not found.", status_code=404)
    current = _row(policy)
    if not current["reveal_allowed"]:
        raise VavError(
            "ADMIN_FIELD_REVEAL_FORBIDDEN", "This field cannot be revealed.", status_code=403
        )
    if payload.purpose_code not in current["allowed_purposes"]:
        raise VavError(
            "ADMIN_FIELD_PURPOSE_DENIED", "Purpose does not permit field access.", status_code=403
        )
    if current["step_up_required"] and not step_up_current(payload.step_up_authenticated_at):
        raise VavError(
            "ADMIN_STEP_UP_REQUIRED", "Current step-up authentication is required.", status_code=401
        )
    expires = datetime.now(UTC) + timedelta(seconds=current["reveal_duration_seconds"] or 300)
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_sensitive_reveal_grants (admin_user_id,policy_id,entity_type,entity_id,purpose_code,reason_encrypted,expires_at) VALUES (:actor,:policy,:type,:entity,:purpose,:reason,:expires) RETURNING id,admin_user_id,policy_id,entity_type,entity_id,purpose_code,status,issued_at,expires_at,revoked_at"
            ),
            {
                "actor": actor,
                "policy": current["id"],
                "type": payload.entity_type,
                "entity": payload.entity_id,
                "purpose": payload.purpose_code,
                "reason": encrypt_private(payload.reason),
                "expires": expires,
            },
        )
    ).first()
    result = _row(row)
    await _audit(
        session,
        actor,
        "admin.sensitive_field.revealed",
        "admin_sensitive_reveal_grant",
        result["id"],
        {"policy_code": payload.policy_code, "purpose": payload.purpose_code},
    )
    await session.commit()
    return result


async def apply_masking(session: AsyncSession, actor: UUID, payload: MaskRequest) -> dict[str, Any]:
    policy = (
        await session.execute(
            text(
                "SELECT * FROM admin_field_access_policies WHERE policy_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.policy_code},
        )
    ).first()
    if not policy:
        raise VavError("ADMIN_FIELD_POLICY_NOT_FOUND", "Field policy not found.", status_code=404)
    current = _row(policy)
    permission = bool(set(payload.permission_codes).intersection(current["allowed_permissions"]))
    purpose = payload.purpose_code in current["allowed_purposes"]
    revealed = False
    if payload.reveal_grant_id:
        revealed = bool(
            await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM admin_sensitive_reveal_grants WHERE id=:id AND admin_user_id=:actor AND policy_id=:policy AND purpose_code=:purpose AND status='active' AND expires_at>now())"
                ),
                {
                    "id": payload.reveal_grant_id,
                    "actor": actor,
                    "policy": current["id"],
                    "purpose": payload.purpose_code,
                },
            )
        )
    allowed = (
        permission
        and purpose
        and (current["classification"] not in {"restricted", "highly_restricted"} or revealed)
    )
    return {
        "allowed": allowed,
        "value": payload.value
        if allowed
        else mask_value(payload.value, current["default_masking_rule"]),
        "masking_rule": "none" if allowed else current["default_masking_rule"],
        "reason_code": None if allowed else "ADMIN_FIELD_MASKED",
    }


async def evaluate_certification(
    session: AsyncSession, actor: UUID, payload: CertificationEvaluate
) -> dict[str, Any]:
    required = list(
        (
            await session.execute(
                text(
                    "SELECT capability_code FROM admin_capability_definitions WHERE owning_module=:domain AND lifecycle_status='active'"
                ),
                {"domain": payload.business_domain},
            )
        ).scalars()
    )
    verified = set(payload.verified_capability_codes).intersection(required)
    critical_gaps = len(set(required) - verified)
    ratio = len(verified) / len(required) if required else 0
    status = "eligible" if required and ratio == 1 and critical_gaps == 0 else "not_certified"
    row = (
        await session.execute(
            text(
                "INSERT INTO admin_domain_certifications (business_domain,release_version,environment,required_capability_count,implemented_capability_count,verified_capability_count,observable_coverage_ratio,operable_coverage_ratio,approval_coverage_ratio,recovery_coverage_ratio,masking_coverage_ratio,audit_coverage_ratio,unresolved_critical_gaps,status,evidence_ids,evaluated_by) VALUES (:domain,:release,:environment,:required,:required,:verified,:ratio,:ratio,:ratio,:ratio,:ratio,:ratio,:gaps,:status,CAST(:evidence AS jsonb),:actor) ON CONFLICT (business_domain,release_version,environment) DO UPDATE SET verified_capability_count=EXCLUDED.verified_capability_count,observable_coverage_ratio=EXCLUDED.observable_coverage_ratio,operable_coverage_ratio=EXCLUDED.operable_coverage_ratio,approval_coverage_ratio=EXCLUDED.approval_coverage_ratio,recovery_coverage_ratio=EXCLUDED.recovery_coverage_ratio,masking_coverage_ratio=EXCLUDED.masking_coverage_ratio,audit_coverage_ratio=EXCLUDED.audit_coverage_ratio,unresolved_critical_gaps=EXCLUDED.unresolved_critical_gaps,status=EXCLUDED.status,evidence_ids=EXCLUDED.evidence_ids,evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now(),certified_by=NULL,certified_at=NULL RETURNING *"
            ),
            {
                "domain": payload.business_domain,
                "release": payload.release_version,
                "environment": payload.environment,
                "required": len(required),
                "verified": len(verified),
                "ratio": ratio,
                "gaps": critical_gaps,
                "status": status,
                "evidence": _json(payload.evidence_ids),
                "actor": actor,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def decide_certification(
    session: AsyncSession, actor: UUID, certification_id: UUID, decision: str
) -> dict[str, Any]:
    record = (
        await session.execute(
            text("SELECT * FROM admin_domain_certifications WHERE id=:id FOR UPDATE"),
            {"id": certification_id},
        )
    ).first()
    if not record:
        raise VavError("ADMIN_CERTIFICATION_NOT_FOUND", "Certification not found.", status_code=404)
    current = _row(record)
    if current["evaluated_by"] == actor:
        raise VavError(
            "ADMIN_CERTIFICATION_INDEPENDENT_REVIEW_REQUIRED",
            "Evaluator cannot certify their result.",
            status_code=403,
        )
    if decision == "certified" and (
        current["status"] != "eligible" or current["environment"] != "production"
    ):
        raise VavError(
            "ADMIN_CERTIFICATION_NOT_ELIGIBLE",
            "Only eligible production evidence can be certified.",
            status_code=409,
        )
    row = (
        await session.execute(
            text(
                "UPDATE admin_domain_certifications SET status=:decision,certified_by=:actor,certified_at=now() WHERE id=:id RETURNING *"
            ),
            {"decision": decision, "actor": actor, "id": certification_id},
        )
    ).first()
    await session.commit()
    return _row(row)
