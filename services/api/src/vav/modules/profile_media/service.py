"""Transactional profile media service (B15 / PROFILE-001).

Design notes:

* All business rules live in :mod:`vav.modules.profile_media.domain` so they are
  testable without a database or object storage; this layer only loads state,
  calls domain and persists.
* Upload limits are enforced twice: once when the upload is registered, and
  again when it is finalized with the values the server actually measured. A
  client that lies about ``byte_size`` is caught at finalize.
* Private media never has a predictable URL. The stored ``access_token`` is an
  HMAC of the asset id under a server secret, and every fetch additionally
  requires a short-lived, viewer-bound signed grant.
* Free-text member input (the intro) is stored through
  :mod:`vav.modules.privacy.crypto`.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.profile_media.domain import (
    AssetState,
    CompletenessInput,
    MediaAsset,
    MediaKind,
    ModerationState,
    ProfileMediaRuleError,
    ShareConsent,
    UploadRequest,
    active_assets,
    assert_url_is_not_predictable,
    build_share_projection,
    compute_completeness,
    derive_asset_token,
    is_publishable,
    issue_access_grant,
    normalize_mbti,
    plan_delete,
    plan_replace,
    private_media_path,
    require_rejection_reason,
    validate_asset_transition,
    validate_moderation_transition,
    validate_upload,
    verify_access_grant,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: ProfileMediaRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def media_enabled() -> None:
    if not get_settings().profile_media_enabled:
        raise VavError(
            "PROFILE_MEDIA_DISABLED", "Profile media is not enabled.", status_code=503
        )


def _media_secret() -> str:
    return get_settings().profile_media_token_secret


async def _publish(
    session: AsyncSession, topic: str, aggregate_type: str, aggregate_id: UUID, payload: dict
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,:aggregate_type,:id,CAST(:payload AS jsonb))"
        ),
        {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "id": str(aggregate_id),
            "payload": _json(payload),
        },
    )


async def _audit(
    session: AsyncSession,
    *,
    asset_id: UUID | None,
    owner_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    action: str,
    reason: str | None = None,
    metadata: dict | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO profile_media_audits "
            "(asset_id,owner_id,actor_id,actor_kind,action,reason,metadata) "
            "VALUES (:asset_id,:owner_id,:actor_id,:actor_kind,:action,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "asset_id": str(asset_id) if asset_id else None,
            "owner_id": str(owner_id) if owner_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
            "action": action,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# Loading assets
# ---------------------------------------------------------------------------


def _asset_from_row(row: dict) -> MediaAsset:
    return MediaAsset(
        asset_id=UUID(str(row["id"])),
        kind=MediaKind(row["kind"]),
        state=AssetState(row["state"]),
        moderation_state=ModerationState(row["moderation_state"]),
        position=int(row["position"]),
        mime_type=row["mime_type"],
        byte_size=int(row["byte_size"] or 0),
        access_token=row["access_token"],
        duration_seconds=(
            float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
        ),
        rejection_reason_code=row["rejection_reason_code"],
    )


async def _load_assets(session: AsyncSession, owner_id: UUID) -> list[MediaAsset]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code "
                    "FROM profile_media_assets WHERE owner_id=:owner_id AND state <> 'deleted' "
                    "ORDER BY kind, position, created_at"
                ),
                {"owner_id": str(owner_id)},
            )
        )
        .mappings()
        .all()
    )
    return [_asset_from_row(dict(row)) for row in rows]


def _asset_payload(asset: MediaAsset, *, owner_id: UUID) -> dict:
    """Owner-facing asset payload.

    ``media_path`` is derived from the opaque token, never from the asset id,
    and is re-checked here so a refactor cannot reintroduce an enumerable URL.
    """

    path = private_media_path(asset.access_token)
    assert_url_is_not_predictable(path, asset_id=asset.asset_id, owner_id=owner_id)
    return {
        "asset_id": str(asset.asset_id),
        "kind": asset.kind.value,
        "state": asset.state.value,
        "moderation_state": asset.moderation_state.value,
        "rejection_reason_code": asset.rejection_reason_code,
        "position": asset.position,
        "duration_seconds": asset.duration_seconds,
        "media_path": path,
        "is_publishable": is_publishable(asset.moderation_state.value),
    }


# ---------------------------------------------------------------------------
# Upload / replace / delete
# ---------------------------------------------------------------------------


async def register_upload(
    session: AsyncSession, *, owner_id: UUID, payload: dict
) -> dict:
    """Register a new upload slot and return its opaque token.

    The row is created in ``uploading`` / ``pending`` state. It occupies no slot
    until it is finalized, so an abandoned upload cannot lock a member out of
    their own photo limit.
    """

    media_enabled()
    assets = await _load_assets(session, owner_id)
    request = UploadRequest(
        kind=MediaKind(payload["kind"]),
        mime_type=payload["mime_type"],
        byte_size=int(payload["byte_size"]),
        duration_seconds=payload.get("duration_seconds"),
    )
    try:
        validate_upload(
            request,
            existing_photo_count=len(active_assets(assets, MediaKind.PHOTO)),
            existing_video_count=len(active_assets(assets, MediaKind.VIDEO)),
        )
    except ProfileMediaRuleError as error:
        raise _fail(error) from error

    position = payload.get("position") or (
        len(active_assets(assets, request.kind)) + 1
    )
    asset_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO profile_media_assets "
                    "(owner_id,kind,state,moderation_state,position,mime_type,byte_size,duration_seconds,access_token) "
                    "VALUES (:owner_id,:kind,'uploading','pending',:position,:mime_type,:byte_size,:duration,'') RETURNING id"
                ),
                {
                    "owner_id": str(owner_id),
                    "kind": request.kind.value,
                    "position": position,
                    "mime_type": request.mime_type,
                    "byte_size": request.byte_size,
                    "duration": request.duration_seconds,
                },
            )
        )
    )
    token = derive_asset_token(asset_id, secret=_media_secret())
    await session.execute(
        text("UPDATE profile_media_assets SET access_token=:token WHERE id=:id"),
        {"token": token, "id": str(asset_id)},
    )
    await _audit(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.upload.registered",
        metadata={"kind": request.kind.value, "position": position},
    )
    await session.commit()
    return {
        "asset_id": str(asset_id),
        "upload_path": private_media_path(token),
        "state": AssetState.UPLOADING.value,
        "moderation_state": ModerationState.PENDING.value,
    }


async def finalize_upload(
    session: AsyncSession, *, owner_id: UUID, asset_id: UUID, payload: dict
) -> dict:
    """Confirm an upload with the values the server measured.

    The constraints are re-run here against the *measured* bytes, mime type and
    duration, which is what makes the limits real rather than advisory.
    """

    media_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code "
                    "FROM profile_media_assets WHERE id=:id AND owner_id=:owner_id FOR UPDATE"
                ),
                {"id": str(asset_id), "owner_id": str(owner_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    asset = _asset_from_row(dict(row))
    assets = [item for item in await _load_assets(session, owner_id) if item.asset_id != asset_id]
    request = UploadRequest(
        kind=asset.kind,
        mime_type=payload["mime_type"],
        byte_size=int(payload["byte_size"]),
        duration_seconds=payload.get("duration_seconds"),
    )
    try:
        validate_asset_transition(asset.state.value, AssetState.ACTIVE.value)
        validate_upload(
            request,
            existing_photo_count=len(active_assets(assets, MediaKind.PHOTO)),
            existing_video_count=len(active_assets(assets, MediaKind.VIDEO)),
        )
    except ProfileMediaRuleError as error:
        raise _fail(error) from error

    await session.execute(
        text(
            "UPDATE profile_media_assets SET state='active',mime_type=:mime_type,byte_size=:byte_size,"
            "duration_seconds=:duration,moderation_state='pending',updated_at=now() WHERE id=:id"
        ),
        {
            "mime_type": request.mime_type,
            "byte_size": request.byte_size,
            "duration": request.duration_seconds,
            "id": str(asset_id),
        },
    )
    await _publish(
        session,
        "profile_media.asset.submitted.v1",
        "profile_media_asset",
        asset_id,
        {"asset_id": str(asset_id), "owner_id": str(owner_id), "kind": asset.kind.value},
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return await get_my_media(session, owner_id=owner_id)


async def replace_asset(
    session: AsyncSession, *, owner_id: UUID, asset_id: UUID, payload: dict
) -> dict:
    """Replace an asset in its slot, resetting moderation to ``pending``."""

    media_enabled()
    assets = await _load_assets(session, owner_id)
    request = UploadRequest(
        kind=MediaKind(payload["kind"]),
        mime_type=payload["mime_type"],
        byte_size=int(payload["byte_size"]),
        duration_seconds=payload.get("duration_seconds"),
    )
    try:
        plan = plan_replace(assets, asset_id=asset_id, request=request)
    except ProfileMediaRuleError as error:
        raise _fail(error) from error

    await session.execute(
        text(
            "UPDATE profile_media_assets SET state='replaced',updated_at=now() "
            "WHERE id=:id AND owner_id=:owner_id"
        ),
        {"id": str(asset_id), "owner_id": str(owner_id)},
    )
    new_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO profile_media_assets "
                    "(owner_id,kind,state,moderation_state,position,mime_type,byte_size,duration_seconds,"
                    "access_token,replaces_asset_id) "
                    "VALUES (:owner_id,:kind,'uploading',:moderation,:position,:mime_type,:byte_size,:duration,'',:replaces) RETURNING id"
                ),
                {
                    "owner_id": str(owner_id),
                    "kind": request.kind.value,
                    "moderation": plan.new_moderation_state.value,
                    "position": plan.new_position,
                    "mime_type": request.mime_type,
                    "byte_size": request.byte_size,
                    "duration": request.duration_seconds,
                    "replaces": str(asset_id),
                },
            )
        )
    )
    token = derive_asset_token(new_id, secret=_media_secret())
    await session.execute(
        text("UPDATE profile_media_assets SET access_token=:token WHERE id=:id"),
        {"token": token, "id": str(new_id)},
    )
    await _audit(
        session,
        asset_id=new_id,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.asset.replaced",
        metadata={"replaced_asset_id": str(asset_id), "position": plan.new_position},
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return {
        "asset_id": str(new_id),
        "replaced_asset_id": str(asset_id),
        "upload_path": private_media_path(token),
        "moderation_state": plan.new_moderation_state.value,
    }


async def delete_asset(
    session: AsyncSession, *, owner_id: UUID, asset_id: UUID
) -> dict:
    """Delete an asset. Terminal - there is no undelete."""

    media_enabled()
    assets = await _load_assets(session, owner_id)
    published = bool(
        await session.scalar(
            text("SELECT is_published FROM profile_media_profiles WHERE user_id=:user_id"),
            {"user_id": str(owner_id)},
        )
    )
    try:
        plan = plan_delete(assets, asset_id=asset_id, profile_is_published=published)
    except ProfileMediaRuleError as error:
        status = 409 if error.code == "MEDIA_MINIMUM_PHOTOS" else 404
        raise _fail(error, status_code=status) from error

    await session.execute(
        text(
            "UPDATE profile_media_assets SET state='deleted',deleted_at=now(),updated_at=now() "
            "WHERE id=:id AND owner_id=:owner_id"
        ),
        {"id": str(asset_id), "owner_id": str(owner_id)},
    )
    await _audit(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.asset.deleted",
        metadata={"remaining_photos": plan.remaining_photos},
    )
    await _publish(
        session,
        "profile_media.asset.deleted.v1",
        "profile_media_asset",
        asset_id,
        {"asset_id": str(asset_id), "owner_id": str(owner_id)},
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return {
        "asset_id": str(asset_id),
        "remaining_photos": plan.remaining_photos,
        "profile_falls_below_minimum": plan.profile_falls_below_minimum,
    }


# ---------------------------------------------------------------------------
# Private access grants
# ---------------------------------------------------------------------------


async def issue_media_grant(
    session: AsyncSession, *, viewer_id: UUID, asset_id: UUID, ttl_seconds: int = 300
) -> dict:
    """Issue a short-lived grant for one private asset.

    The viewer must be the owner, or the asset must be approved *and* covered by
    the owner's share consent. Anything else is a 404, not a 403: a stranger
    must not learn that a hidden asset exists.
    """

    media_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT a.owner_id,a.access_token,a.state,a.moderation_state,a.kind,"
                    "COALESCE(c.share_enabled,false) AS share_enabled,"
                    "COALESCE(c.share_photos,false) AS share_photos,"
                    "COALESCE(c.share_video,false) AS share_video "
                    "FROM profile_media_assets a "
                    "LEFT JOIN profile_share_consents c ON c.user_id=a.owner_id "
                    "WHERE a.id=:id"
                ),
                {"id": str(asset_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["state"] == AssetState.DELETED.value:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(row["owner_id"]))
    if owner_id != viewer_id:
        shareable = (
            row["share_enabled"]
            and is_publishable(row["moderation_state"])
            and (
                row["share_photos"]
                if row["kind"] == MediaKind.PHOTO.value
                else row["share_video"]
            )
        )
        if not shareable:
            raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    try:
        grant = issue_access_grant(
            access_token=row["access_token"],
            viewer_id=viewer_id,
            now=_now(),
            secret=_media_secret(),
            ttl_seconds=ttl_seconds,
        )
    except ProfileMediaRuleError as error:
        raise _fail(error) from error
    return {
        "media_path": private_media_path(grant.access_token),
        "expires_at": grant.expires_at,
        "signature": grant.signature,
        # Echoed so a caller can prove which viewer the grant is bound to; the
        # signature covers it, so it cannot be swapped.
        "viewer_id": str(viewer_id),
    }


def verify_media_grant(
    *, access_token: str, viewer_id: UUID, expires_at: datetime, signature: str
) -> None:
    """Validate a grant at fetch time. Used by the media-serving edge handler."""

    from vav.modules.profile_media.domain import AccessGrant

    try:
        verify_access_grant(
            AccessGrant(
                access_token=access_token,
                viewer_id=viewer_id,
                expires_at=expires_at,
                signature=signature,
            ),
            viewer_id=viewer_id,
            now=_now(),
            secret=_media_secret(),
        )
    except ProfileMediaRuleError as error:
        raise _fail(error, status_code=403) from error


# ---------------------------------------------------------------------------
# Profile fields, completeness and the share card
# ---------------------------------------------------------------------------


async def get_my_media(session: AsyncSession, *, owner_id: UUID) -> dict:
    media_enabled()
    assets = await _load_assets(session, owner_id)
    profile = await _load_profile(session, owner_id)
    score = _completeness(assets, profile)
    return {
        "assets": [_asset_payload(asset, owner_id=owner_id) for asset in active_assets(assets)],
        "pending_assets": [
            _asset_payload(asset, owner_id=owner_id)
            for asset in assets
            if asset.state is AssetState.UPLOADING
        ],
        "mbti": profile.get("mbti"),
        "intro": profile.get("intro"),
        "city_code": profile.get("city_code"),
        "completeness_percent": score.percent,
        "completeness_missing": list(score.missing_codes),
        "is_published": profile.get("is_published", False),
    }


async def _load_profile(session: AsyncSession, owner_id: UUID) -> dict:
    row = (
        (
            await session.execute(
                text(
                    "SELECT mbti,intro_encrypted,city_code,is_published,completeness_percent "
                    "FROM profile_media_profiles WHERE user_id=:user_id"
                ),
                {"user_id": str(owner_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"mbti": None, "intro": None, "city_code": None, "is_published": False}
    return {
        "mbti": row["mbti"],
        "intro": decrypt_private(row["intro_encrypted"]) if row["intro_encrypted"] else None,
        "city_code": row["city_code"],
        "is_published": bool(row["is_published"]),
        "completeness_percent": row["completeness_percent"],
    }


def _completeness(assets: list[MediaAsset], profile: dict):
    approved_photos = [
        asset
        for asset in active_assets(assets, MediaKind.PHOTO)
        if is_publishable(asset.moderation_state.value)
    ]
    approved_video = any(
        is_publishable(asset.moderation_state.value)
        for asset in active_assets(assets, MediaKind.VIDEO)
    )
    return compute_completeness(
        CompletenessInput(
            approved_photo_count=len(approved_photos),
            has_approved_video=approved_video,
            mbti=profile.get("mbti"),
            intro_length=len(profile.get("intro") or ""),
            city_code=profile.get("city_code"),
        )
    )


async def _refresh_completeness(session: AsyncSession, owner_id: UUID) -> int:
    """Recompute and store the completeness percentage.

    Stored denormalized so a feed query can sort by it, but always derived - the
    column is never written by a caller.
    """

    assets = await _load_assets(session, owner_id)
    profile = await _load_profile(session, owner_id)
    score = _completeness(assets, profile)
    await session.execute(
        text(
            "INSERT INTO profile_media_profiles (user_id,completeness_percent) "
            "VALUES (:user_id,:percent) "
            "ON CONFLICT (user_id) DO UPDATE SET completeness_percent=EXCLUDED.completeness_percent,"
            "updated_at=now()"
        ),
        {"user_id": str(owner_id), "percent": score.percent},
    )
    return score.percent


async def set_profile_tags(
    session: AsyncSession, *, owner_id: UUID, payload: dict
) -> dict:
    """Store the MBTI tag, intro and city."""

    media_enabled()
    try:
        mbti = normalize_mbti(payload.get("mbti"))
    except ProfileMediaRuleError as error:
        raise _fail(error) from error
    intro = (payload.get("intro") or "").strip() or None
    await session.execute(
        text(
            "INSERT INTO profile_media_profiles (user_id,mbti,intro_encrypted,city_code) "
            "VALUES (:user_id,:mbti,:intro,:city_code) "
            "ON CONFLICT (user_id) DO UPDATE SET mbti=EXCLUDED.mbti,"
            "intro_encrypted=EXCLUDED.intro_encrypted,city_code=EXCLUDED.city_code,updated_at=now()"
        ),
        {
            "user_id": str(owner_id),
            "mbti": mbti,
            "intro": encrypt_private(intro) if intro else None,
            "city_code": (payload.get("city_code") or "").strip().upper() or None,
        },
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return await get_my_media(session, owner_id=owner_id)


async def get_share_consent(session: AsyncSession, owner_id: UUID) -> dict:
    row = (
        (
            await session.execute(
                text(
                    "SELECT share_enabled,share_photos,share_video,share_mbti,share_intro,share_city "
                    "FROM profile_share_consents WHERE user_id=:user_id"
                ),
                {"user_id": str(owner_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        # No row means nothing is shared. The safe default is off, everywhere.
        return {
            "share_enabled": False,
            "share_photos": False,
            "share_video": False,
            "share_mbti": False,
            "share_intro": False,
            "share_city": False,
        }
    return {key: bool(value) for key, value in row.items()}


async def set_share_consent(
    session: AsyncSession, *, owner_id: UUID, payload: dict
) -> dict:
    media_enabled()
    await session.execute(
        text(
            "INSERT INTO profile_share_consents "
            "(user_id,share_enabled,share_photos,share_video,share_mbti,share_intro,share_city) "
            "VALUES (:user_id,:share_enabled,:share_photos,:share_video,:share_mbti,:share_intro,:share_city) "
            "ON CONFLICT (user_id) DO UPDATE SET share_enabled=EXCLUDED.share_enabled,"
            "share_photos=EXCLUDED.share_photos,share_video=EXCLUDED.share_video,"
            "share_mbti=EXCLUDED.share_mbti,share_intro=EXCLUDED.share_intro,"
            "share_city=EXCLUDED.share_city,updated_at=now()"
        ),
        {"user_id": str(owner_id), **{key: bool(payload[key]) for key in payload}},
    )
    await _audit(
        session,
        asset_id=None,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.share_consent.updated",
        metadata=payload,
    )
    await session.commit()
    return await get_share_consent(session, owner_id)


async def get_share_card(session: AsyncSession, *, owner_id: UUID) -> dict:
    """Build the consent-scoped share card.

    Two independent gates apply per field: moderation state and consent. The
    domain builds the projection and refuses to emit anything outside the closed
    field set.
    """

    media_enabled()
    consent_row = await get_share_consent(session, owner_id)
    assets = await _load_assets(session, owner_id)
    profile = await _load_profile(session, owner_id)
    display_name = (
        await session.scalar(
            text("SELECT display_name FROM user_profiles WHERE user_id=:user_id"),
            {"user_id": str(owner_id)},
        )
        or ""
    )
    try:
        return build_share_projection(
            user_id=owner_id,
            display_name=display_name,
            consent=ShareConsent(**consent_row),
            assets=assets,
            mbti=profile.get("mbti"),
            intro=profile.get("intro"),
            city_code=profile.get("city_code"),
            completeness_percent=_completeness(assets, profile).percent,
        )
    except ProfileMediaRuleError as error:
        raise _fail(error, status_code=403) from error


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------


async def moderation_queue(
    session: AsyncSession, *, state: str = "pending", limit: int = 50
) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,owner_id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code,created_at "
                    "FROM profile_media_assets "
                    "WHERE moderation_state=:state AND state='active' "
                    "ORDER BY created_at LIMIT :limit"
                ),
                {"state": state, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            **_asset_payload(_asset_from_row(dict(row)), owner_id=UUID(str(row["owner_id"]))),
            "owner_id": str(row["owner_id"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def decide_moderation(
    session: AsyncSession, *, asset_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    """Approve, reject or re-queue one asset.

    A rejection must carry a machine reason code, and approval does not survive
    a later replace: the replacement starts pending again.
    """

    media_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT owner_id,moderation_state,kind FROM profile_media_assets "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(asset_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    target = payload["decision"]
    reason_code: str | None = None
    try:
        validate_moderation_transition(row["moderation_state"], target)
        if target == ModerationState.REJECTED.value:
            reason_code = require_rejection_reason(payload.get("reason_code"))
    except ProfileMediaRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "UPDATE profile_media_assets SET moderation_state=:state,rejection_reason_code=:reason_code,"
            "moderated_by=:actor,moderated_at=now(),updated_at=now() WHERE id=:id"
        ),
        {
            "state": target,
            "reason_code": reason_code,
            "actor": str(actor_id),
            "id": str(asset_id),
        },
    )
    owner_id = UUID(str(row["owner_id"]))
    await _audit(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        actor_id=actor_id,
        actor_kind="admin",
        action=f"profile_media.moderation.{target}",
        reason=payload.get("note"),
        metadata={"from_state": row["moderation_state"], "reason_code": reason_code},
    )
    await _publish(
        session,
        "profile_media.asset.moderated.v1",
        "profile_media_asset",
        asset_id,
        {
            "asset_id": str(asset_id),
            "owner_id": str(owner_id),
            "moderation_state": target,
            "reason_code": reason_code,
        },
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return {
        "asset_id": str(asset_id),
        "moderation_state": target,
        "rejection_reason_code": reason_code,
    }


async def admin_remove_asset(
    session: AsyncSession, *, actor_id: UUID, payload: dict
) -> dict:
    """Operator takedown. Uses the same terminal delete transition as a member."""

    media_enabled()
    asset_id = UUID(str(payload["asset_id"]))
    owner_id_raw = await session.scalar(
        text("SELECT owner_id FROM profile_media_assets WHERE id=:id"), {"id": str(asset_id)}
    )
    if owner_id_raw is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(owner_id_raw))
    assets = await _load_assets(session, owner_id)
    try:
        # ``profile_is_published=False``: a takedown is not blocked by the
        # minimum-photo rule, because leaving a violating photo up is worse.
        plan_delete(assets, asset_id=asset_id, profile_is_published=False)
    except ProfileMediaRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE profile_media_assets SET state='deleted',deleted_at=now(),updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(asset_id)},
    )
    await _audit(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="profile_media.asset.removed_by_admin",
        reason=payload["reason"],
    )
    await _refresh_completeness(session, owner_id)
    await session.commit()
    return {"asset_id": str(asset_id), "owner_id": str(owner_id)}
