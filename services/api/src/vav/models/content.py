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
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.base import Base


class ContentEntry(Base):
    __tablename__ = "content_entries"
    __table_args__ = (UniqueConstraint("entry_type", "canonical_slug"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    internal_name: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'public'")
    )
    author_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContentLocalization(Base):
    __tablename__ = "content_localizations"
    __table_args__ = (
        UniqueConstraint("entry_id", "locale"),
        UniqueConstraint("locale", "localized_slug"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_entries.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    localized_slug: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    content_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    plain_text: Mapped[str | None] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(300))
    seo_description: Mapped[str | None] = mapped_column(String(500))
    social_title: Mapped[str | None] = mapped_column(String(300))
    social_description: Mapped[str | None] = mapped_column(String(500))
    cover_media_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContentVersion(Base):
    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("entry_id", "version_number"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_entries.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArticleMetadata(Base):
    __tablename__ = "article_metadata"

    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_entries.id"), primary_key=True
    )
    category: Mapped[str | None] = mapped_column(String(128))
    author_display_name: Mapped[str | None] = mapped_column(String(160))
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_reference: Mapped[str | None] = mapped_column(Text)
    original_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestimonialMetadata(Base):
    __tablename__ = "testimonial_metadata"

    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_entries.id"), primary_key=True
    )
    subject_display_name: Mapped[str | None] = mapped_column(String(160))
    relationship_stage: Mapped[str | None] = mapped_column(String(64))
    consent_status: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    anonymity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_name: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'private'")
    )
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAssetLocalization(Base):
    __tablename__ = "media_asset_localizations"
    __table_args__ = (PrimaryKeyConstraint("media_id", "locale"),)

    media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500))
    caption: Mapped[str | None] = mapped_column(Text)
    accessibility_description: Mapped[str | None] = mapped_column(Text)


class NavigationMenu(Base):
    __tablename__ = "navigation_menus"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class NavigationItem(Base):
    __tablename__ = "navigation_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    menu_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("navigation_menus.id"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("navigation_items.id")
    )
    internal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    link_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    external_url: Mapped[str | None] = mapped_column(Text)
    route_name: Mapped[str | None] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    open_in_new_tab: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    required_auth: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class NavigationItemLocalization(Base):
    __tablename__ = "navigation_item_localizations"
    __table_args__ = (PrimaryKeyConstraint("navigation_item_id", "locale"),)

    navigation_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("navigation_items.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    setting_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[dict[str, object] | list[object] | str | bool | None] = mapped_column(
        JSONB, nullable=False
    )
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContentPreviewToken(Base):
    __tablename__ = "content_preview_tokens"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_entries.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    locale: Mapped[str | None] = mapped_column(String(16))
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    submission_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    region: Mapped[str | None] = mapped_column(String(128))
    subject: Mapped[str | None] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'new'"))
    assigned_to: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    privacy_consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    privacy_consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_page: Mapped[str | None] = mapped_column(String(300))
    ip_address_hash: Mapped[str | None] = mapped_column(String(128))
    user_agent_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
