from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TokenReleaseCreate(BaseModel):
    token_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    manifest_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_summary: str = Field(min_length=10, max_length=5000)
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class ReleaseEvidence(BaseModel):
    evidence_manifest: dict[str, Any]


class ComponentUpsert(BaseModel):
    component_code: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,127}$")
    package_name: str = Field(pattern=r"^@vav/ui-(?:core|user|admin)$")
    source_location: str = Field(min_length=3, max_length=1000)
    owner_team: str = Field(min_length=2, max_length=128)
    accessibility_contract: dict[str, Any]
    supported_states: list[str] = Field(min_length=1)
    status: Literal["active", "experimental"] = "active"


class ComponentDeprecate(BaseModel):
    reason: str = Field(min_length=10, max_length=5000)
    replacement_component_code: str | None = Field(default=None, max_length=128)


class PatternUpsert(BaseModel):
    pattern_code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    name: str = Field(min_length=3, max_length=300)
    audience: Literal["user", "admin", "shared"]
    source_location: str = Field(min_length=3, max_length=1000)
    required_components: list[str] = Field(min_length=1)
    required_states: list[str] = Field(min_length=1)
    accessibility_notes: str = Field(min_length=10, max_length=5000)
    status: Literal["active", "experimental"] = "active"


class AuditRunCreate(BaseModel):
    audit_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{2,127}$")
    audit_type: Literal["accessibility", "responsive", "visual", "page", "storybook"]
    application_code: Literal["user-web", "admin-web", "design-system"]
    route_path: str | None = Field(default=None, max_length=500)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["test", "ci", "staging", "production"]
    viewport: str | None = Field(default=None, max_length=64)
    theme: Literal["light", "dark", "high-contrast"] | None = None
    locale: Literal["zh-CN", "zh-TW", "en"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    status: Literal["not_run", "technical_pass", "needs_review", "failed"]
    findings: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_reference: str | None = Field(default=None, max_length=2000)
    evidence_checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manual_review_required: bool = False


class AuditReview(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=10, max_length=5000)


class BaselineCreate(BaseModel):
    baseline_code: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,254}$")
    application_code: Literal["user-web", "admin-web", "design-system"]
    route_path: str = Field(min_length=1, max_length=500)
    viewport: str = Field(min_length=3, max_length=64)
    theme: Literal["light", "dark", "high-contrast"]
    locale: Literal["zh-CN", "zh-TW", "en"]
    density: Literal["comfortable", "compact"]
    artifact_reference: str = Field(min_length=3, max_length=2000)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BaselineDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=10, max_length=5000)
