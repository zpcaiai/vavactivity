"""Attendee-preview and follow-graph ORM models (B14: ATT-001, SOC-001).

These models exist for schema documentation and metadata only; the service layer
uses raw SQL through ``sqlalchemy.text()``.

Two structural decisions carry the requirements:

* :class:`AttendeePreviewConsent` defaults ``consent_state`` to ``not_asked``
  and the preview query treats a *missing row* the same way, so opt-in is the
  behaviour of the schema and not just of the code (ATT-001 / DEC-002).
* :class:`SocialFollow` and :class:`SocialWantToMeet` are separate tables, and
  neither is the like table (likes live in ``activity_selection_items``, owned
  by the post-event module). Three relations, three stores (SOC-001).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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

# ---------------------------------------------------------------------------
# ATT-001 attendee preview consent
# ---------------------------------------------------------------------------


class AttendeePreviewConsent(Base):
    """One registration's answer to the attendee-preview prompt.

    ``not_asked`` is the default *and* the meaning of a missing row, so a
    backfill that creates no rows leaves everyone hidden.
    """

    __tablename__ = "attendee_preview_consents"
    __table_args__ = (UniqueConstraint("registration_id"),)

    id: Mapped[UUID] = uuid_pk()
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    consent_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'not_asked'")
    )
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The optional one-line intro. Member free text, so encrypted at rest.
    intro_line_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AttendeePreviewConsentHistory(Base):
    """Append-only consent history. A withdrawal is a fact, not an edit."""

    __tablename__ = "attendee_preview_consent_history"

    id: Mapped[UUID] = uuid_pk()
    registration_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String(16))
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    note_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


# ---------------------------------------------------------------------------
# SOC-001 follow graph
# ---------------------------------------------------------------------------


class SocialFollow(Base):
    """A one-directional, non-romantic subscription.

    Not a like: a like is private, event-scoped and only revealed when mutual.
    Not a want-to-meet: that is event-scoped intent. Keeping the three apart is
    the whole requirement (SOC-001).
    """

    __tablename__ = "social_follows"
    __table_args__ = (UniqueConstraint("follower_id", "followee_id"),)

    id: Mapped[UUID] = uuid_pk()
    follower_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    followee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    followed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unfollowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SocialWantToMeet(Base):
    """Event-scoped intent to meet someone. Visible to operators, not the target."""

    __tablename__ = "social_want_to_meet"
    __table_args__ = (UniqueConstraint("user_id", "target_user_id", "activity_id"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    target_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    created_at: Mapped[datetime] = created_at()


class SocialNotificationPreference(Base):
    """Per-member notification switches for the social module."""

    __tablename__ = "social_notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    followed_user_registered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SocialNotificationDelivery(Base):
    """One delivered social notification, keyed by an idempotent dedupe key.

    The unique constraint on ``dedupe_key`` is the actual de-duplication: a
    retried fan-out inserts nothing and therefore sends nothing (SOC-001).
    """

    __tablename__ = "social_notification_deliveries"
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    id: Mapped[UUID] = uuid_pk()
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id")
    )
    notification_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()


class AttendeeSocialAudit(Base):
    """Append-only audit of consent decisions and block-driven follow changes."""

    __tablename__ = "attendee_social_audits"

    id: Mapped[UUID] = uuid_pk()
    subject_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id")
    )
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
