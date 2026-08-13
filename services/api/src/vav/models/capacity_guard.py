"""Capacity and waitlist ORM models (B06 / ACT-003).

These models document the schema for metadata and tooling; the service layer
queries through raw SQL. The invariant this module exists to protect - held plus
confirmed seats never exceed capacity - is expressed here *and* as a real CHECK
constraint in migration ``20260812_0106``, because a guard that only lives in
application code is one forgotten lock away from an oversold event.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class ActivityCapacityCounter(Base):
    """The single row every seat decision for one ticket type serializes on.

    It is a denormalized cache of what the registration rows say, and that is
    deliberate: counting registrations under a lock means locking a growing set
    of rows on every reservation, which turns the door queue into a convoy. One
    row, one lock, constant cost.

    ``is_unlimited`` carries the mode explicitly. ``capacity = 0`` with that
    flag false is a bounded ticket type with no seats available.
    """

    __tablename__ = "activity_capacity_counters"
    __table_args__ = (
        CheckConstraint(
            "is_unlimited OR confirmed_seats + held_seats <= capacity",
            name="activity_capacity_counters_not_oversold",
        ),
        CheckConstraint(
            "NOT is_unlimited OR capacity = 0",
            name="activity_capacity_counters_unlimited_zero",
        ),
        CheckConstraint(
            "confirmed_seats >= 0 AND held_seats >= 0",
            name="activity_capacity_counters_non_negative",
        ),
    )

    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), primary_key=True
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: Catalog-derived mode. Finite capacity 0 means sold out, not unlimited.
    is_unlimited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: People who are coming.
    confirmed_seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: Seats reserved by an in-flight registration or a live promotion offer.
    #: Counting only confirmed seats is the classic oversell.
    held_seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    waitlisted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    waitlist_capacity: Mapped[int | None] = mapped_column(Integer)
    sales_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'open'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityCapacityReservation(Base):
    """One idempotent seat request.

    The unique ``idempotency_key`` is what makes a double-tapped registration
    take one seat instead of two, and what makes a retried request after a lost
    response return the original answer rather than a second reservation.
    """

    __tablename__ = "activity_capacity_reservations"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    waitlist_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at()


class ActivityWaitlistPosition(Base):
    """One member's place in the queue for one ticket type.

    A waitlisted registration holds no seat. ``joined_at`` plus ``priority``
    plus the registration id give a total order, so promotion is deterministic
    rather than dependent on how PostgreSQL happened to return the rows.
    """

    __tablename__ = "activity_waitlist_positions"
    __table_args__ = (UniqueConstraint("registration_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    #: Higher wins. Default zero: plain first-come-first-served, which is what
    #: members expect and what an operator has to justify departing from.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'waiting'")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityWaitlistPromotionOffer(Base):
    """A held seat with a deadline and a notification attached.

    ``expires_at`` is NOT NULL and is clamped to the event start: an offer that
    outlives the event holds a seat nobody can use. ``dedupe_key`` is unique per
    (registration, round), so a retried planner cannot notify the same member
    twice for the same release.
    """

    __tablename__ = "activity_waitlist_promotion_offers"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        CheckConstraint("expires_at > offered_at", name="activity_waitlist_offers_ttl_positive"),
    )

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    waitlist_entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_waitlist_positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ActivityCapacityEvent(Base):
    """Append-only log of every seat movement and every cap change.

    This is what answers "the room was full, why does the counter say 3 free"
    after the fact. Nothing here is ever updated or deleted.
    """

    __tablename__ = "activity_capacity_events"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    registration_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
