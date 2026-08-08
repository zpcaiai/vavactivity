# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.usability.domain import (
    DraftStatus,
    certification_status,
    checksum,
    draft_expired,
    resolve_draft_conflict,
    validate_draft_payload,
    validate_import_rows,
)
from vav.modules.usability.schemas import (
    CertificationEvaluate,
    DraftSave,
    ImportPreview,
    UatRunComplete,
    UatRunCreate,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _row(value: Any) -> dict[str, Any]:
    return dict(value._mapping)


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_sequence(value: Any) -> list[Any]:
    if isinstance(value, str | bytes | bytearray):
        return []
    if isinstance(value, Mapping):
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return []


def _normalize_schema_definition_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str | bytes | bytearray):
        text = value.decode() if isinstance(value, bytes | bytearray) else str(value)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _safe_required_fields(value: Any) -> list[str]:
    payload = _normalize_schema_definition_payload(value)
    fields = payload.get("required", [])
    if isinstance(fields, list | tuple | set):
        return [str(item) for item in fields if str(item)]
    if fields:
        return [str(fields)]
    return []


def _decrypt_encrypted_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        ciphertext = raw.get("ciphertext")
        if isinstance(ciphertext, str):
            decrypted = decrypt_private(ciphertext)
        elif isinstance(ciphertext, bytes | bytearray):
            decrypted = decrypt_private(str(ciphertext.decode()))
        else:
            return {}
    elif isinstance(raw, str | bytes | bytearray):
        text = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
        candidate: Any = text
        if text.startswith("{") and text.endswith("}"):
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                candidate = text
        if isinstance(candidate, Mapping):
            wrapped = candidate.get("ciphertext", text)
            if isinstance(wrapped, str | bytes | bytearray):
                decrypted = decrypt_private(str(wrapped))
            else:
                return {}
        else:
            decrypted = decrypt_private(text)
    else:
        return {}
    return dict(decrypted) if isinstance(decrypted, Mapping) else {}


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM usability_uat_scenarios WHERE lifecycle_status='active') scenarios,(SELECT count(*) FROM usability_uat_runs WHERE status='failed') failed_uat,(SELECT count(*) FROM usability_compatibility_runs WHERE status='failed') compatibility_failures,(SELECT count(*) FROM usability_localization_runs WHERE status='failed') localization_failures,(SELECT count(*) FROM usability_user_drafts WHERE status='active' AND expires_at>now()) active_drafts,(SELECT count(*) FROM usability_import_jobs WHERE status='partially_failed') partial_imports,(SELECT count(*) FROM usability_certifications WHERE status<>'certified') uncertified"
            )
        )
    ).first()
    return _row(row) if row else {}


async def list_section(session: AsyncSession, section: str) -> list[dict[str, Any]]:
    queries = {
        "scenarios": "SELECT * FROM usability_uat_scenarios WHERE lifecycle_status='active' ORDER BY business_domain,scenario_code LIMIT 500",
        "runs": "SELECT r.*,s.scenario_code FROM usability_uat_runs r JOIN usability_uat_scenarios s ON s.id=r.scenario_id ORDER BY r.created_at DESC LIMIT 500",
        "synthetic-data": "SELECT r.*,b.blueprint_code FROM usability_synthetic_runs r JOIN usability_synthetic_blueprints b ON b.id=r.blueprint_id ORDER BY r.created_at DESC LIMIT 500",
        "demo": "SELECT * FROM usability_demo_environments ORDER BY environment_code",
        "compatibility": "SELECT * FROM usability_compatibility_runs ORDER BY executed_at DESC NULLS LAST LIMIT 500",
        "localization": "SELECT * FROM usability_localization_runs ORDER BY executed_at DESC NULLS LAST LIMIT 500",
        "drafts": "SELECT id,definition_id,user_id,entity_id,schema_version,client_version,status,expires_at,created_at,updated_at FROM usability_user_drafts ORDER BY updated_at DESC LIMIT 500",
        "notifications": "SELECT * FROM usability_notification_qa_cases ORDER BY case_code LIMIT 500",
        "imports": "SELECT * FROM usability_import_jobs ORDER BY created_at DESC LIMIT 500",
        "studies": "SELECT * FROM usability_studies ORDER BY created_at DESC LIMIT 500",
        "support": "SELECT * FROM usability_support_playbooks ORDER BY playbook_code LIMIT 500",
        "certifications": "SELECT * FROM usability_certifications ORDER BY evaluated_at DESC LIMIT 500",
        "release": "SELECT * FROM usability_certifications ORDER BY release_version DESC,business_domain LIMIT 500",
    }
    if section not in queries:
        raise VavError(
            "USABILITY_SECTION_NOT_FOUND", "Usability section not found.", status_code=404
        )
    return [dict(row) for row in (await session.execute(text(queries[section]))).mappings()]


async def list_user_drafts(
    session: AsyncSession,
    user_id: UUID,
    *,
    definition_code: str | None = None,
    include_expired: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if definition_code:
        query = """
            SELECT d.id,d.definition_id,dd.draft_code,d.entity_id,d.schema_version,d.client_version,d.status,d.expires_at,d.created_at,d.updated_at
            FROM usability_user_drafts d
            JOIN usability_draft_definitions dd ON dd.id=d.definition_id
            WHERE d.user_id=:user AND dd.draft_code=:code
            ORDER BY d.updated_at DESC
            LIMIT :limit
        """
        params = {"user": user_id, "code": definition_code, "limit": int(limit)}
    else:
        query = """
            SELECT d.id,d.definition_id,dd.draft_code,d.entity_id,d.schema_version,d.client_version,d.status,d.expires_at,d.created_at,d.updated_at
            FROM usability_user_drafts d
            JOIN usability_draft_definitions dd ON dd.id=d.definition_id
            WHERE d.user_id=:user
            ORDER BY d.updated_at DESC
            LIMIT :limit
        """
        params = {"user": user_id, "limit": int(limit)}
    rows = list((await session.execute(text(query), params)).mappings())
    result: list[dict[str, Any]] = []
    for item in rows:
        data = _row(item)
        if include_expired or not draft_expired(data.get("expires_at")):
            result.append(data)
    return result


async def get_user_draft(session: AsyncSession, user_id: UUID, draft_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT d.*,dd.schema_definition,dd.sensitive_fields FROM usability_user_drafts d JOIN usability_draft_definitions dd ON dd.id=d.definition_id WHERE d.id=:id AND d.user_id=:user"
            ),
            {"id": draft_id, "user": user_id},
        )
    ).first()
    if not row:
        raise VavError("USABILITY_DRAFT_NOT_FOUND", "Draft not found.", status_code=404)
    data = _row(row)
    data["payload"] = _decrypt_encrypted_payload(data.get("encrypted_payload"))
    if draft_expired(data.get("expires_at")):
        data["status"] = str(DraftStatus.EXPIRED)
    return data


async def start_uat(session: AsyncSession, actor: UUID, payload: UatRunCreate) -> dict[str, Any]:
    scenario = (
        await session.execute(
            text(
                "SELECT * FROM usability_uat_scenarios WHERE scenario_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.scenario_code},
        )
    ).first()
    if not scenario:
        raise VavError(
            "USABILITY_UAT_SCENARIO_NOT_FOUND", "UAT scenario not found.", status_code=404
        )
    current = _row(scenario)
    if (
        payload.locale not in current["required_locales"]
        or payload.device_profile not in current["required_device_profiles"]
    ):
        raise VavError(
            "USABILITY_UAT_MATRIX_MISMATCH",
            "Locale or device is outside scenario matrix.",
            status_code=422,
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO usability_uat_runs (scenario_id,environment,release_version,locale,device_profile,status,executed_by,started_at) VALUES (:scenario,:environment,:release,:locale,:device,'running',:actor,now()) RETURNING *"
            ),
            {
                "scenario": current["id"],
                "environment": payload.environment,
                "release": payload.release_version,
                "locale": payload.locale,
                "device": payload.device_profile,
                "actor": actor,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def complete_uat(
    session: AsyncSession, run_id: UUID, payload: UatRunComplete
) -> dict[str, Any]:
    run = (
        await session.execute(
            text(
                "SELECT r.*,s.steps FROM usability_uat_runs r JOIN usability_uat_scenarios s ON s.id=r.scenario_id WHERE r.id=:id FOR UPDATE"
            ),
            {"id": run_id},
        )
    ).first()
    if not run:
        raise VavError("USABILITY_UAT_RUN_NOT_FOUND", "UAT run not found.", status_code=404)
    state = _row(run)
    if state["status"] != "running":
        raise VavError("USABILITY_UAT_RUN_NOT_ACTIVE", "UAT run is not active.", status_code=409)

    step_count = len(list(state["steps"] or []))
    if step_count and len(payload.step_results) != step_count:
        raise VavError(
            "USABILITY_UAT_STEP_COUNT_MISMATCH",
            "Step results do not match scenario definition.",
            status_code=422,
        )
    allowed_status = {"not_run", "passed", "failed", "blocked", "skipped"}
    for number, result in enumerate(payload.step_results, 1):
        status = str(result.get("status", "not_run"))
        if status not in allowed_status:
            raise VavError(
                "USABILITY_UAT_STEP_STATUS_INVALID",
                "Invalid step result status.",
                status_code=422,
            )
        await session.execute(
            text(
                "INSERT INTO usability_uat_step_results (run_id,step_number,status,safe_observation,error_code,duration_ms) VALUES (:run,:step,:status,:observation,:error,:duration)"
            ),
            {
                "run": run_id,
                "step": number,
                "status": status,
                "observation": str(result.get("observation", ""))[:2000],
                "error": result.get("error_code"),
                "duration": result.get("duration_ms"),
            },
        )
    row = (
        await session.execute(
            text(
                "UPDATE usability_uat_runs SET status=:status,evidence_refs=CAST(:evidence AS jsonb),completed_at=now() WHERE id=:id RETURNING *"
            ),
            {"status": payload.status, "evidence": _json(payload.evidence_refs), "id": run_id},
        )
    ).first()
    await session.commit()
    return _row(row)


async def save_draft(session: AsyncSession, user_id: UUID, payload: DraftSave) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM usability_draft_definitions WHERE draft_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.draft_code},
        )
    ).first()
    if not definition:
        raise VavError(
            "USABILITY_DRAFT_NOT_REGISTERED", "Draft definition not found.", status_code=404
        )
    current = _row(definition)
    payload_findings = validate_draft_payload(
        payload.payload,
        sensitive_fields=current.get("sensitive_fields") or (),
        local_buffer_allowed=False,
    )
    if payload_findings:
        raise VavError(
            "USABILITY_DRAFT_VALIDATION_FAILED",
            "Draft payload failed validation.",
            status_code=422,
            details=payload_findings,
        )

    existing = (
        await session.execute(
            text(
                "SELECT * FROM usability_user_drafts WHERE definition_id=:definition AND user_id=:user AND entity_id IS NOT DISTINCT FROM :entity FOR UPDATE"
            ),
            {"definition": current["id"], "user": user_id, "entity": payload.entity_id},
        )
    ).first()
    if existing:
        current_row = _row(existing)
        if draft_expired(current_row.get("expires_at")):
            await session.execute(
                text("DELETE FROM usability_user_drafts WHERE id=:id"), {"id": current_row["id"]}
            )
            existing = None
        elif _safe_int(payload.client_version) <= _safe_int(current_row.get("client_version")):
            raise VavError(
                "USABILITY_DRAFT_VERSION_CONFLICT",
                "Draft has a newer server version.",
                status_code=409,
            )

    if existing:
        previous = _row(existing)
        previous_payload = {
            "payload": {},
            "checksum": previous.get("payload_checksum"),
            "client_version": previous.get("client_version", 0),
        }
        try:
            raw = previous.get("encrypted_payload")
            if isinstance(raw, Mapping):
                previous_payload["payload"] = decrypt_private(raw.get("ciphertext", "{}"))
        except Exception:
            previous_payload["payload"] = {}
        conflict = resolve_draft_conflict(
            server={
                "schema_version": previous.get("schema_version"),
                "payload": previous_payload["payload"],
                "checksum": previous_payload["checksum"],
                "client_version": _safe_int(previous_payload["client_version"]),
            },
            client={
                "schema_version": payload.schema_version,
                "payload": payload.payload,
                "checksum": checksum(payload.payload),
                "client_version": _safe_int(payload.client_version),
            },
            policy=current["conflict_policy"],
            high_risk_fields=current["sensitive_fields"],
            base=None,
            current_entity_version=current_row.get("client_version"),
        )
        if conflict["status"] != str(DraftStatus.ACTIVE):
            raise VavError(
                "USABILITY_DRAFT_CONFLICT",
                "Draft conflict requires manual merge before save.",
                status_code=409,
                details=[conflict],
            )

    expiry = datetime.now(UTC) + timedelta(seconds=_safe_int(current["ttl_seconds"], default=3600))
    row = (
        await session.execute(
            text(
                "INSERT INTO usability_user_drafts (definition_id,user_id,entity_id,schema_version,encrypted_payload,payload_checksum,client_version,expires_at) VALUES (:definition,:user,:entity,:schema,CAST(:payload AS jsonb),:checksum,:version,:expires) ON CONFLICT (definition_id,user_id,entity_id) DO UPDATE SET schema_version=EXCLUDED.schema_version,encrypted_payload=EXCLUDED.encrypted_payload,payload_checksum=EXCLUDED.payload_checksum,client_version=EXCLUDED.client_version,status='active',expires_at=EXCLUDED.expires_at,updated_at=now() RETURNING id,definition_id,user_id,entity_id,schema_version,payload_checksum,client_version,status,expires_at,created_at,updated_at"
            ),
            {
                "definition": current["id"],
                "user": user_id,
                "entity": payload.entity_id,
                "schema": payload.schema_version,
                "payload": _json({"ciphertext": encrypt_private(payload.payload)}),
                "checksum": checksum(payload.payload),
                "version": _safe_int(payload.client_version, default=1),
                "expires": expiry,
            },
        )
    ).first()
    await session.commit()
    return _row(row)


async def discard_draft(session: AsyncSession, user_id: UUID, draft_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE usability_user_drafts SET status='discarded',updated_at=now() WHERE id=:id AND user_id=:user RETURNING id,definition_id,user_id,entity_id,schema_version,client_version,status,expires_at,created_at,updated_at"
            ),
            {"id": draft_id, "user": user_id},
        )
    ).first()
    if not row:
        raise VavError("USABILITY_DRAFT_NOT_FOUND", "Draft not found.", status_code=404)
    await session.commit()
    return _row(row)


async def preview_import(
    session: AsyncSession, actor: UUID, payload: ImportPreview
) -> dict[str, Any]:
    definition = (
        await session.execute(
            text(
                "SELECT * FROM usability_import_definitions WHERE import_code=:code AND lifecycle_status='active' ORDER BY semantic_version DESC LIMIT 1"
            ),
            {"code": payload.import_code},
        )
    ).first()
    if not definition:
        raise VavError(
            "USABILITY_IMPORT_NOT_REGISTERED", "Import definition not found.", status_code=404
        )
    current = _row(definition)
    if current["dry_run_required"] and not payload.dry_run:
        raise VavError(
            "USABILITY_IMPORT_DRY_RUN_REQUIRED", "Import requires Dry Run.", status_code=409
        )

    rows = _to_sequence(payload.rows)
    if _safe_int(current["maximum_rows"]) < len(rows):
        raise VavError(
            "USABILITY_IMPORT_TOO_MANY_ROWS",
            "Import payload exceeds allowed size.",
            status_code=422,
        )
    # Preserve schema order: the validator uses the first required field as the
    # deterministic duplicate key for an import batch.
    required = _safe_required_fields(current.get("schema_definition"))
    results = validate_import_rows(rows, required, _safe_int(current["maximum_rows"], default=1))
    source_checksum = checksum(rows)
    existing = (
        await session.execute(
            text("SELECT * FROM usability_import_jobs WHERE idempotency_key=:key"),
            {"key": payload.idempotency_key},
        )
    ).first()
    if existing:
        result = _row(existing)
        if result["source_checksum"] != source_checksum:
            raise VavError(
                "USABILITY_IMPORT_KEY_REUSED",
                "Import key conflicts with another file.",
                status_code=409,
            )
        return result

    valid = sum(item["status"] == "valid" for item in results)
    row = (
        await session.execute(
            text(
                "INSERT INTO usability_import_jobs (definition_id,requested_by,source_file_ref,source_checksum,dry_run,idempotency_key,status,total_rows,valid_rows,invalid_rows) VALUES (:definition,:actor,:source,:checksum,:dry_run,:key,'preview_ready',:total,:valid,:invalid) RETURNING *"
            ),
            {
                "definition": current["id"],
                "actor": actor,
                "source": payload.source_file_ref,
                "checksum": source_checksum,
                "dry_run": payload.dry_run,
                "key": payload.idempotency_key,
                "total": len(results),
                "valid": valid,
                "invalid": len(results) - valid,
            },
        )
    ).first()
    result = _row(row)
    for item in results:
        await session.execute(
            text(
                "INSERT INTO usability_import_row_results (job_id,row_number,status,field_errors) VALUES (:job,:row,:status,CAST(:errors AS jsonb))"
            ),
            {
                "job": result["id"],
                "row": item["row_number"],
                "status": item["status"],
                "errors": _json(item["field_errors"]),
            },
        )
    await session.commit()
    return result


async def evaluate_certification(
    session: AsyncSession, actor: UUID, payload: CertificationEvaluate
) -> dict[str, Any]:
    status = certification_status(
        payload.results, payload.unresolved_critical_findings, payload.environment
    )
    values = {
        key: payload.results.get(key, "not_run")
        for key in (
            "uat",
            "compatibility",
            "localization",
            "draft",
            "notification",
            "import_export",
        )
    }
    row = (
        await session.execute(
            text(
                "INSERT INTO usability_certifications (business_domain,release_version,environment,uat_status,compatibility_status,localization_status,draft_status,notification_status,import_export_status,unresolved_critical_findings,status,evidence_refs,evaluated_by) VALUES (:domain,:release,:environment,:uat,:compatibility,:localization,:draft,:notification,:import_export,:findings,:status,CAST(:evidence AS jsonb),:actor) ON CONFLICT (business_domain,release_version,environment) DO UPDATE SET uat_status=EXCLUDED.uat_status,compatibility_status=EXCLUDED.compatibility_status,localization_status=EXCLUDED.localization_status,draft_status=EXCLUDED.draft_status,notification_status=EXCLUDED.notification_status,import_export_status=EXCLUDED.import_export_status,unresolved_critical_findings=EXCLUDED.unresolved_critical_findings,status=EXCLUDED.status,evidence_refs=EXCLUDED.evidence_refs,evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now(),certified_by=NULL,certified_at=NULL RETURNING *"
            ),
            {
                "domain": payload.business_domain,
                "release": payload.release_version,
                "environment": payload.environment,
                **values,
                "findings": payload.unresolved_critical_findings,
                "status": status,
                "evidence": _json(payload.evidence_refs),
                "actor": actor,
            },
        )
    ).first()
    await session.commit()
    return _row(row)
