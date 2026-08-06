from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SavedViewCreate(BaseModel):
    query_code: str
    name: str = Field(min_length=1, max_length=300)
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: str
    columns: list[str]
    visibility: Literal["private", "team", "organization_template"] = "private"
    shared_team: str | None = None


class BulkPlan(BaseModel):
    operation_code: str
    target_ids: list[UUID] = Field(min_length=1, max_length=10000)
    expected_versions: dict[str, int] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    idempotency_key: str = Field(min_length=8, max_length=128)


class ApprovalCreate(BaseModel):
    policy_code: str
    capability_code: str
    target_entity_type: str | None = None
    target_entity_id: UUID | None = None
    payload: dict[str, Any]
    business_state_snapshot: dict[str, Any]


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    reason_code: str = Field(min_length=3, max_length=128)
    rationale: str = Field(min_length=10, max_length=1000)


class ConfigurationCreate(BaseModel):
    namespace_code: str
    environment: Literal["local", "ci", "staging", "production"]
    semantic_version: str
    configuration: dict[str, Any]


class ConfigurationAction(BaseModel):
    action: Literal["approve", "activate", "rollback", "reject"]


class RevealCreate(BaseModel):
    policy_code: str
    entity_type: str
    entity_id: UUID
    purpose_code: str
    reason: str = Field(min_length=10, max_length=1000)
    step_up_authenticated_at: datetime | None = None


class MaskRequest(BaseModel):
    policy_code: str
    value: Any
    purpose_code: str
    permission_codes: list[str]
    reveal_grant_id: UUID | None = None


class CertificationEvaluate(BaseModel):
    business_domain: str
    release_version: str
    environment: Literal["local", "ci", "staging", "production"]
    verified_capability_codes: list[str]
    evidence_ids: list[UUID] = Field(default_factory=list)


class CertificationDecision(BaseModel):
    decision: Literal["certified", "rejected"]
