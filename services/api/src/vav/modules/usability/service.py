# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.usability.domain import certification_status, checksum, validate_import_rows
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
        "scenarios": "SELECT * FROM usability_uat_scenarios ORDER BY business_domain,scenario_code LIMIT 500",
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
    record = (
        await session.execute(
            text("SELECT * FROM usability_uat_runs WHERE id=:id FOR UPDATE"), {"id": run_id}
        )
    ).first()
    if not record or _row(record)["status"] != "running":
        raise VavError("USABILITY_UAT_RUN_NOT_ACTIVE", "UAT run is not active.", status_code=409)
    for number, result in enumerate(payload.step_results, 1):
        await session.execute(
            text(
                "INSERT INTO usability_uat_step_results (run_id,step_number,status,safe_observation,error_code,duration_ms) VALUES (:run,:step,:status,:observation,:error,:duration)"
            ),
            {
                "run": run_id,
                "step": number,
                "status": result.get("status", "failed"),
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
    existing = (
        await session.execute(
            text(
                "SELECT * FROM usability_user_drafts WHERE definition_id=:definition AND user_id=:user AND entity_id IS NOT DISTINCT FROM :entity FOR UPDATE"
            ),
            {"definition": current["id"], "user": user_id, "entity": payload.entity_id},
        )
    ).first()
    if existing and payload.client_version <= _row(existing)["client_version"]:
        raise VavError(
            "USABILITY_DRAFT_VERSION_CONFLICT", "Draft has a newer server version.", status_code=409
        )
    ciphertext = {"ciphertext": encrypt_private(payload.payload)}
    expires = datetime.now(UTC) + timedelta(seconds=current["ttl_seconds"])
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
                "payload": _json(ciphertext),
                "checksum": checksum(payload.payload),
                "version": payload.client_version,
                "expires": expires,
            },
        )
    ).first()
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
    required = set(current["schema_definition"].get("required", []))
    results = validate_import_rows(payload.rows, required, current["maximum_rows"])
    source_checksum = checksum(payload.rows)
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
