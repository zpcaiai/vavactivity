from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SpaceRequest(BaseModel):
    space_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    name: str = Field(min_length=2, max_length=200)
    purpose: str = Field(min_length=10, max_length=1000)
    default_locale: str = "zh-CN"
    allowed_roles: list[str] = Field(default_factory=list)


class SourceRequest(BaseModel):
    source_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    source_type: Literal["upload", "cms", "course", "activity", "counseling", "faq"]
    title: str = Field(min_length=2, max_length=300)
    sensitivity: Literal["public", "internal", "restricted"] = "internal"


class AuthorizationRequest(BaseModel):
    allow_rag: bool
    allow_public_quote: bool = False
    allow_external_training: bool = False
    allowed_regions: list[str] = Field(default_factory=list)
    evidence: dict[str, object]
    valid_from: datetime
    valid_until: datetime | None = None
    rights_holder_name: str = Field(default="VAV", min_length=2, max_length=300)
    authorization_basis: Literal[
        "owned_by_vav",
        "written_license",
        "public_domain",
        "contractual_permission",
        "user_supplied_authorized",
    ] = "owned_by_vav"
    allowed_uses: list[str] = Field(default_factory=lambda: ["rag_retrieval"])
    prohibited_uses: list[str] = Field(default_factory=lambda: ["external_model_training"])
    prohibited_regions: list[str] = Field(default_factory=list)
    citation_permission: Literal[
        "none", "internal_reference_only", "short_public_excerpt", "public_title_only"
    ] = "none"


class DocumentRequest(BaseModel):
    document_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    title: str = Field(min_length=2, max_length=500)
    locale: str = "zh-CN"
    mime_type: Literal["text/plain", "text/markdown", "application/json"] = "text/markdown"
    text: str = Field(min_length=1, max_length=1_000_000)
    allowed_roles: list[str] = Field(default_factory=list)
    source_locator: dict[str, object] = Field(default_factory=dict)


class RetrievalRequest(BaseModel):
    space_code: str
    query: str = Field(min_length=1, max_length=2000)
    locale: str = "zh-CN"
    region: str | None = None
    roles: list[str] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)
    public: bool = False
    index_version_id: UUID | None = None


class PublishRequest(BaseModel):
    allowed_roles: list[str] = Field(default_factory=list)
    reason: str = Field(default="approved for knowledge retrieval", min_length=2, max_length=1000)


class IndexActionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=2, max_length=1000)


class AuthorizationDecisionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class FindingReviewRequest(BaseModel):
    decision: Literal["resolved", "accepted_risk", "rejected"]
    resolution: str = Field(min_length=2, max_length=2000)


class UploadCreateRequest(BaseModel):
    source_id: UUID
    document_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    title: str = Field(min_length=2, max_length=500)
    locale: str = "zh-CN"
    filename: str = Field(min_length=1, max_length=500)
    mime_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/markdown",
        "text/plain",
        "text/html",
    ]
    byte_size: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class UploadCompleteRequest(BaseModel):
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
