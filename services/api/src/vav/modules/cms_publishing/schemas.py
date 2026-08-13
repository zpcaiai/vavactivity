"""Request payloads for the bilingual CMS module (B19 part 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


class SeoMetadataRequest(_Base):
    seo_title: Annotated[str, Field(min_length=1, max_length=70)]
    seo_description: Annotated[str, Field(max_length=160)] = ""
    #: Site-relative only. An absolute canonical would hand ranking to whatever
    #: host the value names.
    canonical_path: Annotated[str, Field(min_length=1, max_length=500, pattern=r"^/[^/].*$")]
    robots: Annotated[list[str], Field(max_length=6)] = Field(
        default_factory=lambda: ["index", "follow"]
    )
    og_image_media_id: Annotated[str, Field(max_length=64)] | None = None


class LocalizedBodyRequest(_Base):
    locale: Annotated[str, Field(min_length=2, max_length=16)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    summary: Annotated[str, Field(max_length=1000)] = ""
    #: Rich text. Sanitized on write; what is stored is what was kept.
    body_html: Annotated[str, Field(max_length=200_000)]
    status: Literal["draft", "ready", "published"] = "draft"
    seo: SeoMetadataRequest | None = None


class ContentEntryCreateRequest(_Base):
    entry_code: Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]
    content_type: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
    default_locale: Annotated[str, Field(min_length=2, max_length=16)] = "zh-CN"
    bodies: Annotated[list[LocalizedBodyRequest], Field(min_length=1, max_length=8)]

    @field_validator("bodies")
    @classmethod
    def _reject_duplicate_locales(
        cls, value: list[LocalizedBodyRequest]
    ) -> list[LocalizedBodyRequest]:
        locales = [body.locale for body in value]
        if len(set(locales)) != len(locales):
            raise ValueError("each locale may appear at most once")
        return value


class ContentEntryUpdateRequest(_Base):
    bodies: Annotated[list[LocalizedBodyRequest], Field(min_length=1, max_length=8)]
    change_note: Annotated[str, Field(max_length=1000)] | None = None

    @field_validator("bodies")
    @classmethod
    def _reject_duplicate_locales(
        cls, value: list[LocalizedBodyRequest]
    ) -> list[LocalizedBodyRequest]:
        locales = [body.locale for body in value]
        if len(set(locales)) != len(locales):
            raise ValueError("each locale may appear at most once")
        return value


class ContentTransitionRequest(_Base):
    target_status: Literal["draft", "in_review", "scheduled", "published", "archived"]
    #: Required when moving to ``scheduled``; must be in the future.
    scheduled_publish_at: datetime | None = None
    reason: Annotated[str, Field(max_length=1000)] | None = None


class ContentRollbackRequest(_Base):
    target_revision_number: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class PreviewGrantRequest(_Base):
    revision_number: Annotated[int, Field(ge=1)] | None = None
    ttl_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    audience: Literal["internal", "external_reviewer"] = "internal"


class SanitizePreviewRequest(_Base):
    """Dry-run the sanitizer so an editor sees what will be removed."""

    body_html: Annotated[str, Field(max_length=200_000)]


def dump_bodies(bodies: list[LocalizedBodyRequest]) -> list[dict[str, Any]]:
    return [body.model_dump() for body in bodies]
