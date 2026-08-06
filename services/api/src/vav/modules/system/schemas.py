from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class FeatureFlagCreateRequest(BaseModel):
    flag_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    default_value: dict[str, Any]
    targeting_policy: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("flag_code")
    @classmethod
    def prevent_control_bypass_flags(cls, value: str) -> str:
        protected = ("safety.", "privacy.", "payment.", "authorization.", "encryption.")
        if value.startswith(protected):
            raise ValueError("feature flags cannot control mandatory safety or privacy controls")
        return value


class FeatureFlagUpdateRequest(BaseModel):
    default_value: dict[str, Any]
    targeting_policy: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)


class ReleaseRecordCreateRequest(BaseModel):
    release_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    image_digests: dict[str, str]
    database_revision: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    contract_checksums: dict[str, str]
    configuration_fingerprint: dict[str, Any]
    evidence_manifest: dict[str, Any] = Field(default_factory=dict)

    @field_validator("image_digests")
    @classmethod
    def require_immutable_digests(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"api", "worker", "user_web", "admin_web"}
        if set(value) != required or any("@sha256:" not in digest for digest in value.values()):
            raise ValueError("every production image must use an immutable sha256 digest")
        return value


class MaintenanceChangeRequest(BaseModel):
    reason_code: str = Field(min_length=3, max_length=128)
    public_message: str | None = Field(default=None, max_length=1000)
    write_scope: dict[str, bool] = Field(default_factory=dict)
    approval_actor_id: str | None = None


class BackfillTransitionRequest(BaseModel):
    target_status: Literal["running", "paused", "cancelled"]
    expected_cursor: dict[str, Any] | None = None


class OperationalReasonRequest(BaseModel):
    reason_code: str = Field(min_length=3, max_length=128)


class DeploymentEvidenceRequest(BaseModel):
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)


class BackupRecordRequest(BaseModel):
    backup_type: Literal[
        "postgres_full", "postgres_wal", "object_storage", "configuration", "complete"
    ]
    environment: Literal["development", "test", "ci", "staging", "production", "dr"]
    status: Literal["started", "completed", "failed", "verified", "expired"]
    started_at: datetime
    completed_at: datetime | None = None
    backup_reference_encrypted: str | None = Field(default=None, max_length=8192)
    checksum_manifest: dict[str, Any] = Field(default_factory=dict)
    source_release_version: str | None = Field(default=None, max_length=64)
    source_database_revision: str | None = Field(default=None, max_length=64)
    verified_at: datetime | None = None
    expires_at: datetime | None = None


class RestoreDrillRecordRequest(BaseModel):
    drill_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    environment: Literal["development", "test", "ci", "staging", "production", "dr"]
    backup_record_id: UUID | None = None
    status: Literal["started", "passed", "failed", "cancelled"]
    target_release_version: str | None = Field(default=None, max_length=64)
    target_database_revision: str | None = Field(default=None, max_length=64)
    verification_manifest: dict[str, Any] = Field(default_factory=dict)
    failure_summary: str | None = Field(default=None, max_length=4000)
    started_at: datetime
    completed_at: datetime | None = None


class CapacityBaselineRecordRequest(BaseModel):
    release_version: str = Field(min_length=3, max_length=64)
    environment: Literal["development", "test", "ci", "staging", "production", "dr"]
    scenario_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    infrastructure_snapshot: dict[str, Any]
    load_snapshot: dict[str, Any]
    result_metrics: dict[str, Any]
    status: Literal["passed", "failed", "not_certified"]
    tested_at: datetime
