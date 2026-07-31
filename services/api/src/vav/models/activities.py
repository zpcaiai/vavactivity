from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
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


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[UUID] = uuid_pk()
    activity_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    activity_format: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'public'")
    )
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    post_event_choice_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_event_choice_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_timing_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    waitlist_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    post_event_choice_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    minimum_age: Mapped[int | None] = mapped_column(Integer)
    maximum_age: Mapped[int | None] = mapped_column(Integer)
    cancellation_policy_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityLocalization(Base):
    __tablename__ = "activity_localizations"
    __table_args__ = (
        UniqueConstraint("activity_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))
    description_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    venue_display_name: Mapped[str | None] = mapped_column(String(300))
    address_display_text: Mapped[str | None] = mapped_column(String(500))
    participation_notes: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cancellation_notice: Mapped[str | None] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(300))
    seo_description: Mapped[str | None] = mapped_column(String(500))
    cover_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityLocation(Base):
    __tablename__ = "activity_locations"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    location_type: Mapped[str] = mapped_column(String(32), nullable=False)
    venue_name: Mapped[str | None] = mapped_column(String(300))
    country_code: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))
    address_line_1_encrypted: Mapped[str | None] = mapped_column(Text)
    address_line_2_encrypted: Mapped[str | None] = mapped_column(Text)
    postal_code_encrypted: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    online_provider: Mapped[str | None] = mapped_column(String(64))
    online_join_url_encrypted: Mapped[str | None] = mapped_column(Text)
    online_meeting_reference: Mapped[str | None] = mapped_column(String(255))
    public_address_precision: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'city_only'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivitySession(Base):
    __tablename__ = "activity_sessions"
    __table_args__ = (UniqueConstraint("activity_id", "session_code"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    session_code: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_locations.id")
    )
    checkin_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkin_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityTicketType(Base):
    __tablename__ = "activity_ticket_types"
    __table_args__ = (
        UniqueConstraint("activity_id", "ticket_code"),
        UniqueConstraint("activity_id", "catalog_sku_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_code: Mapped[str] = mapped_column(String(128), nullable=False)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    catalog_product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    catalog_sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_policy_override: Mapped[str | None] = mapped_column(String(32))
    payment_timing_override: Mapped[str | None] = mapped_column(String(32))
    waitlist_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    max_quantity_per_user: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    eligibility_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    capacity_display_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'status_only'")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityTicketTypeLocalization(Base):
    __tablename__ = "activity_ticket_type_localizations"
    __table_args__ = (PrimaryKeyConstraint("ticket_type_id", "locale"),)

    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    eligibility_notice: Mapped[str | None] = mapped_column(Text)


class ActivityRegistrationForm(Base):
    __tablename__ = "activity_registration_forms"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False, unique=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    form_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    consent_requirements: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityRegistration(Base):
    __tablename__ = "activity_registrations"
    __table_args__ = (UniqueConstraint("activity_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    registration_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attendance_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'not_checked_in'")
    )
    form_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    form_response_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    pricing_quote_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id")
    )
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"))
    entitlement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id")
    )
    review_status: Mapped[str | None] = mapped_column(String(32))
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason_code: Mapped[str | None] = mapped_column(String(128))
    user_visible_review_message: Mapped[str | None] = mapped_column(String(500))
    review_notes_encrypted: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityRegistrationHistory(Base):
    __tablename__ = "activity_registration_history"

    id: Mapped[UUID] = uuid_pk()
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at()


class ActivityInboxEvent(Base):
    __tablename__ = "activity_inbox_events"

    id: Mapped[UUID] = uuid_pk()
    source_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityWaitlistEntry(Base):
    __tablename__ = "activity_waitlist_entries"
    __table_args__ = (UniqueConstraint("activity_id", "ticket_type_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_ticket_types.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    promotion_offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promotion_offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_order_override: Mapped[int | None] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(Text)
    overridden_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityCheckinCredential(Base):
    __tablename__ = "activity_checkin_credentials"

    id: Mapped[UUID] = uuid_pk()
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_registrations.id"),
        nullable=False,
        unique=True,
    )
    public_reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    credential_secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityCheckinEvent(Base):
    __tablename__ = "activity_checkin_events"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_sessions.id")
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    performed_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    device_reference: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    occurred_at: Mapped[datetime] = created_at()


class ActivityGroupingPlan(Base):
    __tablename__ = "activity_grouping_plans"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    grouping_method: Mapped[str] = mapped_column(String(32), nullable=False)
    target_group_size: Mapped[int | None] = mapped_column(Integer)
    target_group_count: Mapped[int | None] = mapped_column(Integer)
    rule_schema_version: Mapped[int | None] = mapped_column(Integer)
    grouping_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    random_seed: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    locked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityGroup(Base):
    __tablename__ = "activity_groups"
    __table_args__ = (UniqueConstraint("grouping_plan_id", "group_code"),)

    id: Mapped[UUID] = uuid_pk()
    grouping_plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_grouping_plans.id"), nullable=False
    )
    group_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    facilitator_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    capacity: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()


class ActivityGroupMember(Base):
    __tablename__ = "activity_group_members"

    id: Mapped[UUID] = uuid_pk()
    grouping_plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_grouping_plans.id"), nullable=False
    )
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_groups.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    assignment_source: Mapped[str] = mapped_column(String(32), nullable=False)
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    assigned_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    removal_reason: Mapped[str | None] = mapped_column(Text)


class ActivityParticipantProfile(Base):
    __tablename__ = "activity_participant_profiles"
    __table_args__ = (UniqueConstraint("activity_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    dating_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    avatar_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    brief_introduction: Mapped[str | None] = mapped_column(String(500))
    visibility_status: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_snapshot_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityPostEventChoice(Base):
    __tablename__ = "activity_post_event_choices"
    __table_args__ = (UniqueConstraint("activity_id", "chooser_user_id", "chosen_user_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    chooser_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    chosen_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    choice: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ActivityInteractionRestriction(Base):
    __tablename__ = "activity_interaction_restrictions"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id"),)

    id: Mapped[UUID] = uuid_pk()
    user_a_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user_b_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ActivityMutualChoice(Base):
    __tablename__ = "activity_mutual_choices"
    __table_args__ = (UniqueConstraint("activity_id", "user_a_id", "user_b_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    user_a_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user_b_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    first_choice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_post_event_choices.id"), nullable=False
    )
    second_choice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_post_event_choices.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    platform_match_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    introduction_invitation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at()
