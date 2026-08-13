"""Onsite check-in operations ORM models (B08 / CHK-002).

These models document the schema for metadata and tooling; the service layer
queries through raw SQL. Anything security-relevant (the uniqueness that makes a
retried scan idempotent, the reason columns that make an override auditable) is
expressed here *and* as real DDL in migration ``20260812_0105``.

One column in this feature does **not** live here: ``user_contact_points.last_four_hmac``
is added to an existing table by that migration. See ``PATCHES.md`` - the
existing ``UserContactPoint`` model needs the matching attribute, and the phone
write path needs to populate it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
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


class CheckinLookupSession(Base):
    """One phone-last-four search by one operator.

    The row exists so a choice token can be resolved server-side without the
    client ever holding a registration id, and so "who searched for what, when"
    is answerable. Note ``fragment_hmac``: the salted HMAC of four digits, not
    the digits themselves and not anything derived from the whole number.
    """

    __tablename__ = "checkin_lookup_sessions"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    operator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    fragment_hmac: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set only once the operator has picked a candidate with a discriminator.
    #: NULL here means the lookup never resolved to a person, which is the
    #: expected state for an ambiguous search nobody followed up on.
    resolved_registration_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discriminator_kind: Mapped[str | None] = mapped_column(String(32))
    device_reference: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()


class CheckinLookupCandidate(Base):
    """The server-side candidate set a choice token is matched against."""

    __tablename__ = "checkin_lookup_candidates"
    __table_args__ = (UniqueConstraint("lookup_id", "registration_id"),)

    id: Mapped[UUID] = uuid_pk()
    lookup_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("checkin_lookup_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at()


class CheckinOperationEvent(Base):
    """The operator-behaviour trail: lookups, duplicates, refusals, undos.

    Separate from ``activity_checkin_events`` on purpose. That table records
    *attendance transitions* in a vocabulary shared platform-wide; this one
    records what an operator did, including the things that changed nothing
    (a duplicate scan, an out-of-window refusal, a rate-limited burst). Mixing
    them would either pollute the attendance vocabulary or lose the operational
    signal.
    """

    __tablename__ = "checkin_operation_events"
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    registration_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id")
    )
    lookup_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("checkin_lookup_sessions.id")
    )
    operator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    device_reference: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    #: ``registration:device:request_id``. Unique, so a scanner that retries a
    #: lost response lands on the existing row instead of writing a second one.
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    #: Masked only: outcome, window state, device, the ``••••1234`` form of a
    #: searched fragment. Never a phone number, a name or a registration number.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CheckinWindowPolicy(Base):
    """Per-activity override of the deployment's early/late grace minutes."""

    __tablename__ = "checkin_window_policies"

    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), primary_key=True
    )
    early_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CheckinWindowOverride(Base):
    """One admission outside the permitted window, with its stated reason.

    ``reason`` is NOT NULL. The permission answers "who may"; this column is the
    only place that answers "why did they", and an override without one is not
    a record of a decision, it is a record of a click.
    """

    __tablename__ = "checkin_window_overrides"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    operator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    window_state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CheckinLastFourBackfillRun(Base):
    """A booked run of the plaintext-touching ``last_four_hmac`` backfill.

    The migration cannot populate that column: the phone value is encrypted, so
    deriving four digits needs the privacy key, which SQL does not have. This
    table is how an operator requests the job that can, and how the request is
    attributed.
    """

    __tablename__ = "checkin_last_four_backfill_runs"

    id: Mapped[UUID] = uuid_pk()
    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("500"))
    salt_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'v1'")
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    pending_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'queued'"))
    note: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
