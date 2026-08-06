from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstallPlanRequest(StrictRequest):
    skill_name: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$", max_length=255)
    semantic_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
    environment: Literal["development", "test", "ci", "staging", "production"]
    granted_permissions: list[str] = Field(default_factory=list, max_length=100)
    configuration: dict[str, Any] = Field(default_factory=dict)


class CreateInstallationRequest(StrictRequest):
    plan_id: UUID
    expected_plan_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration: dict[str, Any] = Field(default_factory=dict)


class InstallationReasonRequest(StrictRequest):
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")


class UpgradeInstallationRequest(StrictRequest):
    target_version_id: UUID
    expected_version: int = Field(ge=1)
    granted_permissions: list[str] = Field(default_factory=list, max_length=100)


class ExecuteSkillRequest(StrictRequest):
    version_constraint: str = Field(default="*", min_length=1, max_length=128)
    input: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    deadline: datetime
    invocation_source: Literal[
        "user_api",
        "admin_api",
        "agent",
        "event",
        "schedule",
        "workflow",
        "cli",
        "ide",
        "internal_service",
    ] = "internal_service"


class MarketplaceListingRequest(StrictRequest):
    skill_name: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$", max_length=255)
    version_id: UUID
    category_codes: list[str] = Field(min_length=1, max_length=10)
    summary_localizations: dict[str, str]
    documentation_reference: str | None = Field(default=None, max_length=1000)
    pricing_model: Literal["free", "private_contract"] = "free"
    support_policy: dict[str, Any]
    privacy_disclosure: dict[str, Any]

    @field_validator("summary_localizations")
    @classmethod
    def required_summaries(cls, value: dict[str, str]) -> dict[str, str]:
        if not {"zh-CN", "en"}.issubset(value) or any(len(item) < 10 for item in value.values()):
            raise ValueError("zh-CN and en summaries of at least 10 characters are required")
        return value

    @field_validator("privacy_disclosure")
    @classmethod
    def complete_disclosure(cls, value: dict[str, Any]) -> dict[str, Any]:
        required = {
            "reads",
            "writes",
            "externalDestinations",
            "retention",
            "deletion",
            "modelTraining",
            "automatedDecision",
        }
        if not required.issubset(value):
            raise ValueError("complete data-use disclosure is required")
        return value


class ReviewDecisionRequest(StrictRequest):
    decision: Literal["approved", "changes_required", "rejected"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    findings: list[str] = Field(default_factory=list, max_length=100)


class AppealRequest(StrictRequest):
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    statement: str = Field(min_length=20, max_length=5000)
