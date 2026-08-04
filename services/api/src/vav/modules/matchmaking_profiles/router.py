"""Member-facing dating-profile API."""

# ruff: noqa: B008, E501
from __future__ import annotations

import base64
import hashlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.matchmaking_profiles import photos as photo_processing
from vav.modules.matchmaking_profiles import preferences as preference_rules
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import DatingProfileViewContext
from vav.modules.matchmaking_profiles.schemas import (
    NarrativeUpdateRequest,
    PhotoUploadRequest,
    PreferenceUpdateRequest,
    PrivacyUpdateRequest,
    ProfileCreateRequest,
    ProfileFieldUpdateRequest,
    SubmitRequest,
)
from vav.modules.matchmaking_profiles.taxonomies import APPROVED_PREFERENCE_CRITERIA

router = APIRouter()

ALLOWED_VISIBILITIES = frozenset({"private", "mutual_only", "verified_members"})


@router.get("/account/dating-profile")
async def get_own_profile(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.get_profile_row(session, principal.user.id)
    if profile is None:
        return success(
            {"exists": False, "eligible_to_create": True}, request_id_from_request(request)
        )
    projection = await service.viewer_projection(
        session,
        profile_id=profile["id"],
        viewer=principal.user,
        context=DatingProfileViewContext.SELF,
    )
    return success(
        {
            "exists": True,
            "profile_id": str(profile["id"]),
            "profile_number": profile["profile_number"],
            "status": profile["status"],
            "review_status": profile["review_status"],
            "version": profile["version"],
            "current_version_number": profile["current_version_number"],
            "approved_version_number": profile["approved_version_number"],
            "default_locale": profile["default_locale"],
            "completeness_basis_points": profile["completeness_basis_points"],
            "projection": projection,
        },
        request_id_from_request(request),
    )


@router.post("/account/dating-profile", status_code=201)
async def create_own_profile(
    payload: ProfileCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    profile = await service.create_profile(session, principal.user, payload.locale)
    return success(
        {
            "profile_id": str(profile["id"]),
            "profile_number": profile["profile_number"],
            "status": profile["status"],
            "privacy_mode": "strict",
        },
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/schema")
async def get_schema(
    request: Request,
    locale: str = "zh-CN",
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    release = await service.active_schema_release(session)
    return success(
        {
            "schema_code": release["schema_code"],
            "semantic_version": release["semantic_version"],
            "sections": sorted(
                {definition["section_code"] for definition in release["field_manifest"]}
            ),
            "fields": release["field_manifest"],
            "completeness_policy": release["completeness_policy"],
            "submission_policy": release["submission_policy"],
            "taxonomies": await service.active_taxonomies(session, locale),
        },
        request_id_from_request(request),
    )


@router.patch("/account/dating-profile")
async def patch_profile_fields(
    payload: ProfileFieldUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if not payload.values:
        raise VavError(
            "DATING_FIELD_UPDATE_EMPTY", "No field values were provided.", status_code=422
        )
    result = await service.update_fields(
        session, principal.user, payload.values, expected_version=payload.expected_version
    )
    return success(result, request_id_from_request(request))


@router.put("/account/dating-profile/narratives")
async def put_narratives(
    payload: NarrativeUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.ai_assisted and not payload.ai_content_confirmed:
        raise VavError(
            "DATING_NARRATIVE_AI_CONFIRMATION_REQUIRED",
            "Confirm AI-assisted text before it is saved as your own statement.",
            status_code=422,
        )
    values = payload.model_dump(
        exclude={"locale", "ai_assisted", "ai_content_confirmed"}, exclude_unset=True
    )
    result = await service.update_narratives(
        session, principal.user, payload.locale, values, ai_assisted=payload.ai_assisted
    )
    return success(result, request_id_from_request(request))


@router.get("/account/dating-profile/completeness")
async def get_completeness(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    return success(
        await service.completeness_view(session, profile["id"]), request_id_from_request(request)
    )


@router.get("/account/dating-profile/photos")
async def list_photos(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    rows = await service.photo_rows(session, profile["id"])
    return success(
        {
            "items": [
                {
                    "photo_id": str(row["id"]),
                    "photo_role": row["photo_role"],
                    "status": row["status"],
                    "visibility": row["visibility"],
                    "sort_order": row["sort_order"],
                    "quality_flags": (row["processing_report"] or {}).get("quality_flags", []),
                    "exif_removed": (row["processing_report"] or {}).get("exif_removed", True),
                    "rejection_reason_code": row["rejection_reason_code"],
                    "rejection_message_safe": row["rejection_message_safe"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        },
        request_id_from_request(request),
    )


@router.post("/account/dating-profile/photos", status_code=201)
async def upload_photo(
    payload: PhotoUploadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise VavError(
            "DATING_PHOTO_CONTENT_INVALID", "The upload could not be decoded.", status_code=422
        ) from exc

    processed = photo_processing.process_image(content, payload.mime_type)
    profile = await service.require_profile(session, principal.user.id)
    object_key = f"private/dating-photos/{profile['id']}/{processed['checksum_sha256']}.jpg"
    media_id = await session.scalar(
        text(
            "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
            "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
            "VALUES ('s3','vav-private',:key,:filename,'image','image/jpeg',:size,:width,:height,:checksum,"
            "'private','processed',:user_id) RETURNING id"
        ),
        {
            "key": object_key,
            "filename": payload.filename[:300],
            "size": processed["byte_size"],
            "width": processed["width"],
            "height": processed["height"],
            "checksum": processed["checksum_sha256"],
            "user_id": principal.user.id,
        },
    )
    result = await service.register_photo(
        session,
        principal.user,
        media_asset_id=UUID(str(media_id)),
        role=payload.photo_role,
        checksum=processed["checksum_sha256"],
        report=processed["report"],
    )
    return success(result, request_id_from_request(request))


@router.post("/account/dating-profile/photos/{photo_id}/primary")
async def make_primary(
    photo_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await service.set_primary_photo(session, principal.user, photo_id),
        request_id_from_request(request),
    )


@router.delete("/account/dating-profile/photos/{photo_id}")
async def remove_photo(
    photo_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await service.delete_photo(session, principal.user, photo_id),
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/preferences")
async def get_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    preference = await service.preference_profile(session, profile["id"])
    criteria = await service.preference_criteria(session, profile["id"])
    return success(
        {
            "criteria": criteria,
            "hard_constraints": preference_rules.hard_constraint_summary(criteria),
            "preference_version": preference["preference_version"],
            "allow_recommendation_relaxation": preference["allow_recommendation_relaxation"],
            "status": preference["status"],
            "visibility": "private_to_owner_and_recommendation_engine",
            "approved_criteria": sorted(APPROVED_PREFERENCE_CRITERIA),
        },
        request_id_from_request(request),
    )


@router.put("/account/dating-profile/preferences")
async def put_preferences(
    payload: PreferenceUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await service.replace_preferences(
        session,
        principal.user,
        [criterion.model_dump() for criterion in payload.criteria],
        allow_relaxation=payload.allow_recommendation_relaxation,
    )
    return success(result, request_id_from_request(request))


@router.get("/account/dating-profile/privacy")
async def get_privacy(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    await service.require_profile(session, principal.user.id)
    overrides = await service.field_visibility_overrides(session, principal.user.id)
    visible = await session.scalar(
        text("SELECT visible_in_matchmaking FROM user_privacy_settings WHERE user_id=:id"),
        {"id": principal.user.id},
    )
    return success(
        {
            "privacy_mode": "strict",
            "visible_in_matchmaking": bool(visible),
            "field_visibility": overrides,
            "contact_details_ever_public": False,
            "ai_profile_access": await service.ai_consent_granted(session, principal.user.id),
        },
        request_id_from_request(request),
    )


@router.put("/account/dating-profile/privacy")
async def put_privacy(
    payload: PrivacyUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    for rule in payload.rules:
        if rule.visibility not in ALLOWED_VISIBILITIES:
            raise VavError(
                "DATING_VISIBILITY_INVALID",
                f"'{rule.visibility}' is not an allowed visibility for dating fields.",
                status_code=422,
            )
        definition = next(
            (
                item
                for item in (await service.active_schema_release(session))["field_manifest"]
                if item["field_code"] == rule.field_code
            ),
            None,
        )
        if definition is None:
            raise VavError(
                "DATING_FIELD_UNKNOWN",
                f"'{rule.field_code}' is not part of the active schema.",
                status_code=422,
            )
        await session.execute(
            text(
                "INSERT INTO user_field_visibility_rules (user_id,data_domain,field_code,visibility) "
                "VALUES (:user_id,:domain,:field,:visibility) "
                "ON CONFLICT (user_id,data_domain,field_code) DO UPDATE SET visibility=EXCLUDED.visibility,updated_at=now()"
            ),
            {
                "user_id": principal.user.id,
                "domain": f"dating_profile.{definition['section_code']}",
                "field": rule.field_code,
                "visibility": rule.visibility,
            },
        )
    if payload.visible_in_matchmaking is not None:
        await session.execute(
            text(
                "UPDATE user_privacy_settings SET visible_in_matchmaking=:value,"
                "settings_version=settings_version+1,updated_at=now() WHERE user_id=:user_id"
            ),
            {"value": payload.visible_in_matchmaking, "user_id": principal.user.id},
        )
    await service.audit(
        session,
        "matchmaking.privacy.updated",
        "dating_profile",
        profile["id"],
        actor_id=principal.user.id,
        context={"field_codes": sorted(rule.field_code for rule in payload.rules)},
    )
    await service.emit_event(session, "dating_profile.privacy_updated", profile["id"], {})
    # A privacy change must reach the recommendation pool immediately.
    await service.queue_projection_rebuild(session, profile["id"], "dating_profile.privacy_updated")
    await service.refresh_completeness(session, profile["id"])
    await session.commit()
    return success(
        {"updated_fields": len(payload.rules), "projection_rebuild_queued": True},
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/preview")
async def preview_profile(
    request: Request,
    view_context: str = "profile_detail",
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    try:
        context = DatingProfileViewContext(view_context)
    except ValueError as exc:
        raise VavError(
            "DATING_VIEW_CONTEXT_INVALID", "Unknown preview context.", status_code=422
        ) from exc
    if context in {DatingProfileViewContext.ADMIN_REVIEW, DatingProfileViewContext.SELF}:
        raise VavError(
            "DATING_VIEW_CONTEXT_NOT_PREVIEWABLE",
            "This context cannot be previewed.",
            status_code=422,
        )
    profile = await service.require_profile(session, principal.user.id)
    payload = await service.load_payload(session, profile["id"])
    release = await service.schema_release_by_id(session, profile["schema_release_id"])
    from vav.modules.matchmaking_profiles.privacy_view import build_projection

    age = service.age_from(await service.protected_date_of_birth(session, principal.user.id))
    display_name = await session.scalar(
        text("SELECT display_name FROM user_profiles WHERE user_id=:id"), {"id": principal.user.id}
    )
    projection = build_projection(
        profile=dict(profile),
        payload=payload,
        field_manifest=release["field_manifest"],
        context=context,
        display_name=str(display_name or "VAV Member"),
        age_years=age,
        age_display_mode=str(payload.get("basic.age_display_mode") or "exact_age"),
        primary_photo=None,
        field_overrides=await service.field_visibility_overrides(session, principal.user.id),
        ai_consent_granted=await service.ai_consent_granted(session, principal.user.id),
    )
    return success(
        {"preview": projection, "is_draft_preview": True}, request_id_from_request(request)
    )


@router.post("/account/dating-profile/submit")
async def submit_profile(
    payload: SubmitRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.submit_profile(session, principal.user, payload.change_summary),
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/review-status")
async def get_review_status(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    return success(
        {
            "status": profile["status"],
            "review_status": profile["review_status"],
            "submitted_at": profile["submitted_at"],
            "approved_version_number": profile["approved_version_number"],
            "current_version_number": profile["current_version_number"],
        },
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/review-feedback")
async def get_review_feedback(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.review_feedback(session, principal.user),
        request_id_from_request(request),
    )


@router.get("/account/dating-profile/versions/{left}/diff/{right}")
async def diff_versions(
    left: int,
    right: int,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    profile = await service.require_profile(session, principal.user.id)
    return success(
        await service.version_diff(session, profile["id"], left, right),
        request_id_from_request(request),
    )


@router.post("/account/dating-profile/pause")
async def pause(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.pause_profile(session, principal.user),
        request_id_from_request(request),
    )


@router.post("/account/dating-profile/reactivate")
async def reactivate(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.reactivate_profile(session, principal.user),
        request_id_from_request(request),
    )


@router.get("/dating-profiles/{profile_id}")
async def view_profile(
    profile_id: UUID,
    request: Request,
    view_context: str = "profile_detail",
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    try:
        context = DatingProfileViewContext(view_context)
    except ValueError as exc:
        raise VavError(
            "DATING_VIEW_CONTEXT_INVALID", "Unknown view context.", status_code=422
        ) from exc
    if context in {DatingProfileViewContext.ADMIN_REVIEW, DatingProfileViewContext.SELF}:
        raise VavError(
            "DATING_VIEW_CONTEXT_NOT_ALLOWED",
            "This view context is not available on this endpoint.",
            status_code=403,
        )
    return success(
        await service.viewer_projection(
            session, profile_id=profile_id, viewer=principal.user, context=context
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profiles/{profile_id}/photos/{photo_id}/view-token")
async def create_view_token(
    profile_id: UUID,
    photo_id: UUID,
    request: Request,
    view_context: str = "profile_detail",
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    try:
        context = DatingProfileViewContext(view_context)
    except ValueError as exc:
        raise VavError(
            "DATING_VIEW_CONTEXT_INVALID", "Unknown view context.", status_code=422
        ) from exc
    owner_profile = await session.scalar(
        text("SELECT dating_profile_id FROM dating_profile_photos WHERE id=:id"), {"id": photo_id}
    )
    if owner_profile is None or UUID(str(owner_profile)) != profile_id:
        raise VavError("DATING_PHOTO_NOT_FOUND", "Photo not found.", status_code=404)
    return success(
        await service.issue_photo_view_token(session, principal.user, photo_id, context=context),
        request_id_from_request(request),
    )


@router.get("/dating-profiles/photos/{photo_id}/content")
async def photo_content(
    photo_id: UUID,
    request: Request,
    token: str,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Resolve a view token. The storage object key is never returned."""
    service.enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.id,t.expires_at,t.revoked_at,t.viewer_user_id,p.status,m.width,m.height "
                    "FROM dating_profile_photo_view_tokens t "
                    "JOIN dating_profile_photos p ON p.id=t.photo_id "
                    "JOIN media_assets m ON m.id=p.media_asset_id "
                    "WHERE t.photo_id=:photo_id AND t.token_hash=:hash"
                ),
                {"photo_id": photo_id, "hash": hashlib.sha256(token.encode()).hexdigest()},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["viewer_user_id"] != principal.user.id:
        raise VavError("DATING_PHOTO_TOKEN_INVALID", "This link is not valid.", status_code=403)
    if row["revoked_at"] is not None:
        raise VavError("DATING_PHOTO_TOKEN_REVOKED", "This link was revoked.", status_code=403)
    expired = await session.scalar(
        text("SELECT expires_at < now() FROM dating_profile_photo_view_tokens WHERE id=:id"),
        {"id": row["id"]},
    )
    if expired:
        raise VavError("DATING_PHOTO_TOKEN_EXPIRED", "This link has expired.", status_code=403)
    await session.execute(
        text(
            "UPDATE dating_profile_photo_view_tokens SET consumed_at=COALESCE(consumed_at, now()) WHERE id=:id"
        ),
        {"id": row["id"]},
    )
    await session.commit()
    return success(
        {
            "photo_id": str(photo_id),
            "status": row["status"],
            "width": row["width"],
            "height": row["height"],
            "delivery": "private_stream",
        },
        request_id_from_request(request),
    )
