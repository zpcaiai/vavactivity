from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from vav.models.base import Base


def uuid_pk() -> MappedColumn[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_at() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at() -> MappedColumn[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CounselingMentor(Base):
    __tablename__ = "counseling_mentors"

    id: Mapped[UUID] = uuid_pk()
    mentor_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    linked_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    service_languages: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    specialty_topics: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    internal_profile_encrypted: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CounselingMentorLocalization(Base):
    __tablename__ = "counseling_mentor_localizations"
    __table_args__ = (UniqueConstraint("mentor_id", "locale"), UniqueConstraint("locale", "slug"))

    id: Mapped[UUID] = uuid_pk()
    mentor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    public_name: Mapped[str] = mapped_column(String(200), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(500))
    biography_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    scope_statement: Mapped[str] = mapped_column(Text, nullable=False)
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CounselingServiceDefinition(Base):
    __tablename__ = "counseling_services"

    id: Mapped[UUID] = uuid_pk()
    service_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    delivery_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    participant_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_before_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    buffer_after_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    booking_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'request_and_confirm'")
    )
    payment_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    free_access: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    catalog_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id")
    )
    catalog_sku_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id")
    )
    cancellation_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    no_show_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    scope_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    min_notice_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1440")
    )
    max_advance_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("90")
    )
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CounselingServiceLocalization(Base):
    __tablename__ = "counseling_service_localizations"
    __table_args__ = (UniqueConstraint("service_id", "locale"), UniqueConstraint("locale", "slug"))

    id: Mapped[UUID] = uuid_pk()
    service_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_services.id")
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    description_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    scope_notice: Mapped[str] = mapped_column(Text, nullable=False)
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )


class CounselingMentorService(Base):
    __tablename__ = "counseling_mentor_services"
    __table_args__ = (UniqueConstraint("mentor_id", "service_id"),)

    id: Mapped[UUID] = uuid_pk()
    mentor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    service_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_services.id")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))


class CounselingAvailabilityRule(Base):
    __tablename__ = "counseling_availability_rules"

    id: Mapped[UUID] = uuid_pk()
    mentor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    service_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_services.id")
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    local_start_time: Mapped[time] = mapped_column(nullable=False)
    local_end_time: Mapped[time] = mapped_column(nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    daily_limit: Mapped[int | None] = mapped_column(Integer)
    weekly_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))


class CounselingAvailabilityOverride(Base):
    __tablename__ = "counseling_availability_overrides"

    id: Mapped[UUID] = uuid_pk()
    mentor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    override_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_encrypted: Mapped[str | None] = mapped_column(Text)


class CounselingSlotHold(Base):
    __tablename__ = "counseling_slot_holds"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    mentor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    service_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_services.id")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at()


class CounselingAppointment(Base):
    __tablename__ = "counseling_appointments"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    appointment_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    mentor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_mentors.id")
    )
    service_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_services.id")
    )
    slot_hold_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_slot_holds.id")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    intake_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    intake_response_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'not_required'")
    )
    entitlement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id")
    )
    credit_reservation_status: Mapped[str | None] = mapped_column(String(32))
    cancellation_policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    no_show_policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CounselingAppointmentHistory(Base):
    __tablename__ = "counseling_appointment_history"

    id: Mapped[UUID] = uuid_pk()
    appointment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_appointments.id")
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class CounselingSession(Base):
    __tablename__ = "counseling_sessions"
    __table_args__ = (UniqueConstraint("appointment_id"),)

    id: Mapped[UUID] = uuid_pk()
    appointment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_appointments.id")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    meeting_reference_encrypted: Mapped[str | None] = mapped_column(Text)
    private_location_encrypted: Mapped[str | None] = mapped_column(Text)
    recording_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    transcription_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = created_at()


class CounselingRecord(Base):
    __tablename__ = "counseling_records"

    id: Mapped[UUID] = uuid_pk()
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_sessions.id")
    )
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    content_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class CounselingFollowUp(Base):
    __tablename__ = "counseling_follow_ups"

    id: Mapped[UUID] = uuid_pk()
    appointment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_appointments.id")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    assigned_to: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    follow_up_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


class CounselingSafetyReferral(Base):
    __tablename__ = "counseling_safety_referrals"

    id: Mapped[UUID] = uuid_pk()
    appointment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("counseling_appointments.id")
    )
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    details_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
