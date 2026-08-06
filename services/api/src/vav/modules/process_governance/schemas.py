from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessStart(BaseModel):
    process_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    business_key: str = Field(min_length=1, max_length=255)
    source_entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_entity_id: UUID | None = None
    context: dict[str, str] = Field(default_factory=dict)


class StepBegin(BaseModel):
    step_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,127}$")
    idempotency_key: str = Field(min_length=8, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)


class StepComplete(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=255)
    receipt: dict[str, Any]


class EventReceive(BaseModel):
    consumer_code: str = Field(min_length=3, max_length=128)
    event_id: UUID
    event_code: str = Field(min_length=3, max_length=160)
    aggregate_type: str = Field(min_length=1, max_length=128)
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CancellationCreate(BaseModel):
    cancellation_key: str = Field(min_length=8, max_length=255)
    request_type: Literal["user", "system", "admin_technical", "safety", "provider"]
    reason_code: str = Field(min_length=2, max_length=128)
    expected_lock_version: int = Field(ge=0)


class CompensationRequest(BaseModel):
    step_execution_id: UUID
    compensation_code: str = Field(min_length=3, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=255)


class InterventionResolve(BaseModel):
    resolution_command: str = Field(min_length=3, max_length=160)
    receipt: dict[str, Any]


class SimulationRequest(BaseModel):
    scenario_code: str = Field(min_length=3, max_length=128)
    synthetic_seed: int = 1


class CertificationEvaluate(BaseModel):
    business_domain: str = Field(min_length=2, max_length=64)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["local", "ci", "staging", "production"]
    path_results: dict[str, Literal["pass", "fail", "not_run"]]
    evidence_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CertificationDecision(BaseModel):
    decision: Literal["certified", "rejected"]
    reason: str = Field(min_length=10, max_length=1000)
