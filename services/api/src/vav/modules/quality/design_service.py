# ruff: noqa: E501

"""Persistence and policy services for governed design-system assets."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.quality.design_schemas import (
    AuditRunCreate,
    BaselineCreate,
    ComponentUpsert,
    PatternUpsert,
    TokenReleaseCreate,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


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
            "VALUES (:actor,'admin',:action,:subject_type,:subject_id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "action": action,
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "context": _json(context or {}),
        },
    )


async def _all(session: AsyncSession, table: str, order_by: str) -> list[dict[str, Any]]:
    allowed = {
        "ui_token_releases",
        "ui_components",
        "ui_patterns",
        "ui_audit_runs",
        "ui_visual_baselines",
        "ui_visual_differences",
    }
    if table not in allowed:
        raise ValueError("table is not allowlisted")
    result = (await session.execute(text(f"SELECT * FROM {table} ORDER BY {order_by}"))).mappings()
    return [dict(item) for item in result]


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ui_components WHERE status='active') AS components_active,"
                "(SELECT count(*) FROM ui_patterns WHERE status='active') AS patterns_active,"
                "(SELECT count(*) FROM quality_pages) AS pages_registered,"
                "(SELECT count(*) FROM ui_audit_runs WHERE status='failed') AS audits_failed,"
                "(SELECT count(*) FROM ui_audit_runs WHERE manual_review_required AND status<>'approved') AS manual_reviews_open,"
                "(SELECT count(*) FROM ui_visual_baselines WHERE status='pending') AS baselines_pending,"
                "(SELECT count(*) FROM ui_visual_differences WHERE status='pending') AS visual_differences_pending,"
                "(SELECT count(*) FROM ui_token_releases WHERE status='released') AS token_releases"
            )
        )
    ).one()
    item = _row(row)
    item["technical_gates_passed"] = item["audits_failed"] == 0
    item["production_certified"] = (
        item["technical_gates_passed"]
        and item["manual_reviews_open"] == 0
        and item["baselines_pending"] == 0
        and item["visual_differences_pending"] == 0
    )
    item["release_allowed"] = item["production_certified"]
    return item


async def list_tokens(session: AsyncSession) -> list[dict[str, Any]]:
    return await _all(session, "ui_token_releases", "created_at DESC,id")


async def create_token_release(
    session: AsyncSession, actor_id: UUID, payload: TokenReleaseCreate
) -> dict[str, Any]:
    try:
        result = await session.execute(
            text(
                "INSERT INTO ui_token_releases (token_version,manifest_checksum_sha256,generated_checksum_sha256,change_summary,breaking_changes,created_by) "
                "VALUES (:version,:manifest,:generated,:summary,CAST(:breaking AS jsonb),:actor) RETURNING *"
            ),
            {
                "version": payload.token_version,
                "manifest": payload.manifest_checksum_sha256,
                "generated": payload.generated_checksum_sha256,
                "summary": payload.change_summary,
                "breaking": _json(payload.breaking_changes),
                "actor": actor_id,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "DESIGN_TOKEN_VERSION_CONFLICT", "Token version already exists.", status_code=409
        ) from exc
    item = _row(result.one())
    await _audit(session, actor_id, "design.tokens.created", "ui_token_release", item["id"])
    await session.commit()
    return item


async def approve_token_release(
    session: AsyncSession, actor_id: UUID, release_id: UUID
) -> dict[str, Any]:
    current = (
        await session.execute(
            text("SELECT * FROM ui_token_releases WHERE id=:id FOR UPDATE"), {"id": release_id}
        )
    ).first()
    if current is None:
        raise VavError(
            "DESIGN_TOKEN_RELEASE_NOT_FOUND", "Token release was not found.", status_code=404
        )
    item = _row(current)
    if item["status"] != "draft":
        raise VavError(
            "DESIGN_TOKEN_RELEASE_STATE_INVALID",
            "Only a draft token release can be approved.",
            status_code=409,
        )
    if item["created_by"] == actor_id:
        raise VavError(
            "DESIGN_APPROVAL_SEPARATION_REQUIRED",
            "Token approval requires an independent reviewer.",
            status_code=409,
        )
    result = await session.execute(
        text(
            "UPDATE ui_token_releases SET status='approved',approved_by=:actor,approved_at=now() WHERE id=:id RETURNING *"
        ),
        {"actor": actor_id, "id": release_id},
    )
    approved = _row(result.one())
    await _audit(session, actor_id, "design.tokens.approved", "ui_token_release", release_id)
    await session.commit()
    return approved


def _validate_release_evidence(manifest: dict[str, Any]) -> None:
    required = {"token_build", "component_tests", "accessibility_review", "visual_baseline_review"}
    if set(manifest) < required:
        raise VavError(
            "DESIGN_RELEASE_EVIDENCE_INCOMPLETE",
            "Release evidence is missing one or more required gates.",
            status_code=409,
        )
    for code in required:
        value = manifest.get(code)
        if (
            not isinstance(value, dict)
            or value.get("status") != "accepted"
            or not isinstance(value.get("checksum_sha256"), str)
            or len(value["checksum_sha256"]) != 64
        ):
            raise VavError(
                "DESIGN_RELEASE_EVIDENCE_INVALID",
                f"Evidence gate '{code}' is not accepted and checksum-bound.",
                status_code=409,
            )


async def release_tokens(
    session: AsyncSession, actor_id: UUID, release_id: UUID, manifest: dict[str, Any]
) -> dict[str, Any]:
    _validate_release_evidence(manifest)
    current = (
        await session.execute(
            text("SELECT * FROM ui_token_releases WHERE id=:id FOR UPDATE"), {"id": release_id}
        )
    ).first()
    if current is None:
        raise VavError(
            "DESIGN_TOKEN_RELEASE_NOT_FOUND", "Token release was not found.", status_code=404
        )
    item = _row(current)
    if item["status"] != "approved":
        raise VavError(
            "DESIGN_TOKEN_RELEASE_STATE_INVALID",
            "Only an approved token release can be released.",
            status_code=409,
        )
    if item["created_by"] == actor_id:
        raise VavError(
            "DESIGN_RELEASE_SEPARATION_REQUIRED",
            "Token release requires an independent release manager.",
            status_code=409,
        )
    result = await session.execute(
        text(
            "UPDATE ui_token_releases SET status='released',evidence_manifest=CAST(:manifest AS jsonb),released_by=:actor,released_at=now() WHERE id=:id RETURNING *"
        ),
        {"manifest": _json(manifest), "actor": actor_id, "id": release_id},
    )
    released = _row(result.one())
    await _audit(
        session,
        actor_id,
        "design.tokens.released",
        "ui_token_release",
        release_id,
        {"token_version": item["token_version"]},
    )
    await session.commit()
    return released


async def list_components(session: AsyncSession) -> list[dict[str, Any]]:
    return await _all(session, "ui_components", "component_code")


async def upsert_component(
    session: AsyncSession, actor_id: UUID, payload: ComponentUpsert
) -> dict[str, Any]:
    values = payload.model_dump(mode="json")
    values.update(
        {
            "accessibility": _json(values.pop("accessibility_contract")),
            "states": _json(values.pop("supported_states")),
            "actor": actor_id,
        }
    )
    result = await session.execute(
        text(
            "INSERT INTO ui_components (component_code,package_name,source_location,owner_team,accessibility_contract,supported_states,status,created_by,updated_by) "
            "VALUES (:component_code,:package_name,:source_location,:owner_team,CAST(:accessibility AS jsonb),CAST(:states AS jsonb),:status,:actor,:actor) "
            "ON CONFLICT (component_code) DO UPDATE SET package_name=EXCLUDED.package_name,source_location=EXCLUDED.source_location,owner_team=EXCLUDED.owner_team,accessibility_contract=EXCLUDED.accessibility_contract,supported_states=EXCLUDED.supported_states,status=EXCLUDED.status,updated_by=EXCLUDED.updated_by,updated_at=now() RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "design.components.upserted", "ui_component", item["id"])
    await session.commit()
    return item


async def deprecate_component(
    session: AsyncSession, actor_id: UUID, component_id: UUID, reason: str, replacement: str | None
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE ui_components SET status='deprecated',deprecation_reason=:reason,replacement_component_code=:replacement,updated_by=:actor,updated_at=now() WHERE id=:id AND status IN ('active','experimental') RETURNING *"
        ),
        {"reason": reason, "replacement": replacement, "actor": actor_id, "id": component_id},
    )
    row = result.first()
    if row is None:
        raise VavError(
            "DESIGN_COMPONENT_NOT_DEPRECATABLE",
            "Component was not found or is not active.",
            status_code=409,
        )
    item = _row(row)
    await _audit(
        session,
        actor_id,
        "design.components.deprecated",
        "ui_component",
        component_id,
        {"reason": reason, "replacement": replacement},
    )
    await session.commit()
    return item


async def list_patterns(session: AsyncSession) -> list[dict[str, Any]]:
    return await _all(session, "ui_patterns", "pattern_code")


async def upsert_pattern(
    session: AsyncSession, actor_id: UUID, payload: PatternUpsert
) -> dict[str, Any]:
    values = payload.model_dump(mode="json")
    values.update(
        {
            "components": _json(values.pop("required_components")),
            "states": _json(values.pop("required_states")),
            "actor": actor_id,
        }
    )
    result = await session.execute(
        text(
            "INSERT INTO ui_patterns (pattern_code,name,audience,source_location,required_components,required_states,accessibility_notes,status,created_by,updated_by) "
            "VALUES (:pattern_code,:name,:audience,:source_location,CAST(:components AS jsonb),CAST(:states AS jsonb),:accessibility_notes,:status,:actor,:actor) "
            "ON CONFLICT (pattern_code) DO UPDATE SET name=EXCLUDED.name,audience=EXCLUDED.audience,source_location=EXCLUDED.source_location,required_components=EXCLUDED.required_components,required_states=EXCLUDED.required_states,accessibility_notes=EXCLUDED.accessibility_notes,status=EXCLUDED.status,updated_by=EXCLUDED.updated_by,updated_at=now() RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "design.patterns.upserted", "ui_pattern", item["id"])
    await session.commit()
    return item


async def list_pages(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("SELECT * FROM quality_pages ORDER BY application_code,route_path")
        )
    ).mappings()
    return [dict(item) for item in rows]


async def list_audits(session: AsyncSession, audit_type: str | None = None) -> list[dict[str, Any]]:
    audit_filter = ""
    parameters: dict[str, Any] = {}
    if audit_type is not None:
        audit_filter = " WHERE audit_type=:audit_type"
        parameters["audit_type"] = audit_type
    rows = (
        await session.execute(
            text(
                f"SELECT * FROM ui_audit_runs{audit_filter} ORDER BY started_at DESC,id"
            ),
            parameters,
        )
    ).mappings()
    return [dict(item) for item in rows]


async def create_audit(
    session: AsyncSession, actor_id: UUID, payload: AuditRunCreate
) -> dict[str, Any]:
    if (
        payload.audit_type == "accessibility"
        and payload.status == "technical_pass"
        and not payload.manual_review_required
    ):
        raise VavError(
            "DESIGN_ACCESSIBILITY_REVIEW_REQUIRED",
            "Accessibility technical results must remain subject to manual review.",
            status_code=409,
        )
    if (
        payload.status in {"technical_pass", "needs_review"}
        and not payload.evidence_checksum_sha256
    ):
        raise VavError(
            "DESIGN_AUDIT_EVIDENCE_REQUIRED",
            "Passing audit results require checksum-bound evidence.",
            status_code=422,
        )
    values = payload.model_dump(mode="json")
    values.update(
        {
            "findings_json": _json(values.pop("findings")),
            "metrics_json": _json(values.pop("metrics")),
            "actor": actor_id,
        }
    )
    try:
        result = await session.execute(
            text(
                "INSERT INTO ui_audit_runs (audit_code,audit_type,application_code,route_path,git_commit,environment,viewport,theme,locale,density,status,findings,metrics,artifact_reference,evidence_checksum_sha256,manual_review_required,ran_by,completed_at) "
                "VALUES (:audit_code,:audit_type,:application_code,:route_path,:git_commit,:environment,:viewport,:theme,:locale,:density,:status,CAST(:findings_json AS jsonb),CAST(:metrics_json AS jsonb),:artifact_reference,:evidence_checksum_sha256,:manual_review_required,:actor,now()) RETURNING *"
            ),
            values,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "DESIGN_AUDIT_CODE_CONFLICT", "Audit code already exists.", status_code=409
        ) from exc
    item = _row(result.one())
    await _audit(
        session,
        actor_id,
        "design.audits.created",
        "ui_audit_run",
        item["id"],
        {"audit_type": item["audit_type"], "status": item["status"]},
    )
    await session.commit()
    return item


async def review_audit(
    session: AsyncSession, actor_id: UUID, audit_id: UUID, decision: str, reason: str
) -> dict[str, Any]:
    current = (
        await session.execute(
            text("SELECT * FROM ui_audit_runs WHERE id=:id FOR UPDATE"), {"id": audit_id}
        )
    ).first()
    if current is None:
        raise VavError("DESIGN_AUDIT_NOT_FOUND", "Audit run was not found.", status_code=404)
    item = _row(current)
    if item["ran_by"] == actor_id:
        raise VavError(
            "DESIGN_REVIEW_SEPARATION_REQUIRED",
            "Audit review requires an independent reviewer.",
            status_code=409,
        )
    if item["status"] not in {"technical_pass", "needs_review"}:
        raise VavError(
            "DESIGN_AUDIT_STATE_INVALID", "Only a reviewable audit can be decided.", status_code=409
        )
    if decision == "approve" and not item["evidence_checksum_sha256"]:
        raise VavError(
            "DESIGN_AUDIT_EVIDENCE_REQUIRED",
            "Approval requires checksum-bound evidence.",
            status_code=409,
        )
    target = "approved" if decision == "approve" else "failed"
    findings = list(item["findings"] or []) + [
        {"kind": "manual_review", "decision": decision, "reason": reason}
    ]
    result = await session.execute(
        text(
            "UPDATE ui_audit_runs SET status=:status,findings=CAST(:findings AS jsonb),reviewed_by=:actor,reviewed_at=now() WHERE id=:id RETURNING *"
        ),
        {"status": target, "findings": _json(findings), "actor": actor_id, "id": audit_id},
    )
    reviewed = _row(result.one())
    await _audit(
        session, actor_id, f"design.audits.{target}", "ui_audit_run", audit_id, {"reason": reason}
    )
    await session.commit()
    return reviewed


async def list_baselines(session: AsyncSession) -> list[dict[str, Any]]:
    return await _all(session, "ui_visual_baselines", "created_at DESC,id")


async def create_baseline(
    session: AsyncSession, actor_id: UUID, payload: BaselineCreate
) -> dict[str, Any]:
    values = payload.model_dump(mode="json") | {"actor": actor_id}
    try:
        result = await session.execute(
            text(
                "INSERT INTO ui_visual_baselines (baseline_code,application_code,route_path,viewport,theme,locale,density,artifact_reference,checksum_sha256,created_by) VALUES (:baseline_code,:application_code,:route_path,:viewport,:theme,:locale,:density,:artifact_reference,:checksum_sha256,:actor) RETURNING *"
            ),
            values,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "DESIGN_BASELINE_CONFLICT", "Visual baseline already exists.", status_code=409
        ) from exc
    item = _row(result.one())
    await _audit(session, actor_id, "design.baselines.created", "ui_visual_baseline", item["id"])
    await session.commit()
    return item


async def decide_baseline(
    session: AsyncSession, actor_id: UUID, baseline_id: UUID, decision: str, reason: str
) -> dict[str, Any]:
    current = (
        await session.execute(
            text("SELECT * FROM ui_visual_baselines WHERE id=:id FOR UPDATE"), {"id": baseline_id}
        )
    ).first()
    if current is None:
        raise VavError(
            "DESIGN_BASELINE_NOT_FOUND", "Visual baseline was not found.", status_code=404
        )
    item = _row(current)
    if item["status"] != "pending":
        raise VavError(
            "DESIGN_BASELINE_STATE_INVALID",
            "Only a pending baseline can be decided.",
            status_code=409,
        )
    if item["created_by"] == actor_id:
        raise VavError(
            "DESIGN_APPROVAL_SEPARATION_REQUIRED",
            "Baseline approval requires an independent reviewer.",
            status_code=409,
        )
    target = "approved" if decision == "approve" else "rejected"
    result = await session.execute(
        text(
            "UPDATE ui_visual_baselines SET status=:status,approved_by=:actor,approved_at=now() WHERE id=:id RETURNING *"
        ),
        {"status": target, "actor": actor_id, "id": baseline_id},
    )
    decided = _row(result.one())
    await _audit(
        session,
        actor_id,
        f"design.baselines.{target}",
        "ui_visual_baseline",
        baseline_id,
        {"reason": reason},
    )
    await session.commit()
    return decided


async def list_visual_differences(session: AsyncSession) -> list[dict[str, Any]]:
    return await _all(session, "ui_visual_differences", "created_at DESC,id")


async def list_evidence(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM quality_evidence WHERE source_system IN ('ui-quality','storybook','playwright') ORDER BY generated_at DESC,id"
            )
        )
    ).mappings()
    return [dict(item) for item in rows]


async def accept_evidence(
    session: AsyncSession, actor_id: UUID, evidence_id: UUID
) -> dict[str, Any]:
    source_system = await session.scalar(
        text("SELECT source_system FROM quality_evidence WHERE id=:id"), {"id": evidence_id}
    )
    if source_system not in {"ui-quality", "storybook", "playwright"}:
        raise VavError(
            "DESIGN_EVIDENCE_NOT_FOUND",
            "Design-system evidence was not found.",
            status_code=404,
        )
    from vav.modules.quality import service as quality_service

    return await quality_service.transition_evidence(session, actor_id, evidence_id, "accepted")


async def list_design_audit(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,actor_id,actor_type,action,subject_type,subject_id,context,occurred_at FROM audit_events WHERE action LIKE 'design.%' ORDER BY occurred_at DESC LIMIT 500"
            )
        )
    ).mappings()
    return [dict(item) for item in rows]
