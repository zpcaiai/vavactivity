from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator

from vav.modules.content.domain import ContentBlock, TranslationStatus

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


class LocalizationInput(BaseModel):
    locale: str
    localized_slug: Slug | None = None
    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=500)
    excerpt: str | None = None
    content_blocks: list[ContentBlock] = []
    plain_text: str | None = None
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)
    social_title: str | None = Field(default=None, max_length=300)
    social_description: str | None = Field(default=None, max_length=500)
    cover_media_id: UUID | None = None
    translation_status: TranslationStatus = TranslationStatus.DRAFT


class ContentCreateRequest(BaseModel):
    internal_name: str = Field(min_length=1, max_length=160)
    canonical_slug: Slug
    default_locale: str = "zh-CN"
    localization: LocalizationInput
    change_summary: str = Field(min_length=3, max_length=1000)


class ContentUpdateRequest(BaseModel):
    internal_name: str | None = Field(default=None, min_length=1, max_length=160)
    visibility: str | None = None
    expected_version: int = Field(ge=1)
    change_summary: str = Field(min_length=3, max_length=1000)


class LocalizationUpdateRequest(LocalizationInput):
    expected_version: int = Field(ge=1)
    change_summary: str = Field(min_length=3, max_length=1000)


class ReviewRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class ScheduleRequest(ReviewRequest):
    scheduled_publish_at: datetime


class VersionRestoreRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
    expected_version: int = Field(ge=1)


class PreviewTokenRequest(BaseModel):
    locale: str | None = None


class ArticleMetadataInput(BaseModel):
    category: str | None = None
    author_display_name: str | None = None
    reading_time_minutes: int | None = Field(default=None, ge=1, le=1440)
    featured: bool = False
    source_reference: str | None = None


class ArticleCreateRequest(ContentCreateRequest):
    metadata: ArticleMetadataInput = ArticleMetadataInput()


class TestimonialMetadataInput(BaseModel):
    subject_display_name: str | None = None
    relationship_stage: str | None = None
    consent_status: str = "pending"
    consent_record_id: UUID | None = None
    anonymity_level: str = "fully_anonymous"
    featured: bool = False


class TestimonialCreateRequest(ContentCreateRequest):
    metadata: TestimonialMetadataInput = TestimonialMetadataInput()


class MediaUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    mime_type: str
    byte_size: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    visibility: str = "private"


class MediaCompleteRequest(BaseModel):
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class MediaUpdateRequest(BaseModel):
    visibility: str | None = None
    locale: str
    alt_text: str | None = Field(default=None, max_length=500)
    caption: str | None = None
    accessibility_description: str | None = None


class ContactSubmissionRequest(BaseModel):
    submission_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    region: str | None = Field(default=None, max_length=128)
    subject: str | None = Field(default=None, max_length=300)
    message: str = Field(min_length=10, max_length=5000)
    locale: str
    privacy_consent_version: str = Field(min_length=1, max_length=32)
    source_page: str | None = Field(default=None, max_length=300)
    website: str = ""
    form_started_at: datetime | None = None


class ContactStatusRequest(BaseModel):
    status: str
    reason: str = Field(min_length=10, max_length=2000)


class ContactAssignRequest(BaseModel):
    assigned_to: UUID
    reason: str = Field(min_length=10, max_length=2000)


class ContactResolveRequest(BaseModel):
    resolution: str = Field(min_length=10, max_length=2000)


class NavigationLocalizationInput(BaseModel):
    locale: Literal["zh-CN", "zh-TW", "en"]
    label: str = Field(min_length=1, max_length=160)


class NavigationItemInput(BaseModel):
    internal_name: str = Field(min_length=1, max_length=128)
    link_type: Literal["route", "external", "content"]
    target_entry_id: UUID | None = None
    external_url: str | None = Field(default=None, max_length=2000)
    route_name: str | None = Field(default=None, max_length=128)
    sort_order: int = 0
    open_in_new_tab: bool = False
    required_auth: bool = False
    is_active: bool = True
    localizations: list[NavigationLocalizationInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> NavigationItemInput:
        if len({item.locale for item in self.localizations}) != len(self.localizations):
            raise ValueError("navigation localization locales must be unique")
        if self.link_type == "route" and not self.route_name:
            raise ValueError("route links require route_name")
        if self.link_type == "content" and not self.target_entry_id:
            raise ValueError("content links require target_entry_id")
        if self.link_type == "external":
            parsed = urlparse(self.external_url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("external links require an absolute http or https URL")
        return self


class NavigationMenuUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_active: bool = True
    items: list[NavigationItemInput]
    reason: str = Field(min_length=10, max_length=2000)


class SiteSettingRequest(BaseModel):
    value: dict[str, object] | list[object] | str | bool | None
    value_type: Literal[
        "string",
        "nullable_string",
        "boolean",
        "array",
        "object",
        "decision_status",
    ]
    is_public: bool = False
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_typed_value(self) -> SiteSettingRequest:
        valid = {
            "string": isinstance(self.value, str),
            "nullable_string": self.value is None or isinstance(self.value, str),
            "boolean": isinstance(self.value, bool),
            "array": isinstance(self.value, list),
            "object": isinstance(self.value, dict),
            "decision_status": isinstance(self.value, str),
        }[self.value_type]
        if not valid:
            raise ValueError("setting value does not match value_type")
        return self


class SiteSettingRollbackRequest(BaseModel):
    audit_event_id: UUID
    expected_updated_at: datetime
    reason: str = Field(min_length=10, max_length=2000)
