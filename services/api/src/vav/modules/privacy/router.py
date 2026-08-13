# ruff: noqa: B008, E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.privacy.crypto import (
    decrypt_private,
    encrypt_private,
    mask_email,
    mask_phone,
    searchable_hmac,
)
from vav.modules.privacy.schemas import (
    AiMemoryCandidateRequest,
    AiMemoryPreferencesRequest,
    AiMemoryUpdateRequest,
    ConsentActionRequest,
    ContactPointCreateRequest,
    ContactPointUpdateRequest,
    CorrectionRequest,
    ErasureConfirmationRequest,
    ErasureRequest,
    ExportRequest,
    PrivacySettingsUpdateRequest,
    ProfileUpdateRequest,
)
from vav.modules.privacy.service import (
    audit,
    clear_ai_memory,
    consume_export_download,
    create_erasure_plan,
    create_memory_candidate,
    create_request,
    ensure_privacy_defaults,
    grant_consent,
    issue_export_download_token,
    process_inventory_request,
    profile_view,
    update_privacy_settings,
    update_profile,
    validate_memory_content,
    verify_password,
    withdraw_consent,
)

router = APIRouter()


def enabled() -> None:
    if not get_settings().privacy_enabled:
        raise VavError("PRIVACY_DISABLED", "Privacy control plane is disabled.", status_code=503)


@router.get("/account/profile")
async def get_profile(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enabled()
    return success(await profile_view(session, principal.user), request_id_from_request(request))


@router.patch("/account/profile")
async def patch_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enabled()
    return success(
        await update_profile(session, principal.user, payload), request_id_from_request(request)
    )


@router.get("/account/contact-points")
async def contact_points(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enabled()
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,contact_type,value_encrypted,status,verified_at,is_primary,visibility,created_at FROM user_contact_points WHERE user_id=:user_id ORDER BY is_primary DESC,created_at"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows:
        value = str(decrypt_private(row["value_encrypted"]))
        masked = (
            mask_email(value)
            if row["contact_type"] == "email"
            else mask_phone(value)
            if row["contact_type"] == "phone"
            else f"{value[:1]}***"
        )
        items.append(
            {
                **{key: value for key, value in dict(row).items() if key != "value_encrypted"},
                "masked_value": masked,
            }
        )
    return success({"items": items, "private_by_default": True}, request_id_from_request(request))


@router.post("/account/contact-points", status_code=201)
async def create_contact_point(
    payload: ContactPointCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enabled()
    # A phone also gets `last_four_hmac`, the narrowing column onsite check-in
    # searches (CHK-002). Deriving it needs the plaintext, which only exists
    # here — a migration cannot compute it from ciphertext later, so a write
    # that skips it leaves the number permanently unfindable by last four.
    last_four_digest: str | None = None
    if payload.contact_type == "phone":
        try:
            from vav.modules.checkin_operations.service import contact_point_write_values

            last_four_digest = contact_point_write_values(payload.value)["last_four_hmac"]
        except VavError:
            # The lookup salt is not configured. Storing the contact point is
            # still correct; it simply will not be searchable by last four
            # until the salt is set and the backfill job runs.
            last_four_digest = None

    value = await session.scalar(
        text(
            "INSERT INTO user_contact_points "
            "(user_id,contact_type,value_encrypted,value_hmac,last_four_hmac,status,visibility) "
            "VALUES (:user_id,:type,:value,:hash,:last_four,'pending_verification','private') "
            "RETURNING id"
        ),
        {
            "user_id": principal.user.id,
            "type": payload.contact_type,
            "value": encrypt_private(payload.value.strip()),
            "hash": searchable_hmac(payload.value),
            "last_four": last_four_digest,
        },
    )
    contact_id = UUID(str(value))
    await audit(
        session,
        "privacy.contact_point.created",
        "contact_point",
        contact_id,
        actor_id=principal.user.id,
        context={"contact_type": payload.contact_type},
    )
    await session.commit()
    return success(
        {"id": str(contact_id), "status": "pending_verification", "visibility": "private"},
        request_id_from_request(request),
    )


@router.patch("/account/contact-points/{contact_id}")
async def update_contact_point(
    contact_id: UUID,
    payload: ContactPointUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.visibility != "private":
        raise VavError(
            "PRIVACY_CONTACT_VISIBILITY_FORBIDDEN",
            "Contact points remain private until a separately governed exchange flow exists.",
            status_code=409,
        )
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM user_contact_points WHERE id=:id AND user_id=:user_id FOR UPDATE"
                ),
                {"id": contact_id, "user_id": principal.user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("PRIVACY_CONTACT_NOT_FOUND", "Contact point was not found.", status_code=404)
    if payload.is_primary and row["status"] != "verified":
        raise VavError(
            "PRIVACY_CONTACT_NOT_VERIFIED",
            "Only a verified contact point can be primary.",
            status_code=409,
        )
    if payload.is_primary:
        await session.execute(
            text(
                "UPDATE user_contact_points SET is_primary=false,updated_at=now() WHERE user_id=:user_id AND contact_type=:type"
            ),
            {"user_id": principal.user.id, "type": row["contact_type"]},
        )
    await session.execute(
        text(
            "UPDATE user_contact_points SET is_primary=COALESCE(:primary,is_primary),visibility='private',updated_at=now() WHERE id=:id"
        ),
        {"primary": payload.is_primary, "id": contact_id},
    )
    await audit(
        session,
        "privacy.contact_point.updated",
        "contact_point",
        contact_id,
        actor_id=principal.user.id,
        reason=payload.version_reason,
    )
    await session.commit()
    return success({"id": str(contact_id)}, request_id_from_request(request))


@router.delete("/account/contact-points/{contact_id}")
async def delete_contact_point(
    contact_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "DELETE FROM user_contact_points WHERE id=:id AND user_id=:user_id AND is_primary=false RETURNING id"
        ),
        {"id": contact_id, "user_id": principal.user.id},
    )
    if value is None:
        raise VavError(
            "PRIVACY_CONTACT_DELETE_FORBIDDEN",
            "Contact point is missing or primary.",
            status_code=409,
        )
    await audit(
        session,
        "privacy.contact_point.deleted",
        "contact_point",
        contact_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(contact_id), "status": "deleted"}, request_id_from_request(request))


@router.get("/account/privacy/settings")
async def get_privacy_settings(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, principal.user)
    settings_row = dict(
        (
            await session.execute(
                text("SELECT * FROM user_privacy_settings WHERE user_id=:user_id"),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .one()
    )
    rules = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT data_domain,field_code,visibility,allowed_purposes,allowed_recipient_types,valid_from,valid_until FROM user_field_visibility_rules WHERE user_id=:user_id ORDER BY data_domain,field_code"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    ]
    settings_row.pop("id", None)
    settings_row.pop("user_id", None)
    return success({**settings_row, "field_rules": rules}, request_id_from_request(request))


@router.put("/account/privacy/settings")
async def put_privacy_settings(
    payload: PrivacySettingsUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await update_privacy_settings(session, principal.user, payload),
        request_id_from_request(request),
    )


@router.get("/account/consents")
async def consents(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT d.consent_code,d.category,d.required_for_service,d.withdrawable,r.id AS release_id,"
                    "r.semantic_version,r.locale,r.title,r.summary,r.checksum_sha256,"
                    "COALESCE((SELECT u.status FROM user_consents u WHERE u.user_id=:user_id "
                    "AND u.consent_definition_id=d.id ORDER BY u.created_at DESC LIMIT 1),'not_granted') AS status "
                    "FROM consent_definitions d JOIN consent_releases r ON r.consent_definition_id=d.id "
                    "WHERE r.status='active' AND r.locale=:locale ORDER BY d.consent_code"
                ),
                {"user_id": principal.user.id, "locale": principal.user.preferred_locale},
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/account/consents/{consent_code}")
async def consent_detail(
    consent_code: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT u.status,u.source,u.granted_at,u.withdrawn_at,u.expires_at,r.semantic_version,r.locale,r.title,r.summary,r.checksum_sha256 FROM user_consents u JOIN consent_definitions d ON d.id=u.consent_definition_id JOIN consent_releases r ON r.id=u.consent_release_id WHERE u.user_id=:user_id AND d.consent_code=:code ORDER BY u.created_at DESC"
                ),
                {"user_id": principal.user.id, "code": consent_code},
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"consent_code": consent_code, "history": rows}, request_id_from_request(request)
    )


@router.post("/account/consents/{consent_code}/grant")
async def grant_user_consent(
    consent_code: str,
    payload: ConsentActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await grant_consent(
        session,
        principal.user.id,
        consent_code,
        payload.release_id,
        {**payload.evidence, "request_id": request_id_from_request(request)},
    )
    return success(result, request_id_from_request(request))


@router.post("/account/consents/{consent_code}/withdraw")
async def withdraw_user_consent(
    consent_code: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await withdraw_consent(session, principal.user.id, consent_code),
        request_id_from_request(request),
    )


@router.post("/account/privacy/data-inventory", status_code=202)
async def request_inventory(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_id = await create_request(
        session, user=principal.user, request_type="inventory", requested_scope={"modules": "all"}
    )
    result = await process_inventory_request(session, request_id)
    return success(result, request_id_from_request(request))


@router.post("/account/privacy/exports", status_code=202)
async def request_export(
    payload: ExportRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_id = await create_request(
        session,
        user=principal.user,
        request_type="export",
        requested_scope={"modules": payload.modules},
        requested_format=payload.requested_format,
        password=payload.password,
    )
    return success({"id": str(request_id), "status": "verified"}, request_id_from_request(request))


@router.get("/account/privacy/requests")
async def list_privacy_requests(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT id,request_number,request_type,status,requested_scope,requested_format,submitted_at,due_at,decision_code,decision_reason_safe,completed_at FROM data_subject_requests WHERE user_id=:user_id ORDER BY created_at DESC"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    ]
    return success({"items": rows}, request_id_from_request(request))


@router.get("/account/privacy/requests/{privacy_request_id}")
async def privacy_request_detail(
    privacy_request_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,request_number,request_type,status,requested_scope,requested_format,submitted_at,due_at,decision_code,decision_reason_safe,completed_at FROM data_subject_requests WHERE id=:id AND user_id=:user_id"
                ),
                {"id": privacy_request_id, "user_id": principal.user.id},
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
                    "SELECT id,status,module_plans,blocking_conditions,retention_exceptions,user_confirmation_required,user_confirmed_at FROM privacy_erasure_plans WHERE data_subject_request_id=:id"
                ),
                {"id": privacy_request_id},
            )
        )
        .mappings()
        .first()
    )
    return success(
        {**dict(row), "module_results": modules, "erasure_plan": dict(plan) if plan else None},
        request_id_from_request(request),
    )


@router.post("/account/privacy/exports/{privacy_request_id}/download-token")
async def export_download_token(
    privacy_request_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    token = await issue_export_download_token(session, principal.user.id, privacy_request_id)
    return success(
        {"token": token, "expires_in_hours": get_settings().privacy_export_download_ttl_hours},
        request_id_from_request(request),
    )


@router.get("/account/privacy/exports/download/{token}")
async def download_export(
    token: str,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    archive = await consume_export_download(session, principal.user.id, token)
    return Response(
        content=archive,
        media_type="application/vnd.vav.encrypted+json",
        headers={"Content-Disposition": "attachment; filename=vav-private-export.enc"},
    )


@router.post("/account/privacy/corrections", status_code=202)
async def request_correction(
    payload: CorrectionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_id = await create_request(
        session,
        user=principal.user,
        request_type="correction",
        requested_scope={"item_count": len(payload.items)},
    )
    for item in payload.items:
        if (
            item.module_code == "commerce"
            and item.field_path in {"total_minor", "paid_at", "refunded_total_minor"}
            or item.module_code == "identity"
            and item.field_path
            in {"display_name", "city", "region", "preferred_locale", "timezone", "public_bio"}
        ):
            status = "review_required"
        else:
            status = "review_required"
        await session.execute(
            text(
                "INSERT INTO privacy_correction_items (data_subject_request_id,module_code,entity_reference_type,entity_reference_id,field_path,requested_value_encrypted,reason,status) VALUES (:request_id,:module,:entity_type,:entity_id,:field,:value,:reason,:status)"
            ),
            {
                "request_id": request_id,
                "module": item.module_code,
                "entity_type": item.entity_reference_type,
                "entity_id": item.entity_reference_id,
                "field": item.field_path,
                "value": encrypt_private(item.requested_value),
                "reason": item.reason,
                "status": status,
            },
        )
    await audit(
        session,
        "privacy.correction.requested",
        "data_subject_request",
        request_id,
        actor_id=principal.user.id,
        context={"item_count": len(payload.items)},
    )
    await session.commit()
    return success({"id": str(request_id), "status": "submitted"}, request_id_from_request(request))


@router.post("/account/privacy/erasures", status_code=202)
async def request_erasure(
    payload: ErasureRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_id = await create_request(
        session,
        user=principal.user,
        request_type="erasure",
        requested_scope={"modules": payload.requested_scope},
        password=payload.password,
    )
    return success(
        await create_erasure_plan(session, request_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/account/privacy/erasures/{plan_id}/confirm")
async def confirm_erasure(
    plan_id: UUID,
    payload: ErasureConfirmationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    verify_password(principal.user, payload.password)
    value = await session.scalar(
        text(
            "UPDATE privacy_erasure_plans SET user_confirmed_at=now(),status='ready',updated_at=now() WHERE id=:id AND user_id=:user_id AND status='planned' AND blocking_conditions='[]'::jsonb RETURNING id"
        ),
        {"id": plan_id, "user_id": principal.user.id},
    )
    if value is None:
        raise VavError(
            "PRIVACY_ERASURE_CONFIRMATION_BLOCKED",
            "Erasure plan is missing or blocked.",
            status_code=409,
        )
    await audit(
        session,
        "privacy.erasure.confirmed",
        "privacy_erasure_plan",
        plan_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(plan_id), "status": "ready"}, request_id_from_request(request))


@router.get("/account/ai-memory/preferences")
async def memory_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, principal.user)
    row = dict(
        (
            await session.execute(
                text(
                    "SELECT long_term_memory_enabled,allow_profile_facts,allow_service_history,allow_relationship_context,allow_cross_conversation_use,settings_version,created_at,updated_at FROM ai_memory_preferences WHERE user_id=:user_id"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .one()
    )
    return success(row, request_id_from_request(request))


@router.put("/account/ai-memory/preferences")
async def update_memory_preferences(
    payload: AiMemoryPreferencesRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, principal.user)
    consent_id = None
    if payload.long_term_memory_enabled:
        consent_id = await session.scalar(
            text(
                "SELECT u.id FROM user_consents u JOIN consent_definitions d ON d.id=u.consent_definition_id WHERE u.user_id=:user_id AND d.consent_code='ai_long_term_memory' AND u.status='granted' AND (u.expires_at IS NULL OR u.expires_at>now()) ORDER BY u.created_at DESC LIMIT 1"
            ),
            {"user_id": principal.user.id},
        )
        if consent_id is None:
            raise VavError(
                "AI_MEMORY_CONSENT_REQUIRED",
                "Grant AI long-term memory consent first.",
                status_code=409,
            )
    value = await session.scalar(
        text(
            "UPDATE ai_memory_preferences SET long_term_memory_enabled=:enabled,allow_profile_facts=:profile,allow_service_history=:history,allow_relationship_context=:relationship,allow_cross_conversation_use=:cross_use,consent_id=:consent,settings_version=settings_version+1,updated_at=now() WHERE user_id=:user_id AND settings_version=:version RETURNING settings_version"
        ),
        {
            "enabled": payload.long_term_memory_enabled,
            "profile": payload.allow_profile_facts if payload.long_term_memory_enabled else False,
            "history": payload.allow_service_history if payload.long_term_memory_enabled else False,
            "relationship": payload.allow_relationship_context
            if payload.long_term_memory_enabled
            else False,
            "cross_use": payload.allow_cross_conversation_use
            if payload.long_term_memory_enabled
            else False,
            "consent": consent_id,
            "user_id": principal.user.id,
            "version": payload.settings_version,
        },
    )
    if value is None:
        raise VavError(
            "AI_MEMORY_SETTINGS_VERSION_CONFLICT",
            "Memory settings were updated elsewhere.",
            status_code=409,
        )
    if not payload.long_term_memory_enabled:
        await session.execute(
            text(
                "UPDATE ai_memory_items SET status='rejected',updated_at=now() WHERE user_id=:user_id AND status IN ('candidate','user_approval_required')"
            ),
            {"user_id": principal.user.id},
        )
    await audit(
        session,
        "privacy.ai_memory.enabled"
        if payload.long_term_memory_enabled
        else "privacy.ai_memory.disabled",
        "user",
        principal.user.id,
        actor_id=principal.user.id,
        context={"cache_invalidated": True},
    )
    await session.commit()
    deleted = (
        await clear_ai_memory(session, principal.user.id)
        if not payload.long_term_memory_enabled and payload.delete_existing_when_disabled
        else 0
    )
    return success(
        {
            "settings_version": int(value),
            "long_term_memory_enabled": payload.long_term_memory_enabled,
            "deleted_items": deleted,
            "cache_invalidated": True,
        },
        request_id_from_request(request),
    )


@router.get("/account/ai-memory/items")
async def memory_items(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,memory_type,status,content_encrypted,source_type,source_reference_id,provenance_snapshot,certainty,user_confirmed,allowed_purposes,allowed_agent_profiles,valid_from,expires_at,last_used_at,created_at,updated_at FROM ai_memory_items WHERE user_id=:user_id AND status<>'deleted' ORDER BY created_at DESC"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    )
    items = [
        {
            **{key: value for key, value in dict(row).items() if key != "content_encrypted"},
            "content": decrypt_private(row["content_encrypted"]),
        }
        for row in rows
    ]
    return success({"items": items}, request_id_from_request(request))


@router.post("/account/ai-memory/items", status_code=201)
async def add_memory_candidate(
    payload: AiMemoryCandidateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await create_memory_candidate(session, principal.user.id, payload),
        request_id_from_request(request),
    )


@router.patch("/account/ai-memory/items/{item_id}")
async def update_memory_item(
    item_id: UUID,
    payload: AiMemoryUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    validate_memory_content(payload.content)
    value = await session.scalar(
        text(
            "UPDATE ai_memory_items SET content_encrypted=:content,content_hmac=:hash,status='active',certainty='user_confirmed',user_confirmed=true,updated_at=now() WHERE id=:id AND user_id=:user_id AND status<>'deleted' RETURNING id"
        ),
        {
            "content": encrypt_private(payload.content),
            "hash": searchable_hmac(payload.content),
            "id": item_id,
            "user_id": principal.user.id,
        },
    )
    if value is None:
        raise VavError("AI_MEMORY_ITEM_NOT_FOUND", "Memory item was not found.", status_code=404)
    await audit(
        session,
        "privacy.ai_memory.updated",
        "ai_memory_item",
        item_id,
        actor_id=principal.user.id,
        context={"user_confirmed": True},
    )
    await session.commit()
    return success({"id": str(item_id), "status": "active"}, request_id_from_request(request))


async def memory_status_action(
    item_id: UUID,
    target: str,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE ai_memory_items SET status=:status,user_confirmed=:confirmed,updated_at=now() WHERE id=:id AND user_id=:user_id AND status IN ('candidate','user_approval_required') RETURNING id"
        ),
        {
            "status": target,
            "confirmed": target == "active",
            "id": item_id,
            "user_id": principal.user.id,
        },
    )
    if value is None:
        raise VavError(
            "AI_MEMORY_ITEM_ACTION_INVALID", "Memory item cannot transition.", status_code=409
        )
    await audit(
        session,
        "privacy.ai_memory.approved" if target == "active" else "privacy.ai_memory.rejected",
        "ai_memory_item",
        item_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(item_id), "status": target}, request_id_from_request(request))


@router.post("/account/ai-memory/items/{item_id}/approve")
async def approve_memory_item(
    item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await memory_status_action(item_id, "active", request, principal, session)


@router.post("/account/ai-memory/items/{item_id}/reject")
async def reject_memory_item(
    item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await memory_status_action(item_id, "rejected", request, principal, session)


@router.delete("/account/ai-memory/items/{item_id}")
async def delete_memory_item(
    item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE ai_memory_items SET content_encrypted='deleted',status='deleted',deleted_at=now(),updated_at=now() WHERE id=:id AND user_id=:user_id AND status<>'deleted' RETURNING id"
        ),
        {"id": item_id, "user_id": principal.user.id},
    )
    if value is None:
        raise VavError("AI_MEMORY_ITEM_NOT_FOUND", "Memory item was not found.", status_code=404)
    await session.execute(
        text(
            "INSERT INTO ai_memory_cleanup_events (user_id,memory_item_id,cleanup_type,vector_removed,cache_invalidated) VALUES (:user_id,:item_id,'delete',true,true)"
        ),
        {"user_id": principal.user.id, "item_id": item_id},
    )
    await audit(
        session,
        "privacy.ai_memory.deleted",
        "ai_memory_item",
        item_id,
        actor_id=principal.user.id,
        context={"vector_removed": True, "cache_invalidated": True},
    )
    await session.commit()
    return success({"id": str(item_id), "status": "deleted"}, request_id_from_request(request))


@router.post("/account/ai-memory/clear-all")
async def clear_all_memory(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    count = await clear_ai_memory(session, principal.user.id)
    return success(
        {"deleted_count": count, "vectors_removed": True, "cache_invalidated": True},
        request_id_from_request(request),
    )


@router.get("/account/privacy/access-events")
async def user_sensitive_access_events(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            await session.execute(
                text(
                    "SELECT module_code,asset_code,access_type,purpose,result,occurred_at FROM privacy_sensitive_access_events WHERE subject_user_id=:user_id ORDER BY occurred_at DESC LIMIT 100"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    ]
    return success(
        {"items": rows, "investigation_details_redacted": True}, request_id_from_request(request)
    )
