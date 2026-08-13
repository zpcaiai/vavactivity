"""Pure profile media rules (B15 / PROFILE-001).

No database, network, settings or clock access: the upload limits, the
moderation state machine, the private-access grant and the consent-scoped share
projection are all decided from arguments alone, so every one of them is
testable without PostgreSQL or object storage.

Requirement coverage (PROFILE-001):

* 1-3 photos plus exactly one short video in phase one, enforced server-side
  along with size, duration and MIME type. Client-side validation is a UX
  nicety; this module is the control.
* An MBTI tag and a deterministic profile-completeness score.
* Private media is reachable only through an opaque per-asset token plus a
  short-lived signed access grant - never through a predictable URL.
* An explicit, testable delete/replace lifecycle.
* A moderation hook: every asset starts ``pending`` and only an approved asset
  can be seen by anyone but its owner and the moderators.
* A share projection that contains only approved *and* consented fields.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class ProfileMediaRuleError(Exception):
    """Raised when a caller violates a profile-media rule.

    ``code`` is the stable machine identifier; ``message`` is operator-facing
    English. Member-facing copy is localized in the frontend from ``code``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# PROFILE-001 - upload constraints (server-side)
# ---------------------------------------------------------------------------


class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"


#: Phase-one limits. A member needs at least one photo for a profile to be
#: meaningful, and three is the point where a profile stops being a profile and
#: starts being an album.
MIN_PHOTOS = 1
MAX_PHOTOS = 3

#: Exactly one short video in phase one. "Exactly one" is a product decision,
#: not a technical one, so it is stated as a constant and enforced on upload.
MAX_VIDEOS = 1

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024

MIN_VIDEO_DURATION_SECONDS = 3
MAX_VIDEO_DURATION_SECONDS = 30

#: Closed allow-lists, not a deny-list. An unknown type is rejected rather than
#: passed through to storage, because "not on the banned list" is not the same
#: as "safe to serve back to a browser".
ALLOWED_PHOTO_MIME_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
ALLOWED_VIDEO_MIME_TYPES: frozenset[str] = frozenset({"video/mp4", "video/quicktime"})


@dataclass(frozen=True)
class UploadRequest:
    """What the server knows about a proposed upload before accepting it."""

    kind: MediaKind
    mime_type: str
    byte_size: int
    duration_seconds: float | None = None


def _limits(kind: MediaKind) -> tuple[frozenset[str], int]:
    if kind is MediaKind.PHOTO:
        return ALLOWED_PHOTO_MIME_TYPES, MAX_PHOTO_BYTES
    return ALLOWED_VIDEO_MIME_TYPES, MAX_VIDEO_BYTES


def validate_upload(
    request: UploadRequest,
    *,
    existing_photo_count: int,
    existing_video_count: int,
    replacing_asset_kind: MediaKind | None = None,
) -> None:
    """Enforce every upload constraint server-side.

    ``replacing_asset_kind`` lets a replace reuse this function: the slot being
    replaced is not counted against the limit, so swapping the single video is
    allowed while adding a *second* video is not.

    The count check runs first so a member who is already at the limit gets the
    useful error rather than a size error about a file that was never going to
    be accepted.
    """

    photo_count = existing_photo_count - (1 if replacing_asset_kind is MediaKind.PHOTO else 0)
    video_count = existing_video_count - (1 if replacing_asset_kind is MediaKind.VIDEO else 0)
    if request.kind is MediaKind.PHOTO and photo_count >= MAX_PHOTOS:
        raise ProfileMediaRuleError(
            "MEDIA_PHOTO_LIMIT_REACHED",
            f"At most {MAX_PHOTOS} photos are allowed.",
            details={"max_photos": MAX_PHOTOS, "current": existing_photo_count},
        )
    if request.kind is MediaKind.VIDEO and video_count >= MAX_VIDEOS:
        raise ProfileMediaRuleError(
            "MEDIA_VIDEO_LIMIT_REACHED",
            f"At most {MAX_VIDEOS} video is allowed in this phase.",
            details={"max_videos": MAX_VIDEOS, "current": existing_video_count},
        )

    allowed_types, max_bytes = _limits(request.kind)
    mime = (request.mime_type or "").strip().lower()
    if mime not in allowed_types:
        raise ProfileMediaRuleError(
            "MEDIA_MIME_NOT_ALLOWED",
            "That file type is not accepted.",
            details={"mime_type": mime, "allowed": sorted(allowed_types)},
        )
    if request.byte_size <= 0:
        raise ProfileMediaRuleError("MEDIA_FILE_EMPTY", "The uploaded file is empty.")
    if request.byte_size > max_bytes:
        raise ProfileMediaRuleError(
            "MEDIA_FILE_TOO_LARGE",
            "The uploaded file exceeds the size limit.",
            details={"byte_size": request.byte_size, "max_bytes": max_bytes},
        )
    if request.kind is MediaKind.VIDEO:
        duration = request.duration_seconds
        if duration is None:
            # An unmeasurable duration is rejected: accepting it would mean the
            # length limit is unenforced for exactly the files that hid it.
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_DURATION_UNKNOWN",
                "The video duration could not be determined.",
            )
        if duration < MIN_VIDEO_DURATION_SECONDS:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_TOO_SHORT",
                f"The video must be at least {MIN_VIDEO_DURATION_SECONDS} seconds.",
                details={"duration_seconds": duration},
            )
        if duration > MAX_VIDEO_DURATION_SECONDS:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_TOO_LONG",
                f"The video must be at most {MAX_VIDEO_DURATION_SECONDS} seconds.",
                details={
                    "duration_seconds": duration,
                    "max_duration_seconds": MAX_VIDEO_DURATION_SECONDS,
                },
            )
    elif request.duration_seconds is not None:
        raise ProfileMediaRuleError(
            "MEDIA_DURATION_NOT_APPLICABLE", "A photo does not carry a duration."
        )


# ---------------------------------------------------------------------------
# PROFILE-001 - moderation hook
# ---------------------------------------------------------------------------


class ModerationState(StrEnum):
    """Every asset starts :attr:`PENDING` and is invisible to others until a
    moderator (or an automated classifier acting as one) approves it."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    #: The member removed the asset while it was awaiting review.
    WITHDRAWN = "withdrawn"


#: The safe default. Nothing is public because it merely finished uploading.
DEFAULT_MODERATION_STATE = ModerationState.PENDING

#: The only state in which an asset may be shown to anyone but its owner and a
#: moderator.
PUBLISHABLE_MODERATION_STATES: frozenset[ModerationState] = frozenset({ModerationState.APPROVED})

_MODERATION_TRANSITIONS: dict[ModerationState, frozenset[ModerationState]] = {
    ModerationState.PENDING: frozenset(
        {ModerationState.APPROVED, ModerationState.REJECTED, ModerationState.WITHDRAWN}
    ),
    # Re-review is allowed: a report on a live photo sends it back to pending.
    ModerationState.APPROVED: frozenset({ModerationState.PENDING, ModerationState.REJECTED}),
    # A rejected asset is not silently re-approved; the member re-submits it.
    ModerationState.REJECTED: frozenset({ModerationState.PENDING}),
    ModerationState.WITHDRAWN: frozenset(),
}


def validate_moderation_transition(current: str, target: str) -> None:
    try:
        current_state = ModerationState(current)
        target_state = ModerationState(target)
    except ValueError as exc:
        raise ProfileMediaRuleError(
            "MODERATION_STATE_UNKNOWN", f"Unknown moderation state: {exc}"
        ) from exc
    if target_state not in _MODERATION_TRANSITIONS[current_state]:
        raise ProfileMediaRuleError(
            "MODERATION_TRANSITION_INVALID",
            f"Cannot move moderation state from {current_state} to {target_state}.",
            details={"current": current_state.value, "target": target_state.value},
        )


def require_rejection_reason(reason_code: str | None) -> str:
    """A rejection must carry a machine reason code so the member can be told
    *what* to fix and so moderation quality can be measured."""

    cleaned = (reason_code or "").strip()
    if not cleaned:
        raise ProfileMediaRuleError(
            "MODERATION_REASON_REQUIRED", "A rejection requires a reason code."
        )
    if len(cleaned) > 64 or not all(char.isalnum() or char == "_" for char in cleaned):
        raise ProfileMediaRuleError(
            "MODERATION_REASON_INVALID",
            "A rejection reason code must be a short snake_case identifier.",
            details={"reason_code": cleaned},
        )
    return cleaned


def is_publishable(moderation_state: str) -> bool:
    try:
        return ModerationState(moderation_state) in PUBLISHABLE_MODERATION_STATES
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# PROFILE-001 - asset lifecycle (delete / replace)
# ---------------------------------------------------------------------------


class AssetState(StrEnum):
    UPLOADING = "uploading"
    ACTIVE = "active"
    #: Superseded by a newer asset in the same slot. Kept, not deleted, so a
    #: moderation decision on the old file stays explicable.
    REPLACED = "replaced"
    DELETED = "deleted"


_ASSET_TRANSITIONS: dict[AssetState, frozenset[AssetState]] = {
    AssetState.UPLOADING: frozenset({AssetState.ACTIVE, AssetState.DELETED}),
    AssetState.ACTIVE: frozenset({AssetState.REPLACED, AssetState.DELETED}),
    AssetState.REPLACED: frozenset({AssetState.DELETED}),
    AssetState.DELETED: frozenset(),
}


def validate_asset_transition(current: str, target: str) -> None:
    """Guard the asset lifecycle. A deleted asset is terminal: undelete would
    resurrect bytes the member asked to have removed."""

    try:
        current_state = AssetState(current)
        target_state = AssetState(target)
    except ValueError as exc:
        raise ProfileMediaRuleError("ASSET_STATE_UNKNOWN", f"Unknown asset state: {exc}") from exc
    if target_state not in _ASSET_TRANSITIONS[current_state]:
        raise ProfileMediaRuleError(
            "ASSET_TRANSITION_INVALID",
            f"Cannot move asset from {current_state} to {target_state}.",
            details={"current": current_state.value, "target": target_state.value},
        )


@dataclass(frozen=True)
class MediaAsset:
    """One stored profile media asset."""

    asset_id: UUID
    kind: MediaKind
    state: AssetState
    moderation_state: ModerationState
    position: int
    mime_type: str
    byte_size: int
    access_token: str
    duration_seconds: float | None = None
    rejection_reason_code: str | None = None


def active_assets(assets: Iterable[MediaAsset], kind: MediaKind | None = None) -> list[MediaAsset]:
    """Assets that occupy a slot. ``replaced`` and ``deleted`` never count."""

    return sorted(
        (
            asset
            for asset in assets
            if asset.state is AssetState.ACTIVE and (kind is None or asset.kind is kind)
        ),
        key=lambda asset: (asset.position, str(asset.asset_id)),
    )


@dataclass(frozen=True)
class DeletePlan:
    asset_id: UUID
    target_state: AssetState
    #: Remaining active photos after the delete. Surfaced so the caller can warn
    #: the member their profile will drop below the minimum.
    remaining_photos: int
    profile_falls_below_minimum: bool


def plan_delete(
    assets: Sequence[MediaAsset], *, asset_id: UUID, profile_is_published: bool = False
) -> DeletePlan:
    """Plan an explicit deletion.

    Deleting the last photo of a *published* profile is refused: a published
    profile with no photo is not a valid state, and silently unpublishing the
    profile would be a surprising side effect of a delete button. The member
    replaces the photo, or unpublishes first.
    """

    target = next((asset for asset in assets if asset.asset_id == asset_id), None)
    if target is None:
        raise ProfileMediaRuleError("ASSET_NOT_FOUND", "That media asset does not exist.")
    validate_asset_transition(target.state.value, AssetState.DELETED.value)
    remaining = len(
        [asset for asset in active_assets(assets, MediaKind.PHOTO) if asset.asset_id != asset_id]
    )
    below_minimum = remaining < MIN_PHOTOS
    if target.kind is MediaKind.PHOTO and below_minimum and profile_is_published:
        raise ProfileMediaRuleError(
            "MEDIA_MINIMUM_PHOTOS",
            f"A published profile must keep at least {MIN_PHOTOS} photo.",
            details={"min_photos": MIN_PHOTOS},
        )
    return DeletePlan(
        asset_id=asset_id,
        target_state=AssetState.DELETED,
        remaining_photos=remaining,
        profile_falls_below_minimum=below_minimum,
    )


@dataclass(frozen=True)
class ReplacePlan:
    replaced_asset_id: UUID
    replaced_target_state: AssetState
    new_position: int
    new_moderation_state: ModerationState


def plan_replace(
    assets: Sequence[MediaAsset], *, asset_id: UUID, request: UploadRequest
) -> ReplacePlan:
    """Plan a replace: the candidate starts ``pending`` moderation and inherits
    the slot position; the old asset becomes ``replaced`` only on approval.

    Inheriting the position keeps the member's chosen ordering. Resetting
    moderation is the whole point: a replaced photo has not been reviewed, and
    carrying the old approval over would be a trivial moderation bypass. The
    old approved bytes remain current while review is pending so a rejection
    cannot break an already-published profile.
    """

    target = next((asset for asset in assets if asset.asset_id == asset_id), None)
    if target is None:
        raise ProfileMediaRuleError("ASSET_NOT_FOUND", "That media asset does not exist.")
    if target.kind is not request.kind:
        raise ProfileMediaRuleError(
            "MEDIA_REPLACE_KIND_MISMATCH",
            "A replacement must be the same kind of media.",
            details={"expected": target.kind.value, "received": request.kind.value},
        )
    validate_asset_transition(target.state.value, AssetState.REPLACED.value)
    validate_upload(
        request,
        existing_photo_count=len(active_assets(assets, MediaKind.PHOTO)),
        existing_video_count=len(active_assets(assets, MediaKind.VIDEO)),
        replacing_asset_kind=target.kind,
    )
    return ReplacePlan(
        replaced_asset_id=asset_id,
        replaced_target_state=AssetState.REPLACED,
        new_position=target.position,
        new_moderation_state=DEFAULT_MODERATION_STATE,
    )


# ---------------------------------------------------------------------------
# PROFILE-001 - opaque tokens and short-lived access grants
# ---------------------------------------------------------------------------

#: Characters of the opaque token. 26 base32 characters is ~128 bits: not
#: enumerable, and short enough to sit in a path segment.
ASSET_TOKEN_LENGTH = 26

DEFAULT_GRANT_TTL_SECONDS = 300
MAX_GRANT_TTL_SECONDS = 900


def derive_asset_token(asset_id: UUID, *, secret: str) -> str:
    """Derive the opaque per-asset token.

    Keyed with a server secret so the token cannot be computed from the asset id
    (or from a sequence number, or from the owner's user id). It is
    deterministic, so a re-read produces the same URL and CDN caching works, but
    it is unguessable without the secret - which is what "not reachable through
    a predictable URL" actually requires (PROFILE-001).
    """

    if not secret:
        raise ProfileMediaRuleError("MEDIA_SECRET_REQUIRED", "A media token secret is required.")
    digest = hmac.new(secret.encode("utf-8"), str(asset_id).encode("utf-8"), hashlib.sha256)
    return base64.b32encode(digest.digest()).decode("ascii").rstrip("=")[:ASSET_TOKEN_LENGTH]


def private_media_path(access_token: str) -> str:
    """The only path shape private media is served from."""

    token = (access_token or "").strip()
    if len(token) != ASSET_TOKEN_LENGTH or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for character in token
    ):
        raise ProfileMediaRuleError(
            "MEDIA_TOKEN_INVALID", "A private media token must be a fixed base32 value."
        )
    return f"/media/private/{token}"


def assert_url_is_not_predictable(url: str, *, asset_id: UUID, owner_id: UUID) -> None:
    """Fail if an identifier that a caller could guess leaked into a media URL.

    Catches the classic regression where someone "simplifies" the media route
    back to ``/media/{asset_id}`` and quietly makes every private photo
    enumerable.
    """

    lowered = (url or "").lower()
    for label, value in (("asset_id", asset_id), ("owner_id", owner_id)):
        if str(value).lower() in lowered:
            raise ProfileMediaRuleError(
                "MEDIA_URL_PREDICTABLE",
                "A private media URL may not embed a guessable identifier.",
                details={"field": label},
            )


@dataclass(frozen=True)
class AccessGrant:
    """Short-lived API authorization evidence for one viewer and asset.

    A storage presigned URL issued after this check is still a bearer capability
    during its TTL; this signature does not magically bind S3 to the viewer.
    """

    access_token: str
    viewer_id: UUID
    expires_at: datetime
    signature: str


def _grant_message(access_token: str, viewer_id: UUID, expires_at: datetime) -> bytes:
    return f"{access_token}|{viewer_id}|{expires_at.astimezone(UTC).isoformat()}".encode()


def issue_access_grant(
    *,
    access_token: str,
    viewer_id: UUID,
    now: datetime,
    secret: str,
    ttl_seconds: int = DEFAULT_GRANT_TTL_SECONDS,
) -> AccessGrant:
    """Mint a signed grant.

    The signed authorization record is bound to a viewer and asset and expires
    in minutes. A resulting direct S3 URL is transferable, so callers must treat
    it as a secret bearer capability and refresh it only after reauthorization.
    """

    if now.tzinfo is None:
        raise ProfileMediaRuleError("MEDIA_NAIVE_DATETIME", "now must be timezone-aware.")
    if not 1 <= ttl_seconds <= MAX_GRANT_TTL_SECONDS:
        raise ProfileMediaRuleError(
            "MEDIA_GRANT_TTL_INVALID",
            f"A media access grant may live at most {MAX_GRANT_TTL_SECONDS} seconds.",
            details={"ttl_seconds": ttl_seconds},
        )
    if not secret:
        raise ProfileMediaRuleError("MEDIA_SECRET_REQUIRED", "A media token secret is required.")
    expires_at = now + timedelta(seconds=ttl_seconds)
    signature = hmac.new(
        secret.encode("utf-8"), _grant_message(access_token, viewer_id, expires_at), hashlib.sha256
    ).hexdigest()
    return AccessGrant(
        access_token=access_token,
        viewer_id=viewer_id,
        expires_at=expires_at,
        signature=signature,
    )


def verify_access_grant(grant: AccessGrant, *, viewer_id: UUID, now: datetime, secret: str) -> None:
    """Validate a grant at fetch time. Raises with a distinct code per failure."""

    if now.tzinfo is None:
        raise ProfileMediaRuleError("MEDIA_NAIVE_DATETIME", "now must be timezone-aware.")
    if grant.viewer_id != viewer_id:
        raise ProfileMediaRuleError(
            "MEDIA_GRANT_WRONG_VIEWER", "This access grant belongs to a different viewer."
        )
    expected = hmac.new(
        secret.encode("utf-8"),
        _grant_message(grant.access_token, grant.viewer_id, grant.expires_at),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, grant.signature or ""):
        raise ProfileMediaRuleError(
            "MEDIA_GRANT_SIGNATURE_INVALID", "The access grant signature does not match."
        )
    if now > grant.expires_at:
        raise ProfileMediaRuleError(
            "MEDIA_GRANT_EXPIRED",
            "This access grant has expired.",
            details={"expires_at": grant.expires_at.astimezone(UTC).isoformat()},
        )


# ---------------------------------------------------------------------------
# PROFILE-001 - MBTI tag
# ---------------------------------------------------------------------------

#: The sixteen four-letter codes. Stored as a closed enum rather than free text
#: so the tag stays filterable and cannot become a second bio field.
MBTI_TYPES: frozenset[str] = frozenset(
    {
        "ISTJ",
        "ISFJ",
        "INFJ",
        "INTJ",
        "ISTP",
        "ISFP",
        "INFP",
        "INTP",
        "ESTP",
        "ESFP",
        "ENFP",
        "ENTP",
        "ESTJ",
        "ESFJ",
        "ENFJ",
        "ENTJ",
    }
)


def normalize_mbti(value: str | None) -> str | None:
    """Normalize an MBTI tag, or ``None`` when the member left it blank.

    Blank is a first-class answer: MBTI is optional and an empty value must not
    be coerced into a default type.
    """

    cleaned = (value or "").strip().upper()
    if not cleaned:
        return None
    if cleaned not in MBTI_TYPES:
        raise ProfileMediaRuleError(
            "MBTI_TYPE_UNKNOWN",
            "That is not one of the sixteen MBTI types.",
            details={"value": cleaned},
        )
    return cleaned


# ---------------------------------------------------------------------------
# PROFILE-001 - profile completeness
# ---------------------------------------------------------------------------

#: Weights sum to 100 so the score is a percentage with no rounding drift.
#: Photos dominate because a profile without a photo is functionally empty.
COMPLETENESS_WEIGHTS: Mapping[str, int] = {
    "photo_primary": 30,
    "photo_additional": 15,
    "video": 20,
    "mbti": 10,
    "intro": 15,
    "city": 10,
}


@dataclass(frozen=True)
class CompletenessInput:
    approved_photo_count: int = 0
    has_approved_video: bool = False
    mbti: str | None = None
    intro_length: int = 0
    city_code: str | None = None


@dataclass(frozen=True)
class CompletenessScore:
    percent: int
    #: Stable codes for the missing pieces, in a fixed order, so the frontend
    #: can render a checklist without the backend shipping any copy.
    missing_codes: tuple[str, ...]
    earned: Mapping[str, int]


MIN_INTRO_LENGTH_FOR_CREDIT = 10


def compute_completeness(data: CompletenessInput) -> CompletenessScore:
    """Deterministic completeness percentage.

    Only *approved* media counts. Crediting pending uploads would let the score
    jump on upload and fall back on rejection, which reads as a bug to the
    member and rewards submitting anything at all.
    """

    if data.approved_photo_count < 0:
        raise ProfileMediaRuleError(
            "COMPLETENESS_INPUT_INVALID", "approved_photo_count cannot be negative."
        )
    earned: dict[str, int] = {}
    if data.approved_photo_count >= 1:
        earned["photo_primary"] = COMPLETENESS_WEIGHTS["photo_primary"]
    if data.approved_photo_count >= 2:
        earned["photo_additional"] = COMPLETENESS_WEIGHTS["photo_additional"]
    if data.has_approved_video:
        earned["video"] = COMPLETENESS_WEIGHTS["video"]
    if data.mbti:
        earned["mbti"] = COMPLETENESS_WEIGHTS["mbti"]
    if data.intro_length >= MIN_INTRO_LENGTH_FOR_CREDIT:
        earned["intro"] = COMPLETENESS_WEIGHTS["intro"]
    if data.city_code:
        earned["city"] = COMPLETENESS_WEIGHTS["city"]
    missing = tuple(key for key in COMPLETENESS_WEIGHTS if key not in earned)
    return CompletenessScore(
        percent=sum(earned.values()), missing_codes=missing, earned=dict(earned)
    )


# ---------------------------------------------------------------------------
# PROFILE-001 - consent-scoped share card
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShareConsent:
    """Per-field consent for the profile share card.

    Every flag defaults to ``False``. A share card is a copy of someone's face
    and personality that travels outside the app; nothing goes into it that the
    member did not switch on.
    """

    share_enabled: bool = False
    share_photos: bool = False
    share_video: bool = False
    share_mbti: bool = False
    share_intro: bool = False
    share_city: bool = False


#: The closed set of keys a share projection may contain.
SHARE_PROJECTION_FIELDS: frozenset[str] = frozenset(
    {
        "user_id",
        "display_name",
        "photo_tokens",
        "video_token",
        "mbti",
        "intro",
        "city_code",
        "completeness_percent",
    }
)


def build_share_projection(
    *,
    user_id: UUID,
    display_name: str,
    consent: ShareConsent,
    assets: Sequence[MediaAsset],
    mbti: str | None = None,
    intro: str | None = None,
    city_code: str | None = None,
    completeness_percent: int = 0,
) -> dict[str, object]:
    """Build the share card payload from approved *and* consented data only.

    Two independent gates apply to every field: the moderation state of the
    underlying asset, and the member's per-field consent. A field passes only if
    both allow it, and the key is omitted entirely rather than emitted as
    ``null`` - so a consumer cannot infer "this member has a video but hid it".
    """

    if not consent.share_enabled:
        raise ProfileMediaRuleError(
            "PROFILE_SHARE_NOT_CONSENTED",
            "This member has not enabled profile sharing.",
        )
    payload: dict[str, object] = {
        "user_id": str(user_id),
        "display_name": (display_name or "").strip()[:64] or f"member-{str(user_id)[:8]}",
        "completeness_percent": int(completeness_percent),
    }
    if consent.share_photos:
        tokens = [
            asset.access_token
            for asset in active_assets(assets, MediaKind.PHOTO)
            if is_publishable(asset.moderation_state.value)
        ]
        if tokens:
            payload["photo_tokens"] = tokens[:MAX_PHOTOS]
    if consent.share_video:
        video = next(
            (
                asset
                for asset in active_assets(assets, MediaKind.VIDEO)
                if is_publishable(asset.moderation_state.value)
            ),
            None,
        )
        if video is not None:
            payload["video_token"] = video.access_token
    if consent.share_mbti and mbti:
        payload["mbti"] = normalize_mbti(mbti)
    if consent.share_intro:
        text_value = (intro or "").strip()
        if text_value:
            payload["intro"] = text_value[:200]
    if consent.share_city and city_code:
        payload["city_code"] = city_code.strip().upper()
    assert_share_projection(payload)
    return payload


def assert_share_projection(payload: Mapping[str, object]) -> None:
    """Fail if the share projection carries anything outside the closed set."""

    extra = sorted(set(payload) - SHARE_PROJECTION_FIELDS)
    if extra:
        raise ProfileMediaRuleError(
            "PROFILE_SHARE_PROJECTION_LEAK",
            "The profile share card may only expose approved fields.",
            details={"fields": extra},
        )
