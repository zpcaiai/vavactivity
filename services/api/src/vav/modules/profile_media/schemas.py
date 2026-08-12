"""Request payloads for the profile media module (PROFILE-001).

Every constraint declared here is *also* enforced in
:mod:`vav.modules.profile_media.domain`. Pydantic gives a fast, friendly 422;
the domain is the actual control, because a payload can be crafted and a schema
can be relaxed by accident.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


class MediaUploadRequest(_Base):
    """Register an intended upload and receive a storage target.

    ``byte_size``, ``mime_type`` and ``duration_seconds`` are declared by the
    client and re-verified server-side once the bytes land; the values here only
    let the server reject an impossible upload before it starts.
    """

    kind: Literal["photo", "video"]
    mime_type: Annotated[str, Field(min_length=3, max_length=128)]
    byte_size: Annotated[int, Field(ge=1, le=200 * 1024 * 1024)]
    #: Required for a video, forbidden for a photo. The domain enforces both.
    duration_seconds: Annotated[float, Field(ge=0, le=3600)] | None = None
    position: Annotated[int, Field(ge=1, le=3)] | None = None


class MediaReplaceRequest(_Base):
    """Replace one asset in place. The slot position is inherited, moderation
    is reset to ``pending``."""

    kind: Literal["photo", "video"]
    mime_type: Annotated[str, Field(min_length=3, max_length=128)]
    byte_size: Annotated[int, Field(ge=1, le=200 * 1024 * 1024)]
    duration_seconds: Annotated[float, Field(ge=0, le=3600)] | None = None


class MediaFinalizeRequest(_Base):
    """Confirm an upload completed, with the values measured server-side."""

    byte_size: Annotated[int, Field(ge=1, le=200 * 1024 * 1024)]
    mime_type: Annotated[str, Field(min_length=3, max_length=128)]
    duration_seconds: Annotated[float, Field(ge=0, le=3600)] | None = None


class MediaAccessRequest(_Base):
    """Ask for a short-lived signed grant for one private asset."""

    ttl_seconds: Annotated[int, Field(ge=30, le=900)] = 300


# ---------------------------------------------------------------------------
# Profile fields
# ---------------------------------------------------------------------------


class ProfileTagsRequest(_Base):
    mbti: Annotated[str, Field(min_length=4, max_length=4)] | None = None
    intro: Annotated[str, Field(max_length=500)] | None = None
    city_code: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")] | None = None


class ShareConsentRequest(_Base):
    """Per-field consent for the profile share card.

    Every field defaults to ``False``: the safe default is that nothing is
    shareable until the member switches it on (PROFILE-001).
    """

    share_enabled: bool = False
    share_photos: bool = False
    share_video: bool = False
    share_mbti: bool = False
    share_intro: bool = False
    share_city: bool = False


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------


class ModerationDecisionRequest(_Base):
    decision: Literal["approved", "rejected", "pending"]
    #: Required when rejecting. A short snake_case identifier, never free text
    #: shown to the member - the frontend localizes from the code.
    reason_code: Annotated[str, Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")] | None = None
    note: Annotated[str, Field(max_length=1000)] | None = None


class ModerationQueueQuery(_Base):
    state: Literal["pending", "approved", "rejected", "withdrawn"] = "pending"
    limit: Annotated[int, Field(ge=1, le=200)] = 50


class AdminAssetRemovalRequest(_Base):
    asset_id: UUID
    reason: Annotated[str, Field(min_length=4, max_length=1000)]
