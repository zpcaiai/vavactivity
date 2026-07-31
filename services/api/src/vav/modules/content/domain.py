from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

UNSAFE_MARKUP = re.compile(
    r"<\s*(script|iframe|style|form|object|embed)\b|on[a-z]+\s*=",
    flags=re.IGNORECASE,
)


class ContentEntryType(StrEnum):
    PAGE = "page"
    ARTICLE = "article"
    TESTIMONIAL = "testimonial"
    FAQ = "faq"
    ANNOUNCEMENT = "announcement"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TranslationStatus(StrEnum):
    MISSING = "missing"
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    READY = "ready"
    OUTDATED = "outdated"


class Action(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    href: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def safe_href(self) -> Action:
        parsed = urlparse(self.href)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ValueError("unsafe link scheme")
        if not parsed.scheme and not self.href.startswith("/"):
            raise ValueError("relative links must start with /")
        return self


class HeroData(BaseModel):
    heading: str = Field(min_length=1, max_length=300)
    subheading: str | None = Field(default=None, max_length=500)
    background_media_id: UUID | None = None
    primary_action: Action | None = None
    secondary_action: Action | None = None


class RichTextData(BaseModel):
    document: dict[str, Any]

    @model_validator(mode="after")
    def reject_unsafe_markup(self) -> RichTextData:
        serialized = str(self.document)
        if UNSAFE_MARKUP.search(serialized) or "javascript:" in serialized.casefold():
            raise ValueError("unsafe rich-text content")
        return self


class ImageData(BaseModel):
    media_id: UUID
    decorative: bool = False


class QuoteData(BaseModel):
    quote: str = Field(min_length=1, max_length=2000)
    attribution: str | None = Field(default=None, max_length=300)


class CallToActionData(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    button: Action


class CollectionData(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    limit: int = Field(default=3, ge=1, le=20)


class HeroBlock(BaseModel):
    id: str
    type: Literal["hero"]
    version: int = 1
    data: HeroData


class RichTextBlock(BaseModel):
    id: str
    type: Literal["rich_text"]
    version: int = 1
    data: RichTextData


class ImageBlock(BaseModel):
    id: str
    type: Literal["image"]
    version: int = 1
    data: ImageData


class QuoteBlock(BaseModel):
    id: str
    type: Literal["quote"]
    version: int = 1
    data: QuoteData


class CallToActionBlock(BaseModel):
    id: str
    type: Literal["call_to_action"]
    version: int = 1
    data: CallToActionData


class CollectionBlock(BaseModel):
    id: str
    type: Literal[
        "feature_grid",
        "article_list",
        "story_list",
        "activity_list",
        "course_list",
        "counseling_list",
        "faq",
        "divider",
    ]
    version: int = 1
    data: CollectionData


ContentBlock = Annotated[
    HeroBlock | RichTextBlock | ImageBlock | QuoteBlock | CallToActionBlock | CollectionBlock,
    Field(discriminator="type"),
]
