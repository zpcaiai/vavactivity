# ruff: noqa: B008, E501
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.privacy.schemas import (
    AdminDecisionRequest,
    BreakGlassRequest,
    LegalHoldRequest,
    StatusReasonRequest,
)
from vav.modules.privacy.service import (
    audit,
    create_erasure_plan,
    execute_erasure_plan,
    json_value,
    process_export_request,
    request_number,
    utcnow,
)

router = APIRouter()


class ConsentDefinitionRequest(BaseModel):
    consent_code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    category: str = Field(min_length=2, max_length=64)
    required_for_service: bool
    withdrawable: bool
    scope_definition: dict[str, Any]
    evidence_requirements: dict[str, Any]


class ConsentReleaseRequest(BaseModel):
    semantic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    locale: str = Field(pattern=r"^(zh-CN|zh-TW|en)$")
    title: str = Field(min_length=3, max_length=300)
    summary: str = Field(min_length=3, max_length=20_000)
    valid_from: str


class RetentionPolicyRequest(BaseModel):
    policy_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    semantic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    data_category: str = Field(min_length=2, max_length=64)
    module_code: str = Field(min_length=2, max_length=64)
    trigger_event: str = Field(min_length=3, max_length=128)
    retention_days: int = Field(ge=1, le=36500)
    expiration_action: str = Field(
        pattern=r"^(delete|anonymize|pseudonymize|archive_restricted|manual_review)$"
    )
    policy_basis: str = Field(min_length=8, max_length=4000)


@router.get("/admin/privacy/dashboard")
async def dashboard(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.requests.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_rows = list(
        (
            await session.execute(
                text(
                    "SELECT request_type,status,count(*) AS count FROM data_subject_requests GROUP BY request_type,status"
                )
            )
        )
        .mappings()
        .all()
    )
    blocked = await session.scalar(
        text(
            "SELECT count(*) FROM privacy_erasure_plans WHERE status IN ('blocked_by_active_service','blocked_by_hold')"
        )
    )
    active_holds = await session.scalar(
        text(
            "SELECT count(*) FROM privacy_legal_holds WHERE status='active' AND starts_at<=now() AND (ends_at IS NULL OR ends_at>now())"
        )
    )
    break_glass = await session.scalar(
        text("SELECT count(*) FROM privacy_break_glass_access WHERE status='requested'")
    )
    due_retention = await session.scalar(
        text(
            "SELECT count(*) FROM privacy_retention_instances WHERE status='active' AND expires_at<=now()"
        )
    )
    return success(
        {
            "requests": [dict(row) for row in request_rows],
            "blocked_erasures": int(blocked or 0),
            "active_holds": int(active_holds or 0),
            "break_glass_pending": int(break_glass or 0),
            "retention_due": int(due_retention or 0),
            "sensitive_content_redacted": True,
        },
        request_id_from_request(request),
    )


@router.get("/admin/privacy/requests")
async def list_requests(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.requests.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,request_number,('user-'||left(user_id::text,8)) AS user_anonymous_id,request_type,status,identity_verification_level,identity_verified_at,submitted_at,due_at,assigned_to,decision_code,decision_reason_safe,completed_at FROM data_subject_requests ORDER BY created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/requests/{privacy_request_id}")
async def request_detail(
    privacy_request_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.requests.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,request_number,('user-'||left(user_id::text,8)) AS user_anonymous_id,request_type,status,requested_scope,requested_format,identity_verification_level,identity_verified_at,submitted_at,due_at,assigned_to,decision_code,decision_reason_safe,completed_at FROM data_subject_requests WHERE id=:id"
                ),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "PRIVACY_REQUEST_NOT_FOUND", "Privacy request was not found.", status_code=404
        )
    modules = [
        dict(item)
        for item in (
            await session.execute(
                text(
                    "SELECT module_code,operation,status,schema_version,result_manifest,error_code,attempts,completed_at FROM privacy_module_request_results WHERE data_subject_request_id=:id ORDER BY module_code"
                ),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .all()
    ]
    plan = (
        (
            await session.execute(
                text(
                    "SELECT id,status,module_plans,blocking_conditions,retention_exceptions,user_confirmation_required,user_confirmed_at,planned_at,approved_at,execution_started_at,completed_at FROM privacy_erasure_plans WHERE data_subject_request_id=:id"
                ),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .first()
    )
    events = [
        dict(item)
        for item in (
            await session.execute(
                text(
                    "SELECT event_type,safe_context,created_at FROM privacy_request_events WHERE data_subject_request_id=:id ORDER BY created_at"
                ),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {
            **dict(row),
            "module_results": modules,
            "erasure_plan": dict(plan) if plan else None,
            "timeline": events,
            "full_sensitive_values_loaded": False,
        },
        request_id_from_request(request),
    )


async def request_transition(
    privacy_request_id: UUID,
    target: str,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    allowed = {
        "verified": {"submitted", "identity_verification_required"},
        "approved": {"verified", "in_review", "waiting_for_user"},
        "rejected": {"submitted", "verified", "in_review", "waiting_for_user"},
    }
    row = (
        (
            await session.execute(
                text("SELECT status FROM data_subject_requests WHERE id=:id FOR UPDATE"),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["status"] not in allowed[target]:
        raise VavError(
            "PRIVACY_REQUEST_TRANSITION_INVALID",
            "Privacy request transition is invalid.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE data_subject_requests SET status=:status,identity_verified_at=CASE WHEN :status='verified' THEN now() ELSE identity_verified_at END,decision_code=CASE WHEN :status IN ('approved','rejected') THEN :status ELSE decision_code END,decision_reason_safe=:message,completed_at=CASE WHEN :status='rejected' THEN now() ELSE completed_at END,updated_at=now() WHERE id=:id"
        ),
        {"status": target, "message": payload.user_visible_message, "id": privacy_request_id},
    )
    await session.execute(
        text(
            "INSERT INTO privacy_request_events (data_subject_request_id,event_type,actor_id,safe_context) VALUES (:id,:event,:actor,CAST(:context AS jsonb))"
        ),
        {
            "id": privacy_request_id,
            "event": target,
            "actor": principal.user.id,
            "context": json_value({"reason_recorded": True}),
        },
    )
    await audit(
        session,
        f"privacy.request.{target}",
        "data_subject_request",
        privacy_request_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(privacy_request_id), "status": target}, request_id_from_request(request)
    )


@router.post("/admin/privacy/requests/{privacy_request_id}/verify-identity")
async def verify_request_identity(
    privacy_request_id: UUID,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("privacy.requests.verify_identity")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await request_transition(
        privacy_request_id, "verified", payload, request, principal, session
    )


@router.post("/admin/privacy/requests/{privacy_request_id}/approve")
async def approve_request(
    privacy_request_id: UUID,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.requests.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await request_transition(
        privacy_request_id, "approved", payload, request, principal, session
    )


@router.post("/admin/privacy/requests/{privacy_request_id}/reject")
async def reject_request(
    privacy_request_id: UUID,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.requests.reject")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await request_transition(
        privacy_request_id, "rejected", payload, request, principal, session
    )


@router.post("/admin/privacy/exports/{privacy_request_id}/process")
async def process_export(
    privacy_request_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.exports.generate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await process_export_request(session, privacy_request_id), request_id_from_request(request)
    )


@router.get("/admin/privacy/exports")
async def exports(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.exports.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT e.id,r.request_number,('user-'||left(r.user_id::text,8)) AS user_anonymous_id,"
                    "e.status,e.export_format,e.completed_modules,e.failed_modules,e.encryption_mode,"
                    "e.archive_expires_at,e.downloaded_at,e.created_at FROM privacy_export_jobs e "
                    "JOIN data_subject_requests r ON r.id=e.data_subject_request_id "
                    "ORDER BY e.created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"items": rows, "archives_and_tokens_excluded": True}, request_id_from_request(request)
    )


@router.get("/admin/privacy/corrections")
async def corrections(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.corrections.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT c.id,c.data_subject_request_id,c.module_code,c.entity_reference_type,c.field_path,c.reason,c.status,c.reviewed_by,c.reviewed_at,c.resolution_code,c.resolution_message_safe,c.created_at FROM privacy_correction_items c ORDER BY c.created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows, "values_redacted": True}, request_id_from_request(request))


@router.post("/admin/privacy/corrections/{item_id}/approve")
async def approve_correction(
    item_id: UUID,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.corrections.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = (
        (
            await session.execute(
                text("SELECT * FROM privacy_correction_items WHERE id=:id FOR UPDATE"),
                {"id": item_id},
            )
        )
        .mappings()
        .first()
    )
    if item is None or item["status"] != "review_required":
        raise VavError(
            "PRIVACY_CORRECTION_REVIEW_INVALID",
            "Correction is not awaiting review.",
            status_code=409,
        )
    if item["module_code"] == "commerce" and item["field_path"] in {
        "total_minor",
        "paid_at",
        "refunded_total_minor",
    }:
        resolution = "historical_amendment_required"
        status = "approved_for_amendment"
    else:
        resolution = "approved"
        status = "approved"
    await session.execute(
        text(
            "UPDATE privacy_correction_items SET status=:status,reviewed_by=:actor,reviewed_at=now(),resolution_code=:resolution,resolution_message_safe=:message,updated_at=now() WHERE id=:id"
        ),
        {
            "status": status,
            "actor": principal.user.id,
            "resolution": resolution,
            "message": payload.user_visible_message,
            "id": item_id,
        },
    )
    await audit(
        session,
        "privacy.correction.approved",
        "privacy_correction_item",
        item_id,
        actor_id=principal.user.id,
        reason=payload.reason,
        context={"historical_fact_preserved": resolution == "historical_amendment_required"},
    )
    await session.commit()
    return success(
        {"id": str(item_id), "status": status, "resolution_code": resolution},
        request_id_from_request(request),
    )


@router.post("/admin/privacy/corrections/{item_id}/reject")
async def reject_correction(
    item_id: UUID,
    payload: AdminDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.corrections.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE privacy_correction_items SET status='rejected',reviewed_by=:actor,reviewed_at=now(),resolution_code='rejected',resolution_message_safe=:message,updated_at=now() WHERE id=:id AND status='review_required' RETURNING id"
        ),
        {"actor": principal.user.id, "message": payload.user_visible_message, "id": item_id},
    )
    if value is None:
        raise VavError(
            "PRIVACY_CORRECTION_REVIEW_INVALID",
            "Correction is not awaiting review.",
            status_code=409,
        )
    await audit(
        session,
        "privacy.correction.rejected",
        "privacy_correction_item",
        item_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"id": str(item_id), "status": "rejected"}, request_id_from_request(request))


@router.get("/admin/privacy/erasures")
async def erasures(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.erasures.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,data_subject_request_id,('user-'||left(user_id::text,8)) AS user_anonymous_id,status,module_plans,blocking_conditions,retention_exceptions,user_confirmation_required,user_confirmed_at,planned_at,approved_at,execution_started_at,completed_at FROM privacy_erasure_plans ORDER BY created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.post("/admin/privacy/erasures/{plan_id}/replan")
async def replan_erasure(
    plan_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.erasures.plan")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT data_subject_request_id,user_id FROM privacy_erasure_plans WHERE id=:id"
                ),
                {"id": plan_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "PRIVACY_ERASURE_PLAN_NOT_FOUND", "Erasure plan was not found.", status_code=404
        )
    return success(
        await create_erasure_plan(
            session, UUID(str(row["data_subject_request_id"])), UUID(str(row["user_id"]))
        ),
        request_id_from_request(request),
    )


@router.post("/admin/privacy/erasures/{plan_id}/approve")
async def approve_erasure(
    plan_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.erasures.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE privacy_erasure_plans SET status='ready',approved_by=:actor,approved_at=now(),updated_at=now() WHERE id=:id AND status IN ('planned','ready') AND blocking_conditions='[]'::jsonb AND (user_confirmation_required=false OR user_confirmed_at IS NOT NULL) RETURNING id"
        ),
        {"actor": principal.user.id, "id": plan_id},
    )
    if value is None:
        raise VavError(
            "PRIVACY_ERASURE_APPROVAL_BLOCKED",
            "Erasure plan is blocked or unconfirmed.",
            status_code=409,
        )
    await audit(
        session,
        "privacy.erasure.approved",
        "privacy_erasure_plan",
        plan_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"id": str(plan_id), "status": "ready"}, request_id_from_request(request))


@router.post("/admin/privacy/erasures/{plan_id}/execute")
async def execute_erasure(
    plan_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.erasures.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await execute_erasure_plan(session, plan_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.get("/admin/privacy/consents")
async def consent_registry(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.consents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT d.*,count(r.id) AS release_count,count(r.id) FILTER (WHERE r.status='active') AS active_release_count FROM consent_definitions d LEFT JOIN consent_releases r ON r.consent_definition_id=d.id GROUP BY d.id ORDER BY d.consent_code"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.post("/admin/privacy/consents", status_code=201)
async def create_consent_definition(
    payload: ConsentDefinitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.consents.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "INSERT INTO consent_definitions (consent_code,category,required_for_service,withdrawable,scope_definition,evidence_requirements) VALUES (:code,:category,:required,:withdrawable,CAST(:scope AS jsonb),CAST(:evidence AS jsonb)) RETURNING id"
        ),
        {
            "code": payload.consent_code,
            "category": payload.category,
            "required": payload.required_for_service,
            "withdrawable": payload.withdrawable,
            "scope": json_value(payload.scope_definition),
            "evidence": json_value(payload.evidence_requirements),
        },
    )
    await audit(
        session,
        "privacy.consent_definition.created",
        "consent_definition",
        UUID(str(value)),
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(value)}, request_id_from_request(request))


@router.post("/admin/privacy/consents/{definition_id}/releases", status_code=201)
async def create_consent_release(
    definition_id: UUID,
    payload: ConsentReleaseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("privacy.consent_releases.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    checksum = hashlib.sha256(f"{payload.title}\n{payload.summary}".encode()).hexdigest()
    value = await session.scalar(
        text(
            "INSERT INTO consent_releases (consent_definition_id,semantic_version,locale,title,summary,status,valid_from,checksum_sha256,approved_by,approved_at) VALUES (:definition,:version,:locale,:title,:summary,'approved',CAST(:valid_from AS timestamptz),:checksum,:actor,now()) RETURNING id"
        ),
        {
            "definition": definition_id,
            "version": payload.semantic_version,
            "locale": payload.locale,
            "title": payload.title,
            "summary": payload.summary,
            "valid_from": payload.valid_from,
            "checksum": checksum,
            "actor": principal.user.id,
        },
    )
    await session.commit()
    return success(
        {"id": str(value), "status": "approved", "checksum_sha256": checksum},
        request_id_from_request(request),
    )


@router.post("/admin/privacy/consent-releases/{release_id}/activate")
async def activate_consent_release(
    release_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("privacy.consent_releases.activate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM consent_releases WHERE id=:id FOR UPDATE"), {"id": release_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["status"] != "approved":
        raise VavError(
            "PRIVACY_CONSENT_RELEASE_ACTIVATION_INVALID",
            "Consent release is not approved.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE consent_releases SET status='superseded' WHERE consent_definition_id=:definition AND locale=:locale AND status='active'"
        ),
        {"definition": row["consent_definition_id"], "locale": row["locale"]},
    )
    await session.execute(
        text("UPDATE consent_releases SET status='active' WHERE id=:id"), {"id": release_id}
    )
    await audit(
        session,
        "privacy.consent_release.activated",
        "consent_release",
        release_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"id": str(release_id), "status": "active"}, request_id_from_request(request))


@router.get("/admin/privacy/consent-releases")
async def consent_releases(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.consents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT r.id,d.consent_code,r.semantic_version,r.locale,r.title,r.status,r.valid_from,"
                    "r.valid_until,r.checksum_sha256,r.approved_at,r.created_at FROM consent_releases r "
                    "JOIN consent_definitions d ON d.id=r.consent_definition_id "
                    "ORDER BY d.consent_code,r.locale,r.created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/data-inventory")
async def data_inventory(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.inventory.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text("SELECT * FROM privacy_data_assets ORDER BY module_code,asset_code")
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/processing-activities")
async def processing_activities(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.inventory.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text("SELECT * FROM privacy_processing_activities ORDER BY activity_code")
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/classifications")
async def classifications(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.classifications.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text("SELECT * FROM privacy_field_classifications ORDER BY asset_code,field_path")
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/retention-policies")
async def retention_policies(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.retention.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT * FROM privacy_retention_policies ORDER BY policy_code,created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.post("/admin/privacy/retention-policies", status_code=201)
async def create_retention_policy(
    payload: RetentionPolicyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.retention.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "INSERT INTO privacy_retention_policies (policy_code,semantic_version,data_category,module_code,trigger_event,retention_days,expiration_action,policy_basis,status,approved_by,approved_at,valid_from) VALUES (:code,:version,:category,:module,:trigger,:days,:action,:basis,'active',:actor,now(),now()) RETURNING id"
        ),
        {
            "code": payload.policy_code,
            "version": payload.semantic_version,
            "category": payload.data_category,
            "module": payload.module_code,
            "trigger": payload.trigger_event,
            "days": payload.retention_days,
            "action": payload.expiration_action,
            "basis": payload.policy_basis,
            "actor": principal.user.id,
        },
    )
    await audit(
        session,
        "privacy.retention.policy_created",
        "privacy_retention_policy",
        UUID(str(value)),
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(value), "status": "active"}, request_id_from_request(request))


@router.get("/admin/privacy/retention-instances")
async def retention_instances(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.retention.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,policy_id,subject_type,subject_id,('user-'||left(user_id::text,8)) AS user_anonymous_id,trigger_at,expires_at,status,active_hold_count,evaluated_at,action_completed_at FROM privacy_retention_instances ORDER BY expires_at NULLS LAST LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.post("/admin/privacy/workers/retention/run")
async def run_retention(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.retention.execute")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT i.id,i.active_hold_count,p.expiration_action FROM privacy_retention_instances i JOIN privacy_retention_policies p ON p.id=i.policy_id WHERE i.status='active' AND i.expires_at<=now() ORDER BY i.expires_at FOR UPDATE OF i SKIP LOCKED LIMIT 100"
                )
            )
        )
        .mappings()
        .all()
    )
    results = []
    for row in rows:
        if row["active_hold_count"]:
            status = "blocked_by_hold"
        else:
            status = (
                "manual_review" if row["expiration_action"] == "manual_review" else "action_queued"
            )
        await session.execute(
            text(
                "UPDATE privacy_retention_instances SET status=:status,evaluated_at=now(),updated_at=now() WHERE id=:id"
            ),
            {"status": status, "id": row["id"]},
        )
        results.append({"id": str(row["id"]), "status": status})
    await audit(
        session,
        "privacy.retention.action_executed",
        "retention_batch",
        None,
        actor_id=principal.user.id,
        context={"count": len(results), "sensitive_content_excluded": True},
    )
    await session.commit()
    return success({"items": results}, request_id_from_request(request))


@router.get("/admin/privacy/legal-holds")
async def legal_holds(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.holds.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,hold_number,hold_type,status,authorized_by,created_by,starts_at,ends_at,released_by,released_at,created_at FROM privacy_legal_holds ORDER BY created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"items": rows, "scope_and_reason_redacted": True}, request_id_from_request(request)
    )


@router.post("/admin/privacy/legal-holds", status_code=201)
async def create_legal_hold(
    payload: LegalHoldRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.holds.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.authorized_by == principal.user.id:
        raise VavError(
            "PRIVACY_HOLD_SELF_AUTHORIZATION_FORBIDDEN",
            "Hold creation requires a separate authorizer.",
            status_code=403,
        )
    if payload.ends_at <= utcnow():
        raise VavError(
            "PRIVACY_HOLD_END_INVALID", "Hold end must be in the future.", status_code=422
        )
    hold_id = await session.scalar(
        text(
            "INSERT INTO privacy_legal_holds (hold_number,hold_type,status,scope_definition_encrypted,reason_encrypted,authorized_by,created_by,starts_at,ends_at) VALUES (:number,:type,'active',:scope,:reason,:authorized,:creator,now(),:ends) RETURNING id"
        ),
        {
            "number": request_number("HLD"),
            "type": payload.hold_type,
            "scope": encrypt_private(
                {
                    "subject_user_id": str(payload.subject_user_id),
                    "module_codes": payload.module_codes,
                }
            ),
            "reason": encrypt_private(payload.reason),
            "authorized": payload.authorized_by,
            "creator": principal.user.id,
            "ends": payload.ends_at,
        },
    )
    await session.execute(
        text(
            "UPDATE privacy_retention_instances i SET active_hold_count=active_hold_count+1,"
            "status=CASE WHEN i.expires_at<=now() THEN 'blocked_by_hold' ELSE i.status END,updated_at=now() "
            "FROM privacy_retention_policies p WHERE p.id=i.policy_id AND i.user_id=:user_id "
            "AND p.module_code=ANY(CAST(:modules AS text[]))"
        ),
        {"user_id": payload.subject_user_id, "modules": payload.module_codes},
    )
    await audit(
        session,
        "privacy.hold.created",
        "privacy_legal_hold",
        UUID(str(hold_id)),
        actor_id=principal.user.id,
        context={"hold_type": payload.hold_type, "scope_minimized": True},
    )
    await session.commit()
    return success({"id": str(hold_id), "status": "active"}, request_id_from_request(request))


@router.post("/admin/privacy/legal-holds/{hold_id}/release")
async def release_hold(
    hold_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.holds.release")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    hold = (
        (
            await session.execute(
                text(
                    "SELECT scope_definition_encrypted FROM privacy_legal_holds "
                    "WHERE id=:id AND status='active' FOR UPDATE"
                ),
                {"id": hold_id},
            )
        )
        .mappings()
        .first()
    )
    if hold is None:
        raise VavError("PRIVACY_HOLD_NOT_ACTIVE", "Hold is not active.", status_code=409)
    scope = decrypt_private(hold["scope_definition_encrypted"])
    await session.execute(
        text(
            "UPDATE privacy_legal_holds SET status='released',released_by=:actor,released_at=now(),"
            "release_reason_encrypted=:reason,updated_at=now() WHERE id=:id"
        ),
        {"actor": principal.user.id, "reason": encrypt_private(payload.reason), "id": hold_id},
    )
    await session.execute(
        text(
            "UPDATE privacy_retention_instances i SET active_hold_count=GREATEST(active_hold_count-1,0),"
            "status=CASE WHEN i.status='blocked_by_hold' THEN 'active' ELSE i.status END,updated_at=now() "
            "FROM privacy_retention_policies p WHERE p.id=i.policy_id AND i.user_id=:user_id "
            "AND p.module_code=ANY(CAST(:modules AS text[]))"
        ),
        {
            "user_id": UUID(str(scope["subject_user_id"])),
            "modules": list(scope.get("module_codes", [])),
        },
    )
    await audit(
        session,
        "privacy.hold.released",
        "privacy_legal_hold",
        hold_id,
        actor_id=principal.user.id,
        reason=payload.reason,
        context={"retention_reevaluation_enabled": True},
    )
    await session.commit()
    return success({"id": str(hold_id), "status": "released"}, request_id_from_request(request))


@router.get("/admin/privacy/break-glass")
async def break_glass_requests(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.break_glass.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,request_number,requester_user_id,('user-'||left(subject_user_id::text,8)) AS subject_anonymous_id,data_scope,purpose,status,approved_by,approved_at,expires_at,used_at,revoked_at,created_at FROM privacy_break_glass_access ORDER BY created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows, "reasons_redacted": True}, request_id_from_request(request))


@router.post("/admin/privacy/break-glass", status_code=201)
async def request_break_glass(
    payload: BreakGlassRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.break_glass.request")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "INSERT INTO privacy_break_glass_access (request_number,requester_user_id,subject_user_id,data_scope,purpose,reason_encrypted,status,expires_at) VALUES (:number,:requester,:subject,CAST(:scope AS jsonb),:purpose,:reason,'requested',:expires) RETURNING id"
        ),
        {
            "number": request_number("BRG"),
            "requester": principal.user.id,
            "subject": payload.subject_user_id,
            "scope": json_value(payload.data_scope),
            "purpose": payload.purpose,
            "reason": encrypt_private(payload.reason),
            "expires": utcnow()
            + timedelta(minutes=get_settings().privacy_break_glass_default_ttl_minutes),
        },
    )
    await audit(
        session,
        "privacy.break_glass.requested",
        "privacy_break_glass_access",
        UUID(str(value)),
        actor_id=principal.user.id,
        context={"purpose": payload.purpose, "scope": payload.data_scope},
    )
    await session.commit()
    return success({"id": str(value), "status": "requested"}, request_id_from_request(request))


@router.post("/admin/privacy/break-glass/{access_id}/approve")
async def approve_break_glass(
    access_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.break_glass.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE privacy_break_glass_access SET status='approved',approved_by=:actor,approved_at=now() WHERE id=:id AND status='requested' AND requester_user_id<>:actor AND expires_at>now() RETURNING id"
        ),
        {"actor": principal.user.id, "id": access_id},
    )
    if value is None:
        raise VavError(
            "PRIVACY_BREAK_GLASS_APPROVAL_INVALID",
            "Break-glass request is expired, self-approved or unavailable.",
            status_code=409,
        )
    await audit(
        session,
        "privacy.break_glass.approved",
        "privacy_break_glass_access",
        access_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"id": str(access_id), "status": "approved"}, request_id_from_request(request))


@router.post("/admin/privacy/break-glass/{access_id}/use")
async def use_break_glass(
    access_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("privacy.break_glass.use")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM privacy_break_glass_access WHERE id=:id AND requester_user_id=:actor AND status='approved' AND expires_at>now() AND revoked_at IS NULL FOR UPDATE"
                ),
                {"id": access_id, "actor": principal.user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "PRIVACY_BREAK_GLASS_USE_FORBIDDEN",
            "Approved unexpired access is required.",
            status_code=403,
        )
    await session.execute(
        text("UPDATE privacy_break_glass_access SET used_at=now() WHERE id=:id"), {"id": access_id}
    )
    for asset in row["data_scope"]:
        await session.execute(
            text(
                "INSERT INTO privacy_sensitive_access_events (actor_user_id,subject_user_id,module_code,asset_code,access_type,purpose,permission_code,break_glass_access_id,result) VALUES (:actor,:subject,'privacy',:asset,'read',:purpose,'privacy.break_glass.use',:access_id,'allowed')"
            ),
            {
                "actor": principal.user.id,
                "subject": row["subject_user_id"],
                "asset": str(asset),
                "purpose": row["purpose"],
                "access_id": access_id,
            },
        )
    await audit(
        session,
        "privacy.break_glass.used",
        "privacy_break_glass_access",
        access_id,
        actor_id=principal.user.id,
        context={"asset_count": len(row["data_scope"])},
    )
    await session.commit()
    return success(
        {
            "id": str(access_id),
            "status": "used",
            "scope": row["data_scope"],
            "expires_at": row["expires_at"],
            "sensitive_values_not_loaded": True,
        },
        request_id_from_request(request),
    )


@router.get("/admin/privacy/access-events")
async def access_events(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.sensitive_access.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,actor_user_id,('user-'||left(subject_user_id::text,8)) AS subject_anonymous_id,module_code,asset_code,access_type,purpose,permission_code,break_glass_access_id,result,occurred_at FROM privacy_sensitive_access_events ORDER BY occurred_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/admin/privacy/audit")
async def privacy_audit(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,event_type,actor_id,subject_type,subject_id,reason,safe_context,created_at FROM privacy_audit_events ORDER BY created_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"items": rows, "sensitive_values_excluded": True}, request_id_from_request(request)
    )


@router.get("/admin/privacy/incidents")
async def privacy_incidents(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("privacy.incidents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id AS event_id,'sensitive_access_denied' AS incident_type,module_code,asset_code,"
                    "purpose,result AS status,occurred_at FROM privacy_sensitive_access_events "
                    "WHERE result<>'allowed' ORDER BY occurred_at DESC LIMIT 500"
                )
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"items": rows, "derived_signal_view": True, "investigation_details_redacted": True},
        request_id_from_request(request),
    )
