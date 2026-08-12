"""Profile media ORM models (B15 / PROFILE-001).

These models exist for schema documentation and metadata only; the service layer
uses raw SQL through ``sqlalchemy.text()``.

Structural notes that carry the requirement:

* :class:`ProfileMediaAsset` stores an ``access_token`` and no public path. The
  token is an HMAC of the asset id under a server secret, so private media is
  not reachable by guessing an id or a sequence number.
* ``moderation_state`` defaults to ``pending``: nothing is publishable merely
  because it finished uploading.
* :class:`ProfileShareConsent` defaults every flag to ``false``, so the share
  card is empty until the member opts each field in.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base


class ProfileMediaAsset(Base):
    """One photo or video belonging to a member's profile."""

    __tablename__ = "profile_media_assets"
    __table_args__ = (UniqueConstraint("access_token"),)

    id: Mapped[UUID] = uuid_pk()
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'uploading'")
    )
    #: Safe default: an asset is never publishable until a moderator says so.
    moderation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(8, 2))
    #: Opaque, unguessable handle. The *only* way private media is addressed.
    access_token: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Set on a replacement so the audit trail links old bytes to new.
    replaces_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    rejection_reason_code: Mapped[str | None] = mapped_column(String(64))
    moderated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ProfileMediaProfile(Base):
    """The non-media half of the profile: MBTI, intro, city and completeness."""

    __tablename__ = "profile_media_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    mbti: Mapped[str | None] = mapped_column(String(4))
    #: Member free text, so encrypted at rest through the privacy helpers.
    intro_encrypted: Mapped[str | None] = mapped_column(Text)
    city_code: Mapped[str | None] = mapped_column(String(32))
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Always derived by the domain; never written directly by a caller.
    completeness_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ProfileShareConsent(Base):
    """Per-field consent for the profile share card. Everything defaults off."""

    __tablename__ = "profile_share_consents"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    share_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    share_photos: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    share_video: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    share_mbti: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    share_intro: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    share_city: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ProfileMediaAudit(Base):
    """Append-only audit of uploads, replaces, deletes and moderation decisions."""

    __tablename__ = "profile_media_audits"

    id: Mapped[UUID] = uuid_pk()
    asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    owner_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
