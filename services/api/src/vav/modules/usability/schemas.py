from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DraftSave(BaseModel):
    draft_code: str
    entity_id: UUID | None = None
    schema_version: str
    client_version: int = Field(ge=1)
    payload: dict[str, Any]


class ImportPreview(BaseModel):
    import_code: str
    source_file_ref: str
    rows: list[dict[str, Any]] = Field(max_length=100000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = True


class UatRunCreate(BaseModel):
    scenario_code: str
    environment: Literal["local", "ci", "demo", "staging", "production"]
    release_version: str
    locale: str
    device_profile: str


class UatRunComplete(BaseModel):
    status: Literal["passed", "failed", "blocked"]
    step_results: list[dict[str, Any]]
    evidence_refs: list[str] = Field(default_factory=list)


class CertificationEvaluate(BaseModel):
    business_domain: str
    release_version: str
    environment: Literal["local", "ci", "demo", "staging", "production"]
    results: dict[str, Literal["passed", "failed", "blocked", "not_run"]]
    unresolved_critical_findings: int = Field(ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
