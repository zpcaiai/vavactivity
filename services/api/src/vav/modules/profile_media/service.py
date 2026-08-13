"""Transactional profile media service (B15 / PROFILE-001).

Design notes:

* All business rules live in :mod:`vav.modules.profile_media.domain` so they are
  testable without a database or object storage; this layer only loads state,
  calls domain and persists.
* Registration checks the declared shape before issuing a bounded POST policy.
  Finalization downloads the staged bytes, decodes/parses them server-side,
  normalizes photos and writes a different final key. Client metadata is never
  treated as proof of MIME type, size or video duration.
* Private media never has a predictable URL. The stored ``access_token`` is an
  HMAC of the asset id under a server secret. The API authorizes each grant;
  the resulting short-lived storage URL is explicitly treated as a bearer
  capability, not as viewer-bound transport.
* Free-text member input (the intro) is stored through
  :mod:`vav.modules.privacy.crypto`.
"""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.profile_media.domain import (
    MAX_PHOTO_BYTES,
    MAX_VIDEO_BYTES,
    AssetState,
    CompletenessInput,
    CompletenessScore,
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
from vav.modules.profile_media.inspection import inspect_media
from vav.modules.profile_media.storage import (
    UPLOAD_URL_TTL_SECONDS,
    delete_storage_key,
    measure_object,
    object_key,
    presigned_read_url,
    presigned_upload,
    read_object,
    upload_object_key,
    validate_storage_key,
    write_final_object,
)

MAX_PENDING_PHOTO_UPLOADS = 3
MAX_PENDING_VIDEO_UPLOADS = 1
UPLOAD_FINALIZE_GRACE_SECONDS = 300
MEDIA_INSPECTION_QUEUE_TIMEOUT_SECONDS = 5
_MEDIA_INSPECTION_SLOT = asyncio.Semaphore(1)

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
        raise VavError("PROFILE_MEDIA_DISABLED", "Profile media is not enabled.", status_code=503)


def _upload_ceiling(kind: MediaKind) -> int:
    """The hard byte ceiling storage will enforce for this kind.

    Taken from the domain constants rather than restated, so the policy signed
    into an upload and the policy checked at finalize can never disagree.
    """

    return MAX_PHOTO_BYTES if kind is MediaKind.PHOTO else MAX_VIDEO_BYTES


def _media_secret() -> str:
    # Configured as a SecretStr; the domain signs with a plain str.
    secret = get_settings().profile_media_token_secret
    return secret.get_secret_value() if secret else ""


async def _publish(
    session: AsyncSession,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
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
    metadata: dict[str, Any] | None = None,
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


async def _lock_owner(session: AsyncSession, owner_id: UUID) -> None:
    """Serialize every slot-changing operation for one member.

    Partial unique indexes catch the final collision, but a database error is a
    poor user-facing capacity control and does not protect the published-profile
    minimum during two concurrent deletes. The transaction-scoped advisory lock
    gives register/finalize/replace/delete one shared ordering point.
    """

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"profile-media:{owner_id}"},
    )


async def _require_active_owner(session: AsyncSession, owner_id: UUID) -> None:
    """Recheck account state after acquiring the media write lock.

    Authentication happens before a request waits on the advisory lock.  A
    privacy erasure can commit while that old request is waiting, so trusting
    the dependency's earlier user snapshot would allow media/profile rows to be
    recreated after an erasure completed.
    """

    status = await session.scalar(
        text("SELECT status FROM users WHERE id=:user_id"),
        {"user_id": str(owner_id)},
    )
    if status != "active":
        raise VavError(
            "PROFILE_MEDIA_ACCOUNT_INACTIVE",
            "Profile media cannot be changed for an inactive account.",
            status_code=409,
        )


async def _queue_storage_deletion(
    session: AsyncSession,
    *,
    asset_id: UUID | None,
    owner_id: UUID | None = None,
    access_token: str,
    storage_key: str,
    not_before: datetime | None = None,
) -> None:
    key = validate_storage_key(access_token, storage_key)
    due_at = not_before or _now()
    await session.execute(
        text(
            "INSERT INTO profile_media_storage_deletions "
            "(asset_id,owner_id,access_token,storage_key,state,next_attempt_at) "
            "VALUES (:asset_id,:owner_id,:access_token,:storage_key,'pending',:due_at) "
            "ON CONFLICT (storage_key) DO UPDATE SET "
            "owner_id=COALESCE(EXCLUDED.owner_id,profile_media_storage_deletions.owner_id),"
            "state=CASE WHEN profile_media_storage_deletions.state='completed' "
            "THEN 'completed' ELSE 'pending' END,"
            "last_error=CASE WHEN profile_media_storage_deletions.state='completed' "
            "THEN profile_media_storage_deletions.last_error ELSE NULL END,"
            "next_attempt_at=CASE WHEN profile_media_storage_deletions.state='completed' "
            "THEN profile_media_storage_deletions.next_attempt_at "
            "ELSE GREATEST(profile_media_storage_deletions.next_attempt_at,:due_at) END,"
            "updated_at=now()"
        ),
        {
            "asset_id": str(asset_id) if asset_id else None,
            "owner_id": str(owner_id) if owner_id else None,
            "access_token": access_token,
            "storage_key": key,
            "due_at": due_at,
        },
    )


async def _queue_asset_storage_cleanup(
    session: AsyncSession,
    *,
    asset_id: UUID,
    owner_id: UUID,
    access_token: str,
    storage_key: str | None,
    upload_expires_at: datetime | None,
) -> None:
    """Queue every key an upload may have written.

    The browser POST policy remains replayable until it expires, even after a
    successful DeleteObject.  Staging deletion is therefore delayed until the
    policy/grace deadline.  The derived immutable key is always queued too: a
    worker or database failure after the final PUT but before commit otherwise
    leaves bytes that no database row knows how to find.
    """

    keys: dict[str, datetime | None] = {
        upload_object_key(access_token): upload_expires_at,
        object_key(access_token): None,
    }
    if storage_key:
        keys.setdefault(storage_key, None)
    for key, not_before in keys.items():
        await _queue_storage_deletion(
            session,
            asset_id=asset_id,
            owner_id=owner_id,
            access_token=access_token,
            storage_key=key,
            not_before=not_before,
        )


async def _expire_owner_uploads(session: AsyncSession, owner_id: UUID) -> int:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,access_token,storage_key,upload_expires_at "
                    "FROM profile_media_assets "
                    "WHERE owner_id=:owner_id AND state='uploading' "
                    "AND storage_verified_at IS NULL "
                    "AND upload_expires_at IS NOT NULL AND upload_expires_at < now() "
                    "FOR UPDATE"
                ),
                {"owner_id": str(owner_id)},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        await session.execute(
            text(
                "UPDATE profile_media_assets SET state='deleted',deleted_at=now(),updated_at=now() "
                "WHERE id=:id AND state='uploading'"
            ),
            {"id": str(row["id"])},
        )
        await _queue_asset_storage_cleanup(
            session,
            asset_id=UUID(str(row["id"])),
            owner_id=owner_id,
            access_token=str(row["access_token"]),
            storage_key=str(row["storage_key"]) if row["storage_key"] else None,
            upload_expires_at=row["upload_expires_at"],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Loading assets
# ---------------------------------------------------------------------------


def _asset_from_row(row: dict[str, Any]) -> MediaAsset:
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


async def _load_assets(
    session: AsyncSession, owner_id: UUID, *, for_update: bool = False
) -> list[MediaAsset]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code "
                    "FROM profile_media_assets WHERE owner_id=:owner_id AND state <> 'deleted' "
                    "ORDER BY kind, position, created_at" + (" FOR UPDATE" if for_update else "")
                ),
                {"owner_id": str(owner_id)},
            )
        )
        .mappings()
        .all()
    )
    return [_asset_from_row(dict(row)) for row in rows]


def _asset_payload(asset: MediaAsset, *, owner_id: UUID) -> dict[str, Any]:
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
    session: AsyncSession, *, owner_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Register a new upload slot and return its opaque token.

    The row is created in ``uploading`` / ``pending`` state with the same expiry
    as its storage policy plus a short finalization grace window. Expired rows
    are reaped, but live pending rows do occupy a slot; otherwise one account
    could register and upload an unbounded number of never-finalized 100 MB
    objects.
    """

    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    await _expire_owner_uploads(session, owner_id)
    assets = await _load_assets(session, owner_id, for_update=True)
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

    pending_rows = list(
        (
            await session.execute(
                text(
                    "SELECT kind,position FROM profile_media_assets "
                    "WHERE owner_id=:owner_id AND state='uploading' "
                    "AND storage_verified_at IS NULL "
                    "AND (upload_expires_at IS NULL OR upload_expires_at >= now()) FOR UPDATE"
                ),
                {"owner_id": str(owner_id)},
            )
        )
        .mappings()
        .all()
    )
    active_of_kind = active_assets(assets, request.kind)
    pending_of_kind = [row for row in pending_rows if row["kind"] == request.kind.value]
    pending_limit = (
        MAX_PENDING_PHOTO_UPLOADS if request.kind is MediaKind.PHOTO else MAX_PENDING_VIDEO_UPLOADS
    )
    if len(active_of_kind) + len(pending_of_kind) >= pending_limit:
        raise VavError(
            "MEDIA_UPLOAD_SLOT_UNAVAILABLE",
            "All upload slots for this media type are already active or pending.",
            status_code=409,
        )
    if request.kind is MediaKind.PHOTO:
        occupied = {asset.position for asset in active_of_kind} | {
            int(row["position"]) for row in pending_of_kind
        }
        requested_position = payload.get("position")
        if requested_position is not None and int(requested_position) in occupied:
            raise VavError(
                "MEDIA_POSITION_OCCUPIED",
                "That photo position is already active or pending.",
                status_code=409,
            )
        position = (
            int(requested_position)
            if requested_position is not None
            else next(
                slot for slot in range(1, MAX_PENDING_PHOTO_UPLOADS + 1) if slot not in occupied
            )
        )
    else:
        position = 1
    upload_expires_at = _now() + timedelta(
        seconds=UPLOAD_URL_TTL_SECONDS + UPLOAD_FINALIZE_GRACE_SECONDS
    )
    asset_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO profile_media_assets "
                    "(owner_id,kind,state,moderation_state,position,mime_type,byte_size,duration_seconds,"
                    "access_token,storage_key,upload_expires_at) "
                    "VALUES (:owner_id,:kind,'uploading','pending',:position,:mime_type,:byte_size,"
                    ":duration,'','',:upload_expires_at) RETURNING id"
                ),
                {
                    "owner_id": str(owner_id),
                    "kind": request.kind.value,
                    "position": position,
                    "mime_type": request.mime_type,
                    "byte_size": request.byte_size,
                    "duration": request.duration_seconds,
                    "upload_expires_at": upload_expires_at,
                },
            )
        )
    )
    token = derive_asset_token(asset_id, secret=_media_secret())
    storage_key = upload_object_key(token)
    await session.execute(
        text(
            "UPDATE profile_media_assets SET access_token=:token,storage_key=:storage_key WHERE id=:id"
        ),
        {"token": token, "storage_key": storage_key, "id": str(asset_id)},
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
    upload = presigned_upload(
        token, mime_type=request.mime_type, max_bytes=_upload_ceiling(request.kind)
    )
    await session.commit()
    return {
        "asset_id": str(asset_id),
        # The logical identity of the asset. Kept for logs and comparison; it is
        # not fetchable, and never was — see ``profile_media.storage``.
        "upload_path": private_media_path(token),
        # Where the bytes actually go. Presigned so they never pass through the
        # API, and carrying a size condition storage itself enforces — the
        # declared byte_size is the member's claim, this is the ceiling.
        "upload": upload,
        "upload_expires_at": upload_expires_at,
        "state": AssetState.UPLOADING.value,
        "moderation_state": ModerationState.PENDING.value,
    }


async def finalize_upload(
    session: AsyncSession, *, owner_id: UUID, asset_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Inspect staged bytes and atomically activate their immutable final copy."""

    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code,replaces_asset_id,"
                    "storage_key,storage_etag,checksum_sha256,storage_verified_at,"
                    "upload_expires_at "
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
    if (
        asset.state in {AssetState.ACTIVE, AssetState.UPLOADING}
        and row["storage_verified_at"] is not None
    ):
        # The database commit may have succeeded even if its acknowledgement
        # never reached the client. Treat a retry as success only after binding
        # it back to the same immutable bytes; this removes the false-failure
        # 409 without weakening integrity.
        finalized_key = validate_storage_key(asset.access_token, str(row["storage_key"] or ""))
        measured = await asyncio.to_thread(
            measure_object,
            asset.access_token,
            storage_key=finalized_key,
        )
        if (
            measured is None
            or int(str(measured["byte_size"])) != asset.byte_size
            or (row["storage_etag"] and measured["etag"] != row["storage_etag"])
            or (row["checksum_sha256"] and measured["checksum_sha256"] != row["checksum_sha256"])
        ):
            raise VavError(
                "MEDIA_STORAGE_INTEGRITY_MISMATCH",
                "The stored media no longer matches the finalized asset.",
                status_code=409,
            )
        return await get_my_media(session, owner_id=owner_id)
    if asset.state is not AssetState.UPLOADING:
        raise VavError(
            "MEDIA_UPLOAD_ALREADY_FINALIZED",
            "Only an uploading asset can be finalized.",
            status_code=409,
        )
    if row["upload_expires_at"] is not None and row["upload_expires_at"] < _now():
        await _expire_owner_uploads(session, owner_id)
        await session.commit()
        raise VavError("MEDIA_UPLOAD_EXPIRED", "The upload window has expired.", status_code=409)
    try:
        await asyncio.wait_for(
            _MEDIA_INSPECTION_SLOT.acquire(),
            timeout=MEDIA_INSPECTION_QUEUE_TIMEOUT_SECONDS,
        )
    except TimeoutError as error:
        raise VavError(
            "MEDIA_INSPECTION_BUSY",
            "Media inspection is at capacity. Retry shortly.",
            status_code=503,
        ) from error
    staged_key = validate_storage_key(asset.access_token, str(row["storage_key"] or ""))
    try:
        staged = await asyncio.to_thread(
            read_object,
            asset.access_token,
            storage_key=staged_key,
            max_bytes=_upload_ceiling(asset.kind),
        )
        try:
            inspected = await asyncio.to_thread(
                inspect_media,
                kind=asset.kind,
                payload=cast(bytes, staged["content"]),
                # The value persisted at registration is the declared type signed into
                # the POST policy. Object ContentType is also uploader-controlled and is
                # deliberately ignored here.
                declared_mime_type=asset.mime_type,
            )
        except ProfileMediaRuleError as error:
            status_code = (
                503
                if error.code
                in {"MEDIA_VIDEO_INSPECTION_UNAVAILABLE", "MEDIA_VIDEO_INSPECTION_TIMEOUT"}
                else 422
            )
            raise _fail(error, status_code=status_code) from error
    finally:
        _MEDIA_INSPECTION_SLOT.release()
    request = UploadRequest(
        kind=asset.kind,
        mime_type=inspected.mime_type,
        byte_size=inspected.byte_size,
        duration_seconds=inspected.duration_seconds,
    )
    assets = [
        item
        for item in await _load_assets(session, owner_id, for_update=True)
        if item.asset_id != asset_id
    ]
    replacement = None
    replacing_kind: MediaKind | None = None
    if row["replaces_asset_id"] is not None:
        replacement = (
            (
                await session.execute(
                    text(
                        "SELECT id,kind,state,access_token,storage_key,upload_expires_at "
                        "FROM profile_media_assets "
                        "WHERE id=:id AND owner_id=:owner_id FOR UPDATE"
                    ),
                    {
                        "id": str(row["replaces_asset_id"]),
                        "owner_id": str(owner_id),
                    },
                )
            )
            .mappings()
            .first()
        )
        if replacement is None or replacement["state"] != AssetState.ACTIVE.value:
            raise VavError(
                "MEDIA_REPLACE_TARGET_CHANGED",
                "The media being replaced is no longer active.",
                status_code=409,
            )
        replacing_kind = MediaKind(str(replacement["kind"]))
    try:
        validate_asset_transition(asset.state.value, AssetState.ACTIVE.value)
        validate_upload(
            request,
            existing_photo_count=len(active_assets(assets, MediaKind.PHOTO)),
            existing_video_count=len(active_assets(assets, MediaKind.VIDEO)),
            replacing_asset_kind=replacing_kind,
        )
    except ProfileMediaRuleError as error:
        raise _fail(error) from error

    finalized = await asyncio.to_thread(
        write_final_object,
        asset.access_token,
        content=inspected.content,
        mime_type=inspected.mime_type,
        checksum_sha256=inspected.checksum_sha256,
    )

    # A normal upload becomes active/pending. A finalized replacement remains
    # a verified `uploading` row until moderation: the old approved asset stays
    # live, and approval later swaps both rows atomically. Rejection therefore
    # cannot leave a published profile with no public photo/video.
    finalized_state = (
        AssetState.UPLOADING.value if replacement is not None else AssetState.ACTIVE.value
    )
    await session.execute(
        text(
            "UPDATE profile_media_assets SET state=:state,mime_type=:mime_type,byte_size=:byte_size,"
            "duration_seconds=:duration,moderation_state='pending',storage_key=:storage_key,"
            "storage_etag=:storage_etag,storage_version_id=:storage_version_id,"
            "checksum_sha256=:checksum,storage_verified_at=now(),"
            "updated_at=now() WHERE id=:id"
        ),
        {
            "state": finalized_state,
            "mime_type": request.mime_type,
            "byte_size": request.byte_size,
            "duration": request.duration_seconds,
            "storage_key": str(finalized["storage_key"]),
            "storage_etag": str(finalized["etag"]),
            "storage_version_id": finalized.get("version_id"),
            "checksum": inspected.checksum_sha256,
            "id": str(asset_id),
        },
    )
    await _queue_storage_deletion(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        access_token=asset.access_token,
        storage_key=staged_key,
        # A presigned POST is a bearer capability and can recreate a deleted
        # object until it expires.  Delete only after its grace deadline.
        not_before=row["upload_expires_at"],
    )
    await _audit(
        session,
        asset_id=asset_id,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.upload.finalized",
        metadata={
            "kind": asset.kind.value,
            "byte_size": inspected.byte_size,
            "checksum_sha256": inspected.checksum_sha256,
            "replaces_asset_id": str(row["replaces_asset_id"])
            if row["replaces_asset_id"]
            else None,
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
    session: AsyncSession, *, owner_id: UUID, asset_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Register a replacement candidate while retaining the reviewed asset."""

    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    await _expire_owner_uploads(session, owner_id)
    assets = await _load_assets(session, owner_id, for_update=True)
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

    pending_replacement = await session.scalar(
        text(
            "SELECT id FROM profile_media_assets WHERE owner_id=:owner_id "
            "AND replaces_asset_id=:asset_id AND state='uploading' "
            "AND (storage_verified_at IS NOT NULL OR upload_expires_at IS NULL "
            "OR upload_expires_at >= now()) FOR UPDATE"
        ),
        {"owner_id": str(owner_id), "asset_id": str(asset_id)},
    )
    if pending_replacement is not None:
        raise VavError(
            "MEDIA_REPLACEMENT_ALREADY_PENDING",
            "A replacement upload is already pending for this asset.",
            status_code=409,
        )
    upload_expires_at = _now() + timedelta(
        seconds=UPLOAD_URL_TTL_SECONDS + UPLOAD_FINALIZE_GRACE_SECONDS
    )
    new_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO profile_media_assets "
                    "(owner_id,kind,state,moderation_state,position,mime_type,byte_size,duration_seconds,"
                    "access_token,replaces_asset_id,storage_key,upload_expires_at) "
                    "VALUES (:owner_id,:kind,'uploading',:moderation,:position,:mime_type,:byte_size,"
                    ":duration,'',:replaces,'',:upload_expires_at) RETURNING id"
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
                    "upload_expires_at": upload_expires_at,
                },
            )
        )
    )
    token = derive_asset_token(new_id, secret=_media_secret())
    storage_key = upload_object_key(token)
    await session.execute(
        text(
            "UPDATE profile_media_assets SET access_token=:token,storage_key=:storage_key WHERE id=:id"
        ),
        {"token": token, "storage_key": storage_key, "id": str(new_id)},
    )
    await _audit(
        session,
        asset_id=new_id,
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="member",
        action="profile_media.replacement.registered",
        metadata={"replaced_asset_id": str(asset_id), "position": plan.new_position},
    )
    upload = presigned_upload(
        token, mime_type=request.mime_type, max_bytes=_upload_ceiling(request.kind)
    )
    await session.commit()
    return {
        "asset_id": str(new_id),
        "replaced_asset_id": str(asset_id),
        "upload_path": private_media_path(token),
        "upload": upload,
        "upload_expires_at": upload_expires_at,
        "moderation_state": plan.new_moderation_state.value,
    }


async def delete_asset(session: AsyncSession, *, owner_id: UUID, asset_id: UUID) -> dict[str, Any]:
    """Delete an asset. Terminal - there is no undelete."""

    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    await _expire_owner_uploads(session, owner_id)
    assets = await _load_assets(session, owner_id, for_update=True)
    storage_row = (
        (
            await session.execute(
                text(
                    "SELECT access_token,storage_key,upload_expires_at FROM profile_media_assets "
                    "WHERE id=:id AND owner_id=:owner_id FOR UPDATE"
                ),
                {"id": str(asset_id), "owner_id": str(owner_id)},
            )
        )
        .mappings()
        .first()
    )
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
    if storage_row is not None:
        await _queue_asset_storage_cleanup(
            session,
            asset_id=asset_id,
            owner_id=owner_id,
            access_token=str(storage_row["access_token"]),
            storage_key=(str(storage_row["storage_key"]) if storage_row["storage_key"] else None),
            upload_expires_at=storage_row["upload_expires_at"],
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


async def expire_stale_uploads(session: AsyncSession, *, limit: int = 200) -> int:
    """Mark expired upload registrations deleted and enqueue object cleanup."""

    owner_ids = list(
        (
            await session.scalars(
                text(
                    "SELECT DISTINCT owner_id FROM profile_media_assets "
                    "WHERE state='uploading' AND upload_expires_at IS NOT NULL "
                    "AND storage_verified_at IS NULL "
                    "AND upload_expires_at < now() ORDER BY owner_id LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).all()
    )
    expired = 0
    for raw_owner_id in owner_ids:
        owner_id = UUID(str(raw_owner_id))
        await _lock_owner(session, owner_id)
        expired += await _expire_owner_uploads(session, owner_id)
    await session.commit()
    return expired


async def process_storage_deletions(session: AsyncSession, *, limit: int = 20) -> dict[str, int]:
    """Delete queued objects with retry state durable in PostgreSQL."""

    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,access_token,storage_key,attempts FROM "
                    "profile_media_storage_deletions WHERE state IN ('pending','failed') "
                    "AND next_attempt_at <= now() ORDER BY next_attempt_at,created_at "
                    "FOR UPDATE SKIP LOCKED LIMIT :limit"
                ),
                {"limit": limit},
            )
        )
        .mappings()
        .all()
    )
    completed = 0
    failed = 0
    for row in rows:
        try:
            await asyncio.to_thread(
                delete_storage_key,
                str(row["access_token"]),
                storage_key=str(row["storage_key"]),
            )
        except VavError as error:
            failed += 1
            await session.execute(
                text(
                    "UPDATE profile_media_storage_deletions SET attempts=attempts+1,"
                    # Private-byte deletion never becomes terminal merely
                    # because a provider/credential outage lasted ten tries.
                    # Existing `failed` rows are selected above and revived;
                    # after repeated failures the retry cadence simply slows.
                    "state='pending',"
                    "last_error=:error,next_attempt_at=now()+"
                    "make_interval(secs => LEAST(21600, "
                    "(30 * power(2, LEAST(attempts, 10)))::int)),"
                    "updated_at=now() WHERE id=:id"
                ),
                {"id": str(row["id"]), "error": error.code},
            )
        else:
            completed += 1
            await session.execute(
                text(
                    "UPDATE profile_media_storage_deletions SET state='completed',"
                    "attempts=attempts+1,last_error=NULL,completed_at=now(),updated_at=now() "
                    "WHERE id=:id"
                ),
                {"id": str(row["id"])},
            )
    await session.commit()
    return {"completed": completed, "failed": failed}


# ---------------------------------------------------------------------------
# Private access grants
# ---------------------------------------------------------------------------


async def _build_media_grant(
    row: Mapping[str, Any], *, viewer_id: UUID, ttl_seconds: int
) -> dict[str, Any]:
    """Verify the finalized object and mint its short-lived bearer URL."""

    try:
        grant = issue_access_grant(
            access_token=str(row["access_token"]),
            viewer_id=viewer_id,
            now=_now(),
            secret=_media_secret(),
            ttl_seconds=ttl_seconds,
        )
    except ProfileMediaRuleError as error:
        raise _fail(error) from error
    storage_key = validate_storage_key(str(row["access_token"]), str(row["storage_key"] or ""))
    measured = await asyncio.to_thread(
        measure_object, str(row["access_token"]), storage_key=storage_key
    )
    if measured is None:
        raise VavError(
            "MEDIA_BYTES_MISSING",
            "The finalized media object is unavailable.",
            status_code=409,
        )
    if (
        (row["storage_etag"] and str(measured["etag"]) != str(row["storage_etag"]))
        or (row.get("checksum_sha256") and measured["checksum_sha256"] != row["checksum_sha256"])
        or int(str(measured["byte_size"])) != int(row["byte_size"])
    ):
        raise VavError(
            "MEDIA_STORAGE_INTEGRITY_MISMATCH",
            "The stored media no longer matches the finalized asset.",
            status_code=409,
        )
    return {
        "media_path": private_media_path(grant.access_token),
        "media_url": presigned_read_url(
            grant.access_token, storage_key=storage_key, ttl_seconds=ttl_seconds
        ),
        "expires_at": grant.expires_at,
        "signature": grant.signature,
        "viewer_id": str(viewer_id),
    }


async def issue_media_grant(
    session: AsyncSession, *, viewer_id: UUID, asset_id: UUID, ttl_seconds: int = 300
) -> dict[str, Any]:
    """Issue a short-lived bearer URL after authorizing one viewer.

    The viewer must be the owner, or the asset must be approved *and* covered by
    the owner's share consent. Anything else is a 404, not a 403: a stranger
    must not learn that a hidden asset exists.

    S3 presigned URLs are bearer capabilities; the ``viewer_id`` signature is
    useful audit evidence but cannot stop somebody who receives the final URL
    from replaying it during its short TTL. The API therefore does not describe
    the storage URL itself as viewer-bound.
    """

    media_enabled()
    owner_id_raw = await session.scalar(
        text("SELECT owner_id FROM profile_media_assets WHERE id=:id"),
        {"id": str(asset_id)},
    )
    if owner_id_raw is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(owner_id_raw))
    await _lock_owner(session, owner_id)
    owner_status = await session.scalar(
        text("SELECT status FROM users WHERE id=:user_id"),
        {"user_id": str(owner_id)},
    )
    if owner_status != "active":
        # Preserve the endpoint's non-enumeration contract for non-owners: an
        # inactive/erased owner's asset is indistinguishable from a missing one.
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    row = (
        (
            await session.execute(
                text(
                    "SELECT a.owner_id,a.access_token,a.state,a.moderation_state,a.kind,"
                    "a.storage_key,a.storage_etag,a.checksum_sha256,a.byte_size,a.mime_type,"
                    "a.storage_verified_at,a.replaces_asset_id,"
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
    owner_previewable = (
        row is not None
        and owner_id == viewer_id
        and (
            row["state"] == AssetState.ACTIVE.value
            or (
                row["state"] == AssetState.UPLOADING.value
                and row["storage_verified_at"] is not None
                and row["replaces_asset_id"] is not None
            )
        )
    )
    if row is None or (row["state"] != AssetState.ACTIVE.value and not owner_previewable):
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(row["owner_id"]))
    if owner_id != viewer_id:
        shareable = (
            row["share_enabled"]
            and is_publishable(row["moderation_state"])
            and (
                row["share_photos"] if row["kind"] == MediaKind.PHOTO.value else row["share_video"]
            )
        )
        if not shareable:
            raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    return await _build_media_grant(dict(row), viewer_id=viewer_id, ttl_seconds=ttl_seconds)


async def issue_admin_media_grant(
    session: AsyncSession, *, viewer_id: UUID, asset_id: UUID, ttl_seconds: int = 300
) -> dict[str, Any]:
    """Mint a grant for an authorized moderator, including pending assets."""

    media_enabled()
    owner_id_raw = await session.scalar(
        text("SELECT owner_id FROM profile_media_assets WHERE id=:id"),
        {"id": str(asset_id)},
    )
    if owner_id_raw is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(owner_id_raw))
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT owner_id,access_token,state,storage_key,storage_etag,"
                    "checksum_sha256,byte_size,storage_verified_at,replaces_asset_id "
                    "FROM profile_media_assets WHERE id=:id"
                ),
                {"id": str(asset_id)},
            )
        )
        .mappings()
        .first()
    )
    reviewable = row is not None and (
        row["state"] == AssetState.ACTIVE.value
        or (
            row["state"] == AssetState.UPLOADING.value
            and row["storage_verified_at"] is not None
            and row["replaces_asset_id"] is not None
        )
    )
    if not reviewable:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    assert row is not None
    return await _build_media_grant(dict(row), viewer_id=viewer_id, ttl_seconds=ttl_seconds)


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


async def get_my_media(session: AsyncSession, *, owner_id: UUID) -> dict[str, Any]:
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


async def _load_profile(session: AsyncSession, owner_id: UUID) -> dict[str, Any]:
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


def _completeness(assets: list[MediaAsset], profile: dict[str, Any]) -> CompletenessScore:
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
    return int(score.percent)


async def set_profile_tags(
    session: AsyncSession, *, owner_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Store the MBTI tag, intro and city."""

    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
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


async def get_share_consent(session: AsyncSession, owner_id: UUID) -> dict[str, Any]:
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
    session: AsyncSession, *, owner_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    media_enabled()
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
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


async def get_share_card(session: AsyncSession, *, owner_id: UUID) -> dict[str, Any]:
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
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,owner_id,kind,state,moderation_state,position,mime_type,byte_size,"
                    "access_token,duration_seconds,rejection_reason_code,created_at "
                    "FROM profile_media_assets "
                    "WHERE moderation_state=:state AND (state='active' OR "
                    "(state='uploading' AND storage_verified_at IS NOT NULL "
                    "AND replaces_asset_id IS NOT NULL)) "
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
    session: AsyncSession, *, asset_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Approve, reject or re-queue one asset.

    A rejection must carry a machine reason code, and approval does not survive
    a later replace: the replacement starts pending again.
    """

    media_enabled()
    owner_id_raw = await session.scalar(
        text("SELECT owner_id FROM profile_media_assets WHERE id=:id"),
        {"id": str(asset_id)},
    )
    if owner_id_raw is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(owner_id_raw))
    await _lock_owner(session, owner_id)
    await _require_active_owner(session, owner_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT owner_id,moderation_state,kind,state,replaces_asset_id,"
                    "access_token,storage_key,upload_expires_at "
                    "FROM profile_media_assets WHERE id=:id AND (state='active' OR "
                    "(state='uploading' AND storage_verified_at IS NOT NULL "
                    "AND replaces_asset_id IS NOT NULL)) FOR UPDATE"
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
        if row["state"] == AssetState.UPLOADING.value and target == ModerationState.PENDING.value:
            raise ProfileMediaRuleError(
                "MODERATION_TRANSITION_INVALID",
                "A replacement candidate is already pending review.",
            )
        if target == ModerationState.REJECTED.value:
            reason_code = require_rejection_reason(payload.get("reason_code"))
    except ProfileMediaRuleError as error:
        raise _fail(error, status_code=409) from error

    replacement_target = None
    is_replacement = row["state"] == AssetState.UPLOADING.value
    if is_replacement and target == ModerationState.APPROVED.value:
        replacement_target = (
            (
                await session.execute(
                    text(
                        "SELECT id,state,access_token,storage_key,upload_expires_at "
                        "FROM profile_media_assets WHERE id=:id AND owner_id=:owner_id FOR UPDATE"
                    ),
                    {
                        "id": str(row["replaces_asset_id"]),
                        "owner_id": str(owner_id),
                    },
                )
            )
            .mappings()
            .first()
        )
        if replacement_target is None or replacement_target["state"] != AssetState.ACTIVE.value:
            raise VavError(
                "MEDIA_REPLACE_TARGET_CHANGED",
                "The media being replaced is no longer active.",
                status_code=409,
            )

    if is_replacement and target == ModerationState.APPROVED.value:
        assert replacement_target is not None
        await session.execute(
            text(
                "UPDATE profile_media_assets SET state='replaced',updated_at=now() "
                "WHERE id=:id AND state='active'"
            ),
            {"id": str(replacement_target["id"])},
        )
        await _queue_asset_storage_cleanup(
            session,
            asset_id=UUID(str(replacement_target["id"])),
            owner_id=owner_id,
            access_token=str(replacement_target["access_token"]),
            storage_key=(
                str(replacement_target["storage_key"])
                if replacement_target["storage_key"]
                else None
            ),
            upload_expires_at=replacement_target["upload_expires_at"],
        )
        next_asset_state = AssetState.ACTIVE.value
        deleted_at_sql = "NULL"
    elif is_replacement and target == ModerationState.REJECTED.value:
        next_asset_state = AssetState.DELETED.value
        deleted_at_sql = "now()"
        await _queue_asset_storage_cleanup(
            session,
            asset_id=asset_id,
            owner_id=owner_id,
            access_token=str(row["access_token"]),
            storage_key=str(row["storage_key"]) if row["storage_key"] else None,
            upload_expires_at=row["upload_expires_at"],
        )
    else:
        next_asset_state = str(row["state"])
        deleted_at_sql = "deleted_at"

    await session.execute(
        text(
            "UPDATE profile_media_assets SET state=:asset_state,moderation_state=:state,"
            "rejection_reason_code=:reason_code,moderated_by=:actor,moderated_at=now(),"
            f"deleted_at={deleted_at_sql},updated_at=now() WHERE id=:id"
        ),
        {
            "asset_state": next_asset_state,
            "state": target,
            "reason_code": reason_code,
            "actor": str(actor_id),
            "id": str(asset_id),
        },
    )
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
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Operator takedown. Uses the same terminal delete transition as a member."""

    media_enabled()
    asset_id = UUID(str(payload["asset_id"]))
    owner_id_raw = await session.scalar(
        text("SELECT owner_id FROM profile_media_assets WHERE id=:id"), {"id": str(asset_id)}
    )
    if owner_id_raw is None:
        raise VavError("ASSET_NOT_FOUND", "That media asset does not exist.", status_code=404)
    owner_id = UUID(str(owner_id_raw))
    await _lock_owner(session, owner_id)
    assets = await _load_assets(session, owner_id, for_update=True)
    storage_row = (
        (
            await session.execute(
                text(
                    "SELECT access_token,storage_key,upload_expires_at FROM profile_media_assets "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(asset_id)},
            )
        )
        .mappings()
        .first()
    )
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
    if storage_row is not None:
        await _queue_asset_storage_cleanup(
            session,
            asset_id=asset_id,
            owner_id=owner_id,
            access_token=str(storage_row["access_token"]),
            storage_key=(str(storage_row["storage_key"]) if storage_row["storage_key"] else None),
            upload_expires_at=storage_row["upload_expires_at"],
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
