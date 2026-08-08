# ruff: noqa: E501

"""Persistence services for the fail-closed quality control plane."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.quality.domain import (
    CAPABILITY_CODE_PATTERN,
    FLOW_CODE_PATTERN,
    GATE_CODE_PATTERN,
    REQUIREMENT_CODE_PATTERN,
    TRACE_RELATIONSHIPS,
    GateEnforcementLevel,
    GateOutcome,
    QualityGateStatus,
    QualityPolicyError,
    ReleaseQualityDecision,
    business_flow_complete,
    content_fingerprint,
    evaluate_gate_condition,
    release_decision,
    validate_capability_transition,
    validate_code,
    validate_requirement_transition,
    validate_waiver,
)
from vav.modules.quality.schemas import (
    BusinessFlowCreate,
    CapabilityCreate,
    EvidenceRegister,
    ExceptionScenarioCreate,
    GateDefinitionCreate,
    ReleaseEvaluationRequest,
    RequirementCreate,
    RiskCreate,
    TraceLinkCreate,
    TraceNodeCreate,
    WaiverRequest,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _policy_error(exc: QualityPolicyError) -> VavError:
    return VavError(exc.code, exc.message, status_code=409)


async def _audit(
    session: AsyncSession,
    actor_id: UUID,
    action: str,
    subject_type: str,
    subject_id: UUID | None,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events "
            "(actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,'admin',:action,:subject_type,:subject_id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "action": action,
            "subject_type": subject_type,
            "subject_id": str(subject_id) if subject_id else None,
            "context": _json(context or {}),
        },
    )


async def _list(session: AsyncSession, table: str, *, order_by: str) -> list[dict[str, Any]]:
    allowed = {
        "quality_requirements",
        "quality_capabilities",
        "quality_trace_nodes",
        "quality_trace_links",
        "quality_business_flows",
        "quality_exception_scenarios",
        "quality_gaps",
        "quality_risks",
        "quality_waivers",
        "quality_evidence",
        "quality_gate_definitions",
        "quality_gate_runs",
        "quality_release_evaluations",
        "quality_certifications",
    }
    if table not in allowed:
        raise ValueError("table is not allowlisted")
    rows = (await session.execute(text(f"SELECT * FROM {table} ORDER BY {order_by}"))).mappings()
    return [dict(item) for item in rows]


async def list_requirements(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_requirements", order_by="criticality,requirement_code")


async def create_requirement(
    session: AsyncSession, actor_id: UUID, payload: RequirementCreate
) -> dict[str, Any]:
    try:
        validate_code(payload.requirement_code, REQUIREMENT_CODE_PATTERN, "requirement")
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    values = payload.model_dump(mode="json")
    values.update(
        {
            "acceptance": _json(values.pop("acceptance_criteria")),
            "non_functional": _json(values.pop("non_functional_criteria")),
            "actor": str(actor_id),
            "fingerprint": content_fingerprint(payload.model_dump(mode="json")),
        }
    )
    result = await session.execute(
        text(
            "INSERT INTO quality_requirements "
            "(requirement_code,title,description,source_type,source_reference,source_version,"
            "requirement_type,business_domain,criticality,status,acceptance_criteria,"
            "non_functional_criteria,owner_team,parent_requirement_id,introduced_in_batch,"
            "target_release,created_by,content_fingerprint) VALUES "
            "(:requirement_code,:title,:description,:source_type,:source_reference,:source_version,"
            ":requirement_type,:business_domain,:criticality,'draft',CAST(:acceptance AS jsonb),"
            "CAST(:non_functional AS jsonb),:owner_team,:parent_requirement_id,"
            ":introduced_in_batch,:target_release,:actor,:fingerprint) RETURNING *"
        ),
        values,
    )
    created = _row(result.one())
    await _audit(
        session, actor_id, "quality.requirement.created", "quality_requirement", created["id"]
    )
    await session.commit()
    return created


async def transition_requirement(
    session: AsyncSession, requirement_id: UUID, actor_id: UUID, target: str
) -> dict[str, Any]:
    current = (
        await session.execute(
            text("SELECT * FROM quality_requirements WHERE id=:id FOR UPDATE"),
            {"id": requirement_id},
        )
    ).first()
    if current is None:
        raise VavError(
            "QUALITY_REQUIREMENT_NOT_FOUND", "Requirement was not found.", status_code=404
        )
    item = _row(current)
    try:
        validate_requirement_transition(item["status"], target)
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    if target == "approved" and item["created_by"] == actor_id:
        raise VavError(
            "QUALITY_APPROVAL_SEPARATION_REQUIRED",
            "Requirement approval requires an independent reviewer.",
            status_code=409,
        )
    result = await session.execute(
        text(
            "UPDATE quality_requirements SET status=CAST(:target AS varchar),updated_at=now(),"
            "approved_by=CASE WHEN CAST(:target AS varchar)='approved' THEN :actor ELSE approved_by END,"
            "approved_at=CASE WHEN CAST(:target AS varchar)='approved' THEN now() ELSE approved_at END "
            "WHERE id=:id RETURNING *"
        ),
        {"target": target, "actor": actor_id, "id": requirement_id},
    )
    updated = _row(result.one())
    await _audit(
        session,
        actor_id,
        f"quality.requirement.{target}",
        "quality_requirement",
        requirement_id,
    )
    await session.commit()
    return updated


async def list_capabilities(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_capabilities", order_by="module_code,capability_code")


async def upsert_capability(
    session: AsyncSession, actor_id: UUID, payload: CapabilityCreate
) -> dict[str, Any]:
    try:
        validate_code(payload.capability_code, CAPABILITY_CODE_PATTERN, "capability")
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    existing_status = await session.scalar(
        text("SELECT lifecycle_status FROM quality_capabilities WHERE capability_code=:code"),
        {"code": payload.capability_code},
    )
    if existing_status and existing_status != payload.lifecycle_status:
        try:
            validate_capability_transition(existing_status, payload.lifecycle_status)
        except QualityPolicyError as exc:
            raise _policy_error(exc) from exc
    values = payload.model_dump(mode="json") | {"actor": actor_id}
    result = await session.execute(
        text(
            "INSERT INTO quality_capabilities "
            "(capability_code,name,description,capability_type,module_code,criticality,"
            "lifecycle_status,owning_service,primary_actor_type,introduced_in_batch,current_version,"
            "owner_team,created_by) VALUES (:capability_code,:name,:description,:capability_type,"
            ":module_code,:criticality,:lifecycle_status,:owning_service,:primary_actor_type,"
            ":introduced_in_batch,:current_version,:owner_team,:actor) "
            "ON CONFLICT (capability_code) DO UPDATE SET name=EXCLUDED.name,"
            "description=EXCLUDED.description,capability_type=EXCLUDED.capability_type,"
            "module_code=EXCLUDED.module_code,criticality=EXCLUDED.criticality,"
            "lifecycle_status=EXCLUDED.lifecycle_status,owning_service=EXCLUDED.owning_service,"
            "primary_actor_type=EXCLUDED.primary_actor_type,current_version=EXCLUDED.current_version,"
            "owner_team=EXCLUDED.owner_team,updated_at=now() RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(
        session, actor_id, "quality.capability.registered", "quality_capability", item["id"]
    )
    await session.commit()
    return item


async def list_traceability(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": await _list(session, "quality_trace_nodes", order_by="node_type,node_code"),
        "links": await _list(session, "quality_trace_links", order_by="created_at,id"),
    }


async def create_trace_node(
    session: AsyncSession, actor_id: UUID, payload: TraceNodeCreate
) -> dict[str, Any]:
    values = payload.model_dump(mode="json")
    values["metadata_json"] = _json(values.pop("metadata"))
    result = await session.execute(
        text(
            "INSERT INTO quality_trace_nodes "
            "(node_type,node_code,module_code,title,source_location,version,status,metadata) "
            "VALUES (:node_type,:node_code,:module_code,:title,:source_location,:version,:status,"
            "CAST(:metadata_json AS jsonb)) ON CONFLICT (node_type,node_code,version) DO UPDATE SET "
            "module_code=EXCLUDED.module_code,title=EXCLUDED.title,source_location=EXCLUDED.source_location,"
            "status=EXCLUDED.status,metadata=EXCLUDED.metadata,updated_at=now() RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(
        session, actor_id, "quality.traceability.node_synced", "quality_trace_node", item["id"]
    )
    await session.commit()
    return item


async def create_trace_link(
    session: AsyncSession, actor_id: UUID, payload: TraceLinkCreate
) -> dict[str, Any]:
    if payload.relationship_type not in TRACE_RELATIONSHIPS:
        raise VavError(
            "QUALITY_TRACE_RELATIONSHIP_INVALID",
            "Trace relationship is not allowed.",
            status_code=422,
        )
    result = await session.execute(
        text(
            "INSERT INTO quality_trace_links "
            "(source_node_id,target_node_id,relationship_type,required,status,verification_method) "
            "VALUES (:source_node_id,:target_node_id,:relationship_type,:required,'unverified',"
            ":verification_method) ON CONFLICT (source_node_id,target_node_id,relationship_type) "
            "DO UPDATE SET required=EXCLUDED.required,verification_method=EXCLUDED.verification_method "
            "RETURNING *"
        ),
        payload.model_dump(),
    )
    item = _row(result.one())
    await _audit(session, actor_id, "quality.traceability.linked", "quality_trace_link", item["id"])
    await session.commit()
    return item


async def verify_trace_link(session: AsyncSession, actor_id: UUID, link_id: UUID) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_trace_links SET status='verified',verified_by=:actor,verified_at=now() "
            "WHERE id=:id RETURNING *"
        ),
        {"actor": actor_id, "id": link_id},
    )
    row = result.first()
    if row is None:
        raise VavError("QUALITY_TRACE_LINK_NOT_FOUND", "Trace link was not found.", status_code=404)
    item = _row(row)
    await _audit(session, actor_id, "quality.traceability.verified", "quality_trace_link", link_id)
    await session.commit()
    return item


async def list_business_flows(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_business_flows", order_by="criticality,flow_code")


async def create_business_flow(
    session: AsyncSession, actor_id: UUID, payload: BusinessFlowCreate
) -> dict[str, Any]:
    try:
        validate_code(payload.flow_code, FLOW_CODE_PATTERN, "business flow")
        complete = business_flow_complete(payload.closure_checks)
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    values = payload.model_dump(mode="json")
    for field in (
        "supporting_actor_types",
        "start_condition",
        "success_end_conditions",
        "failure_end_conditions",
        "cancellation_conditions",
        "closure_checks",
    ):
        values[f"{field}_json"] = _json(values.pop(field))
    values["status"] = "complete" if complete else "incomplete"
    result = await session.execute(
        text(
            "INSERT INTO quality_business_flows "
            "(flow_code,name,business_domain,criticality,primary_actor_type,supporting_actor_types,"
            "start_condition,success_end_conditions,failure_end_conditions,cancellation_conditions,"
            "closure_checks,manual_intervention_supported,compensation_required,owner_team,status) "
            "VALUES (:flow_code,:name,:business_domain,:criticality,:primary_actor_type,"
            "CAST(:supporting_actor_types_json AS jsonb),CAST(:start_condition_json AS jsonb),"
            "CAST(:success_end_conditions_json AS jsonb),CAST(:failure_end_conditions_json AS jsonb),"
            "CAST(:cancellation_conditions_json AS jsonb),CAST(:closure_checks_json AS jsonb),"
            ":manual_intervention_supported,:compensation_required,:owner_team,:status) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(
        session, actor_id, "quality.business_flow.created", "quality_business_flow", item["id"]
    )
    await session.commit()
    return item


async def certify_business_flow(
    session: AsyncSession, actor_id: UUID, flow_id: UUID
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_business_flows SET status='certified',certified_by=:actor,"
            "certified_at=now(),updated_at=now() WHERE id=:id AND status='complete' RETURNING *"
        ),
        {"actor": actor_id, "id": flow_id},
    )
    row = result.first()
    if row is None:
        raise VavError(
            "QUALITY_FLOW_NOT_CERTIFIABLE",
            "Only a complete business flow can be certified.",
            status_code=409,
        )
    item = _row(row)
    await _audit(
        session, actor_id, "quality.business_flow.certified", "quality_business_flow", flow_id
    )
    await session.commit()
    return item


async def create_exception_scenario(
    session: AsyncSession, actor_id: UUID, payload: ExceptionScenarioCreate
) -> dict[str, Any]:
    values = payload.model_dump(mode="json")
    values["trigger"] = _json(values.pop("trigger_condition"))
    result = await session.execute(
        text(
            "INSERT INTO quality_exception_scenarios "
            "(scenario_code,business_flow_id,exception_type,trigger_condition,expected_business_state,"
            "expected_user_message_code,expected_admin_action,compensation_expected,retry_expected,criticality) "
            "VALUES (:scenario_code,:business_flow_id,:exception_type,CAST(:trigger AS jsonb),"
            ":expected_business_state,:expected_user_message_code,:expected_admin_action,"
            ":compensation_expected,:retry_expected,:criticality) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "quality.exception.created", "quality_exception", item["id"])
    await session.commit()
    return item


async def list_gaps(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_gaps", order_by="severity,status,detected_at DESC")


async def assign_gap(
    session: AsyncSession,
    actor_id: UUID,
    gap_id: UUID,
    owner_team: str,
    owner_user_id: UUID | None,
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_gaps SET status='assigned',owner_team=:team,owner_user_id=:owner "
            "WHERE id=:id AND status<>'resolved' RETURNING *"
        ),
        {"team": owner_team, "owner": owner_user_id, "id": gap_id},
    )
    row = result.first()
    if row is None:
        raise VavError("QUALITY_GAP_NOT_ASSIGNABLE", "Gap cannot be assigned.", status_code=409)
    item = _row(row)
    await _audit(session, actor_id, "quality.gap.assigned", "quality_gap", gap_id)
    await session.commit()
    return item


async def resolve_gap(
    session: AsyncSession, actor_id: UUID, gap_id: UUID, resolution_summary: str
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_gaps SET status='resolved',resolved_at=now(),resolution_summary=:summary "
            "WHERE id=:id AND status<>'resolved' RETURNING *"
        ),
        {"summary": resolution_summary, "id": gap_id},
    )
    row = result.first()
    if row is None:
        raise VavError("QUALITY_GAP_NOT_RESOLVABLE", "Gap cannot be resolved.", status_code=409)
    item = _row(row)
    await _audit(session, actor_id, "quality.gap.resolved", "quality_gap", gap_id)
    await session.commit()
    return item


async def list_risks(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_risks", order_by="severity,status,risk_code")


async def create_risk(session: AsyncSession, actor_id: UUID, payload: RiskCreate) -> dict[str, Any]:
    values = payload.model_dump(mode="json")
    values["requirements"] = _json(values.pop("affected_requirements"))
    values["capabilities"] = _json(values.pop("affected_capabilities"))
    result = await session.execute(
        text(
            "INSERT INTO quality_risks "
            "(risk_code,title,description,category,severity,likelihood,affected_requirements,"
            "affected_capabilities,mitigation_plan,contingency_plan,owner_user_id,owner_team,status,"
            "target_resolution_date) VALUES (:risk_code,:title,:description,:category,:severity,"
            ":likelihood,CAST(:requirements AS jsonb),CAST(:capabilities AS jsonb),:mitigation_plan,"
            ":contingency_plan,:owner_user_id,:owner_team,'open',:target_resolution_date) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "quality.risk.created", "quality_risk", item["id"])
    await session.commit()
    return item


async def list_waivers(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_waivers", order_by="created_at DESC,id")


async def request_waiver(
    session: AsyncSession, actor_id: UUID, payload: WaiverRequest
) -> dict[str, Any]:
    if not any((payload.gate_definition_id, payload.quality_gap_id, payload.quality_risk_id)):
        raise VavError(
            "QUALITY_WAIVER_SUBJECT_REQUIRED",
            "A waiver must reference a gate, gap or risk.",
            status_code=422,
        )
    if payload.expires_at <= payload.valid_from:
        raise VavError(
            "QUALITY_WAIVER_EXPIRY_INVALID", "Waiver expiry is invalid.", status_code=422
        )
    settings = get_settings()
    if (payload.expires_at - payload.valid_from).days > settings.quality_waiver_max_days:
        raise VavError(
            "QUALITY_WAIVER_EXPIRY_INVALID", "Waiver duration is too long.", status_code=422
        )
    waiver_number = f"WV-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12]}"
    values = payload.model_dump() | {
        "number": waiver_number,
        "mitigation": _json(payload.mitigation_conditions),
        "scope_json": _json(payload.scope),
        "actor": actor_id,
    }
    result = await session.execute(
        text(
            "INSERT INTO quality_waivers "
            "(waiver_number,gate_definition_id,quality_gap_id,quality_risk_id,justification,"
            "mitigation_conditions,scope,status,requested_by,valid_from,expires_at) VALUES "
            "(:number,:gate_definition_id,:quality_gap_id,:quality_risk_id,:justification,"
            "CAST(:mitigation AS jsonb),CAST(:scope_json AS jsonb),'requested',:actor,:valid_from,"
            ":expires_at) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "quality.waiver.requested", "quality_waiver", item["id"])
    await session.commit()
    return item


async def approve_waiver(session: AsyncSession, actor_id: UUID, waiver_id: UUID) -> dict[str, Any]:
    current = (
        await session.execute(
            text(
                "SELECT w.*,g.gate_code FROM quality_waivers w LEFT JOIN quality_gate_definitions g "
                "ON g.id=w.gate_definition_id WHERE w.id=:id FOR UPDATE OF w"
            ),
            {"id": waiver_id},
        )
    ).first()
    if current is None:
        raise VavError("QUALITY_WAIVER_NOT_FOUND", "Waiver was not found.", status_code=404)
    item = _row(current)
    if item["status"] != "requested":
        raise VavError("QUALITY_WAIVER_STATE_INVALID", "Waiver is not pending.", status_code=409)
    try:
        validate_waiver(
            gate_code=item["gate_code"] or "GATE-OTHER",
            requested_by=str(item["requested_by"]),
            approved_by=str(actor_id),
            valid_from=item["valid_from"],
            expires_at=item["expires_at"],
            mitigation_conditions=item["mitigation_conditions"],
            max_days=get_settings().quality_waiver_max_days,
        )
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    result = await session.execute(
        text(
            "UPDATE quality_waivers SET status='approved',approved_by=:actor,approved_at=now() "
            "WHERE id=:id RETURNING *"
        ),
        {"actor": actor_id, "id": waiver_id},
    )
    approved = _row(result.one())
    await _audit(session, actor_id, "quality.waiver.approved", "quality_waiver", waiver_id)
    await session.commit()
    return approved


async def revoke_waiver(session: AsyncSession, actor_id: UUID, waiver_id: UUID) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_waivers SET status='revoked',revoked_at=now() "
            "WHERE id=:id AND status='approved' RETURNING *"
        ),
        {"id": waiver_id},
    )
    row = result.first()
    if row is None:
        raise VavError("QUALITY_WAIVER_STATE_INVALID", "Waiver is not active.", status_code=409)
    item = _row(row)
    await _audit(session, actor_id, "quality.waiver.revoked", "quality_waiver", waiver_id)
    await session.commit()
    return item


async def list_evidence(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await _list(session, "quality_evidence", order_by="created_at DESC,id")
    for item in rows:
        item["artifact_reference_encrypted"] = bool(item["artifact_reference_encrypted"])
    return rows


async def register_evidence(
    session: AsyncSession, actor_id: UUID, payload: EvidenceRegister
) -> dict[str, Any]:
    if payload.artifact_reference and not payload.artifact_checksum_sha256:
        raise VavError(
            "QUALITY_EVIDENCE_CHECKSUM_REQUIRED",
            "Artifact evidence requires a SHA-256 checksum.",
            status_code=422,
        )
    if payload.expires_at and payload.expires_at <= payload.generated_at:
        raise VavError(
            "QUALITY_EVIDENCE_EXPIRY_INVALID", "Evidence expiry is invalid.", status_code=422
        )
    values = payload.model_dump() | {
        "type": payload.evidence_type.value,
        "artifact": encrypt_private(payload.artifact_reference)
        if payload.artifact_reference
        else None,
        "summary_json": _json(payload.summary),
        "actor": actor_id,
    }
    result = await session.execute(
        text(
            "INSERT INTO quality_evidence "
            "(evidence_code,evidence_type,title,source_system,source_reference,release_version,"
            "git_commit,environment,status,artifact_reference_encrypted,artifact_checksum_sha256,"
            "summary,generated_at,expires_at,registered_by) VALUES (:evidence_code,:type,:title,"
            ":source_system,:source_reference,:release_version,:git_commit,:environment,'registered',"
            ":artifact,:artifact_checksum_sha256,CAST(:summary_json AS jsonb),:generated_at,:expires_at,"
            ":actor) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    item["artifact_reference_encrypted"] = bool(item["artifact_reference_encrypted"])
    await _audit(session, actor_id, "quality.evidence.registered", "quality_evidence", item["id"])
    await session.commit()
    return item


async def transition_evidence(
    session: AsyncSession, actor_id: UUID, evidence_id: UUID, target: str
) -> dict[str, Any]:
    expected = "registered" if target == "validated" else "validated"
    result = await session.execute(
        text(
            "UPDATE quality_evidence SET status=CAST(:target AS varchar),"
            "validated_by=CASE WHEN CAST(:target AS varchar)='validated' "
            "THEN :actor ELSE validated_by END "
            "WHERE id=:id AND status=CAST(:expected AS varchar) AND registered_by<>:actor "
            "AND (expires_at IS NULL OR expires_at>now()) RETURNING *"
        ),
        {"target": target, "actor": actor_id, "id": evidence_id, "expected": expected},
    )
    row = result.first()
    if row is None:
        raise VavError(
            "QUALITY_EVIDENCE_NOT_TRANSITIONABLE",
            "Evidence is expired, in the wrong state, or lacks independent validation.",
            status_code=409,
        )
    item = _row(row)
    item["artifact_reference_encrypted"] = bool(item["artifact_reference_encrypted"])
    await _audit(session, actor_id, f"quality.evidence.{target}", "quality_evidence", evidence_id)
    await session.commit()
    return item


async def list_gates(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(
        session, "quality_gate_definitions", order_by="gate_code,semantic_version DESC"
    )


async def create_gate(
    session: AsyncSession, actor_id: UUID, payload: GateDefinitionCreate
) -> dict[str, Any]:
    try:
        validate_code(payload.gate_code, GATE_CODE_PATTERN, "gate")
        evaluate_gate_condition(
            payload.condition_definition, payload.condition_definition["expected"]
        )
    except QualityPolicyError as exc:
        raise _policy_error(exc) from exc
    values = payload.model_dump(mode="json") | {
        "condition": _json(payload.condition_definition),
        "evidence": _json([item.value for item in payload.required_evidence_types]),
        "release_types": _json(payload.applicable_release_types),
        "modules": _json(payload.applicable_modules),
        "actor": actor_id,
    }
    result = await session.execute(
        text(
            "INSERT INTO quality_gate_definitions "
            "(gate_code,semantic_version,name,category,enforcement_level,condition_definition,"
            "required_evidence_types,applicable_release_types,applicable_modules,status,created_by) "
            "VALUES (:gate_code,:semantic_version,:name,:category,:enforcement_level,"
            "CAST(:condition AS jsonb),CAST(:evidence AS jsonb),CAST(:release_types AS jsonb),"
            "CAST(:modules AS jsonb),'draft',:actor) RETURNING *"
        ),
        values,
    )
    item = _row(result.one())
    await _audit(session, actor_id, "quality.gate.created", "quality_gate", item["id"])
    await session.commit()
    return item


async def list_gate_runs(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_gate_runs", order_by="started_at DESC,id")


async def approve_gate(session: AsyncSession, actor_id: UUID, gate_id: UUID) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE quality_gate_definitions SET status='active',approved_by=:actor,approved_at=now() "
            "WHERE id=:id AND status='draft' AND created_by<>:actor RETURNING *"
        ),
        {"actor": actor_id, "id": gate_id},
    )
    row = result.first()
    if row is None:
        raise VavError(
            "QUALITY_GATE_APPROVAL_REJECTED",
            "Gate approval requires a draft and an independent approver.",
            status_code=409,
        )
    item = _row(row)
    await _audit(session, actor_id, "quality.gate.approved", "quality_gate", gate_id)
    await session.commit()
    return item


async def _active_waiver(
    session: AsyncSession, gate_id: UUID, release: str, environment: str
) -> UUID | None:
    rows = (
        await session.execute(
            text(
                "SELECT id,scope FROM quality_waivers WHERE gate_definition_id=:gate "
                "AND status='approved' AND valid_from<=now() AND expires_at>now()"
            ),
            {"gate": gate_id},
        )
    ).mappings()
    for waiver in rows:
        scope = waiver["scope"]
        if scope.get("release_version") == release and scope.get("environment") == environment:
            return UUID(str(waiver["id"]))
    return None


async def evaluate_release(
    session: AsyncSession,
    actor_id: UUID,
    release_version: str,
    payload: ReleaseEvaluationRequest,
) -> dict[str, Any]:
    gate_rows = (
        (
            await session.execute(
                text(
                    "SELECT * FROM quality_gate_definitions WHERE status='active' ORDER BY gate_code"
                )
            )
        )
        .mappings()
        .all()
    )
    outcomes: list[GateOutcome] = []
    run_ids: list[str] = []
    failure_reasons: list[str] = []
    if payload.environment == "production":
        blockers = (
            (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM quality_requirements WHERE criticality IN ('blocker','critical') "
                        "AND status<>'verified') AS requirements_unverified,"
                        "(SELECT count(*) FROM quality_gaps WHERE severity IN ('blocker','critical') "
                        "AND status<>'resolved') AS gaps_open,"
                        "(SELECT count(*) FROM quality_risks WHERE severity IN ('blocker','critical') "
                        "AND status<>'closed') AS risks_open,"
                        "(SELECT count(*) FROM quality_business_flows WHERE criticality IN ('blocker','critical') "
                        "AND status<>'certified') AS flows_uncertified"
                    )
                )
            )
            .mappings()
            .one()
        )
        for metric, value in blockers.items():
            if value:
                outcomes.append(
                    GateOutcome(
                        code=f"GATE-PREFLIGHT-{metric.upper()}",
                        enforcement=GateEnforcementLevel.BLOCKER,
                        status=QualityGateStatus.FAILED,
                    )
                )
                failure_reasons.append(f"GATE-PREFLIGHT-{metric.upper()}:{value}")
    applicable_gate_count = 0
    for gate in gate_rows:
        if payload.release_type not in gate["applicable_release_types"]:
            continue
        applicable_gate_count += 1
        evidence_rows = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM quality_evidence WHERE release_version=:release AND git_commit=:commit "
                        "AND environment=:environment AND status='accepted' "
                        "AND (expires_at IS NULL OR expires_at>now()) ORDER BY generated_at DESC"
                    ),
                    {
                        "release": release_version,
                        "commit": payload.git_commit,
                        "environment": payload.environment,
                    },
                )
            )
            .mappings()
            .all()
        )
        allowed = set(gate["required_evidence_types"])
        evidence = [item for item in evidence_rows if item["evidence_type"] in allowed]
        condition = gate["condition_definition"]
        metric = condition["metric"]
        observed = next(
            (item["summary"][metric] for item in evidence if metric in item["summary"]), None
        )
        passed = False
        reasons: list[str] = []
        if observed is None:
            reasons.append("required_current_evidence_missing")
        else:
            try:
                passed = evaluate_gate_condition(condition, observed)
            except QualityPolicyError as exc:
                reasons.append(exc.code.lower())
        waiver_id = (
            None
            if passed
            else await _active_waiver(session, gate["id"], release_version, payload.environment)
        )
        status = (
            QualityGateStatus.PASSED
            if passed
            else (QualityGateStatus.WAIVED if waiver_id else QualityGateStatus.FAILED)
        )
        outcome = GateOutcome(
            code=gate["gate_code"],
            enforcement=GateEnforcementLevel(gate["enforcement_level"]),
            status=status,
            waiver_valid=waiver_id is not None,
        )
        outcomes.append(outcome)
        if status is not QualityGateStatus.PASSED:
            failure_reasons.extend(
                f"{gate['gate_code']}:{reason}" for reason in reasons or [status.value]
            )
        run = await session.execute(
            text(
                "INSERT INTO quality_gate_runs "
                "(gate_definition_id,release_version,git_commit,environment,status,evaluated_value,"
                "expected_condition,evidence_ids,failure_reasons,waiver_id,completed_at,triggered_by) "
                "VALUES (:gate,:release,:commit,:environment,:status,CAST(:observed AS jsonb),"
                "CAST(:condition AS jsonb),CAST(:evidence AS jsonb),CAST(:reasons AS jsonb),:waiver,"
                "now(),:actor) ON CONFLICT (gate_definition_id,release_version,environment) DO UPDATE "
                "SET git_commit=EXCLUDED.git_commit,status=EXCLUDED.status,"
                "evaluated_value=EXCLUDED.evaluated_value,expected_condition=EXCLUDED.expected_condition,"
                "evidence_ids=EXCLUDED.evidence_ids,failure_reasons=EXCLUDED.failure_reasons,"
                "waiver_id=EXCLUDED.waiver_id,started_at=now(),completed_at=now(),"
                "triggered_by=EXCLUDED.triggered_by RETURNING id"
            ),
            {
                "gate": gate["id"],
                "release": release_version,
                "commit": payload.git_commit,
                "environment": payload.environment,
                "status": status.value,
                "observed": _json(observed),
                "condition": _json(condition),
                "evidence": _json([str(item["id"]) for item in evidence]),
                "reasons": _json(reasons),
                "waiver": waiver_id,
                "actor": actor_id,
            },
        )
        run_ids.append(str(run.scalar_one()))
    if applicable_gate_count == 0:
        outcomes.append(
            GateOutcome(
                code="GATE-DEFINITIONS-PRESENT",
                enforcement=GateEnforcementLevel.BLOCKER,
                status=QualityGateStatus.FAILED,
            )
        )
        failure_reasons.append("GATE-DEFINITIONS-PRESENT:no_applicable_approved_gate")
    decision = release_decision(outcomes)
    score = (
        round(
            (
                sum(item.status is QualityGateStatus.PASSED for item in outcomes)
                / len(outcomes)
                * 100
            ),
            2,
        )
        if outcomes
        else 0.0
    )
    result = await session.execute(
        text(
            "INSERT INTO quality_release_evaluations "
            "(release_version,git_commit,environment,decision,structural_score,gate_run_ids,"
            "failure_reasons,evaluated_by) VALUES (:release,:commit,:environment,:decision,:score,"
            "CAST(:runs AS jsonb),CAST(:reasons AS jsonb),:actor) "
            "ON CONFLICT (release_version,environment) DO UPDATE SET git_commit=EXCLUDED.git_commit,"
            "decision=EXCLUDED.decision,structural_score=EXCLUDED.structural_score,"
            "gate_run_ids=EXCLUDED.gate_run_ids,failure_reasons=EXCLUDED.failure_reasons,"
            "evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now() RETURNING *"
        ),
        {
            "release": release_version,
            "commit": payload.git_commit,
            "environment": payload.environment,
            "decision": decision.value,
            "score": score,
            "runs": _json(run_ids),
            "reasons": _json(failure_reasons),
            "actor": actor_id,
        },
    )
    item = _row(result.one())
    await _audit(
        session,
        actor_id,
        "quality.release.decided",
        "quality_release_evaluation",
        item["id"],
        {"decision": decision.value, "git_commit": payload.git_commit},
    )
    await session.commit()
    return item


async def list_releases(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_release_evaluations", order_by="evaluated_at DESC,id")


async def list_certifications(session: AsyncSession) -> list[dict[str, Any]]:
    return await _list(session, "quality_certifications", order_by="certified_at DESC,id")


async def list_quality_audit(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,actor_id,actor_type,action,subject_type,subject_id,context,occurred_at "
                "FROM audit_events WHERE action LIKE 'quality.%' ORDER BY occurred_at DESC LIMIT 500"
            )
        )
    ).mappings()
    return [dict(item) for item in rows]


async def release_detail(
    session: AsyncSession, release_version: str, environment: str
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "SELECT r.*,c.certification_status,c.evidence_manifest,c.certified_by,c.certified_at "
            "FROM quality_release_evaluations r LEFT JOIN quality_certifications c "
            "ON c.release_evaluation_id=r.id WHERE r.release_version=:release AND r.environment=:environment"
        ),
        {"release": release_version, "environment": environment},
    )
    row = result.first()
    if row is None:
        raise VavError(
            "QUALITY_RELEASE_NOT_FOUND", "Release evaluation was not found.", status_code=404
        )
    return _row(row)


async def certify_release(
    session: AsyncSession,
    actor_id: UUID,
    release_version: str,
    environment: str,
    evidence_manifest: dict[str, Any],
) -> dict[str, Any]:
    current = (
        await session.execute(
            text(
                "SELECT * FROM quality_release_evaluations WHERE release_version=:release "
                "AND environment=:environment FOR UPDATE"
            ),
            {"release": release_version, "environment": environment},
        )
    ).first()
    if current is None:
        raise VavError(
            "QUALITY_RELEASE_NOT_FOUND", "Release evaluation was not found.", status_code=404
        )
    release = _row(current)
    if release["decision"] != ReleaseQualityDecision.GO.value:
        raise VavError(
            "QUALITY_RELEASE_NOT_CERTIFIABLE",
            "Only a GO release can be certified; conditional production release is rejected.",
            status_code=409,
        )
    if release["evaluated_by"] == actor_id:
        raise VavError(
            "QUALITY_CERTIFICATION_SEPARATION_REQUIRED",
            "Certification requires an independent reviewer.",
            status_code=409,
        )
    if not evidence_manifest:
        raise VavError(
            "QUALITY_CERTIFICATION_EVIDENCE_REQUIRED",
            "Certification requires an evidence manifest.",
            status_code=422,
        )
    raw_evidence_ids = evidence_manifest.get("evidence_ids")
    if not isinstance(raw_evidence_ids, list) or not raw_evidence_ids:
        raise VavError(
            "QUALITY_CERTIFICATION_EVIDENCE_REQUIRED",
            "Certification evidence manifest requires evidence_ids.",
            status_code=422,
        )
    try:
        evidence_ids = [UUID(str(item)) for item in raw_evidence_ids]
    except ValueError as exc:
        raise VavError(
            "QUALITY_CERTIFICATION_EVIDENCE_INVALID",
            "Certification evidence identifiers are invalid.",
            status_code=422,
        ) from exc
    accepted_count = await session.scalar(
        text(
            "SELECT count(*) FROM quality_evidence WHERE id=ANY(:ids) AND status='accepted' "
            "AND release_version=:release AND git_commit=:commit AND environment=:environment "
            "AND (expires_at IS NULL OR expires_at>now())"
        ),
        {
            "ids": evidence_ids,
            "release": release_version,
            "commit": release["git_commit"],
            "environment": environment,
        },
    )
    if accepted_count != len(set(evidence_ids)):
        raise VavError(
            "QUALITY_CERTIFICATION_EVIDENCE_INVALID",
            "Every certification artifact must be accepted, current and bound to this release.",
            status_code=409,
        )
    result = await session.execute(
        text(
            "INSERT INTO quality_certifications "
            "(release_evaluation_id,certification_status,evidence_manifest,certified_by) "
            "VALUES (:evaluation,'certified',CAST(:manifest AS jsonb),:actor) RETURNING *"
        ),
        {"evaluation": release["id"], "manifest": _json(evidence_manifest), "actor": actor_id},
    )
    item = _row(result.one())
    await _audit(
        session, actor_id, "quality.release.certified", "quality_certification", item["id"]
    )
    await session.commit()
    return item


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    result = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM quality_requirements) AS requirements_total,"
                "(SELECT count(*) FROM quality_requirements WHERE status='verified') AS requirements_verified,"
                "(SELECT count(*) FROM quality_capabilities WHERE lifecycle_status='available') AS capabilities,"
                "(SELECT count(*) FROM quality_gaps WHERE status<>'resolved') AS gaps_open,"
                "(SELECT count(*) FROM quality_gaps WHERE status<>'resolved' AND severity IN ('blocker','critical')) "
                "AS critical_gaps_open,"
                "(SELECT count(*) FROM quality_risks WHERE status<>'closed') AS risks_open,"
                "(SELECT count(*) FROM quality_waivers WHERE status='approved' AND expires_at>now()) AS waivers_active,"
                "(SELECT count(*) FROM quality_gate_runs WHERE status='failed') AS gate_failures,"
                "(SELECT count(*) FROM quality_release_evaluations WHERE decision='no_go') AS releases_no_go"
            )
        )
    ).one()
    item = _row(result)
    total = item["requirements_total"]
    item["requirement_verification_ratio"] = (
        round(item["requirements_verified"] / total, 4) if total else 0.0
    )
    item["release_allowed"] = item["critical_gaps_open"] == 0 and item["gate_failures"] == 0
    return item
