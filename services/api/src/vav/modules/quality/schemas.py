from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from vav.modules.quality.domain import (
    ALLOWED_GATE_OPERATORS,
    CapabilityType,
    ExceptionScenarioType,
    GateEnforcementLevel,
    QualityCriticality,
    QualityEvidenceType,
    QualityRequirementType,
    RequirementSourceType,
    TraceNodeType,
)


class RequirementCreate(BaseModel):
    requirement_code: str
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=3, max_length=10_000)
    source_type: RequirementSourceType
    source_reference: str | None = Field(default=None, max_length=1000)
    source_version: str | None = Field(default=None, max_length=64)
    requirement_type: QualityRequirementType
    business_domain: str = Field(min_length=2, max_length=64)
    criticality: QualityCriticality
    acceptance_criteria: list[dict[str, Any]] = Field(min_length=1)
    non_functional_criteria: dict[str, Any] = Field(default_factory=dict)
    owner_team: str = Field(min_length=2, max_length=128)
    parent_requirement_id: UUID | None = None
    introduced_in_batch: int | None = Field(default=None, ge=1, le=32)
    target_release: str | None = Field(default=None, max_length=64)


class RequirementTransition(BaseModel):
    target_status: Literal[
        "approved",
        "in_implementation",
        "implemented",
        "verified",
        "deferred",
        "rejected",
        "superseded",
    ]


class CapabilityCreate(BaseModel):
    capability_code: str
    name: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=10_000)
    capability_type: CapabilityType
    module_code: str = Field(min_length=2, max_length=64)
    criticality: QualityCriticality
    lifecycle_status: str = "available"
    owning_service: str | None = Field(default=None, max_length=128)
    primary_actor_type: str | None = Field(default=None, max_length=64)
    introduced_in_batch: int | None = Field(default=None, ge=1, le=32)
    current_version: str | None = Field(default=None, max_length=64)
    owner_team: str = Field(min_length=2, max_length=128)


class TraceNodeCreate(BaseModel):
    node_type: TraceNodeType
    node_code: str = Field(min_length=3, max_length=255)
    module_code: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=3, max_length=500)
    source_location: str | None = Field(default=None, max_length=1000)
    version: str = Field(default="1.0.0", max_length=64)
    status: str = Field(default="active", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceLinkCreate(BaseModel):
    source_node_id: UUID
    target_node_id: UUID
    relationship_type: str
    required: bool = True
    verification_method: str | None = Field(default=None, max_length=64)


class BusinessFlowCreate(BaseModel):
    flow_code: str
    name: str = Field(min_length=3, max_length=300)
    business_domain: str = Field(min_length=2, max_length=64)
    criticality: QualityCriticality
    primary_actor_type: str = Field(min_length=2, max_length=64)
    supporting_actor_types: list[str] = Field(default_factory=list)
    start_condition: dict[str, Any]
    success_end_conditions: list[dict[str, Any]] = Field(min_length=1)
    failure_end_conditions: list[dict[str, Any]] = Field(min_length=1)
    cancellation_conditions: list[dict[str, Any]] = Field(default_factory=list)
    closure_checks: dict[str, bool]
    manual_intervention_supported: bool
    compensation_required: bool
    owner_team: str = Field(min_length=2, max_length=128)


class ExceptionScenarioCreate(BaseModel):
    scenario_code: str = Field(min_length=3, max_length=128)
    business_flow_id: UUID
    exception_type: ExceptionScenarioType
    trigger_condition: dict[str, Any]
    expected_business_state: str = Field(min_length=2, max_length=128)
    expected_user_message_code: str | None = Field(default=None, max_length=128)
    expected_admin_action: str | None = Field(default=None, max_length=128)
    compensation_expected: bool
    retry_expected: bool
    criticality: QualityCriticality


class GapAssignment(BaseModel):
    owner_team: str = Field(min_length=2, max_length=128)
    owner_user_id: UUID | None = None


class GapResolution(BaseModel):
    resolution_summary: str = Field(min_length=10, max_length=5000)


class RiskCreate(BaseModel):
    risk_code: str = Field(min_length=3, max_length=128)
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=10, max_length=10_000)
    category: str = Field(min_length=2, max_length=64)
    severity: QualityCriticality
    likelihood: Literal["rare", "unlikely", "possible", "likely", "almost_certain"]
    affected_requirements: list[str] = Field(default_factory=list)
    affected_capabilities: list[str] = Field(default_factory=list)
    mitigation_plan: str | None = Field(default=None, max_length=10_000)
    contingency_plan: str | None = Field(default=None, max_length=10_000)
    owner_user_id: UUID | None = None
    owner_team: str = Field(min_length=2, max_length=128)
    target_resolution_date: str | None = None


class WaiverRequest(BaseModel):
    gate_definition_id: UUID | None = None
    quality_gap_id: UUID | None = None
    quality_risk_id: UUID | None = None
    justification: str = Field(min_length=20, max_length=10_000)
    mitigation_conditions: dict[str, Any]
    scope: dict[str, Any]
    valid_from: datetime
    expires_at: datetime

    @field_validator("mitigation_conditions", "scope")
    @classmethod
    def not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("must not be empty")
        return value


class DecisionReason(BaseModel):
    reason: str = Field(min_length=10, max_length=5000)


class EvidenceRegister(BaseModel):
    evidence_code: str = Field(min_length=3, max_length=128)
    evidence_type: QualityEvidenceType
    title: str = Field(min_length=3, max_length=500)
    source_system: str = Field(min_length=2, max_length=64)
    source_reference: str | None = Field(default=None, max_length=1000)
    release_version: str = Field(min_length=1, max_length=64)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["test", "ci", "staging", "production", "dr"]
    artifact_reference: str | None = Field(default=None, max_length=2000)
    artifact_checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    summary: dict[str, Any]
    generated_at: datetime
    expires_at: datetime | None = None


class GateDefinitionCreate(BaseModel):
    gate_code: str
    semantic_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    name: str = Field(min_length=3, max_length=300)
    category: str = Field(min_length=2, max_length=64)
    enforcement_level: GateEnforcementLevel
    condition_definition: dict[str, Any]
    required_evidence_types: list[QualityEvidenceType] = Field(min_length=1)
    applicable_release_types: list[str] = Field(min_length=1)
    applicable_modules: list[str] = Field(default_factory=list)

    @field_validator("condition_definition")
    @classmethod
    def restricted_dsl(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) != {"metric", "operator", "expected"}:
            raise ValueError("condition must contain only metric, operator and expected")
        if value.get("operator") not in ALLOWED_GATE_OPERATORS:
            raise ValueError("operator is not allowed")
        return value


class ReleaseEvaluationRequest(BaseModel):
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["test", "ci", "staging", "production", "dr"]
    release_type: str = Field(default="standard", min_length=2, max_length=64)


class ReleaseCertificationRequest(BaseModel):
    environment: Literal["test", "ci", "staging", "production", "dr"]
    evidence_manifest: dict[str, Any]
