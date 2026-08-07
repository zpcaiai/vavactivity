"""Canonical, immutable Skill manifest models."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Metadata(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$", max_length=255)
    display_name: str = Field(alias="displayName", min_length=1, max_length=300)
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
    publisher: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,126}[a-z0-9]$")
    description: str = Field(min_length=1, max_length=2000)
    license: str = Field(min_length=1, max_length=100)
    categories: tuple[str, ...] = ()


class SchemaReference(StrictModel):
    schema_path: str = Field(alias="schema", pattern=r"^schemas/[a-z0-9._-]+\.json$")


class CapabilityDeclaration(StrictModel):
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


class Dependencies(StrictModel):
    skills: tuple[dict[str, str], ...] = ()
    modules: tuple[dict[str, str], ...] = ()
    providers: tuple[dict[str, str], ...] = ()


class Execution(StrictModel):
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=900)
    retry_policy: Literal["none", "read_safe", "idempotent"] = Field(alias="retryPolicy")
    idempotency: Literal["not_required", "required", "caller_provided"]
    concurrency_limit: int = Field(alias="concurrencyLimit", ge=1, le=1000)


class DataAccess(StrictModel):
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()


class Security(StrictModel):
    network_access: Literal["none", "allowlist"] = Field(alias="networkAccess")
    filesystem_access: Literal["none", "temporary_read_only", "temporary_read_write"] = Field(
        alias="filesystemAccess"
    )
    secret_access: tuple[str, ...] = Field(default=(), alias="secretAccess")
    risk_level: Literal["low", "medium", "high", "critical"] = Field(alias="riskLevel")
    user_confirmation_required: bool = Field(alias="userConfirmationRequired")


class Compatibility(StrictModel):
    minimum_platform_version: str = Field(alias="minimumPlatformVersion")
    maximum_platform_version: str = Field(alias="maximumPlatformVersion")


class Observability(StrictModel):
    tracing: bool
    metrics: bool
    audit_level: Literal["none", "metadata", "detailed"] = Field(alias="auditLevel")


class Tests(StrictModel):
    command: str = Field(pattern=r"^(pytest|pnpm test|npm test)(?: [A-Za-z0-9_./:= -]+)?$")


class SkillSpec(StrictModel):
    type: Literal[
        "query",
        "command",
        "workflow",
        "agent-tool",
        "event-handler",
        "scheduled-job",
        "provider-adapter",
        "domain-pack",
        "ui-extension",
    ]
    runtime: Literal["python", "typescript", "worker", "http", "sandbox", "none"]
    entrypoint: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    runtime_api_version: str = Field(alias="runtimeApiVersion", pattern=r"^\d+\.\d+$")
    manifest_version: str = Field(alias="manifestVersion", pattern=r"^\d+\.\d+$")
    inputs: SchemaReference
    outputs: SchemaReference
    errors: SchemaReference
    permissions: tuple[str, ...] = ()
    capabilities: CapabilityDeclaration
    dependencies: Dependencies
    execution: Execution
    data: DataAccess
    security: Security
    compatibility: Compatibility
    observability: Observability
    tests: Tests

    @model_validator(mode="after")
    def side_effects_require_idempotency(self) -> "SkillSpec":
        side_effecting = self.type in {"command", "workflow", "event-handler", "scheduled-job"}
        if side_effecting and self.execution.idempotency == "not_required":
            raise ValueError("side-effecting Skills must declare idempotency")
        return self


class SkillManifest(StrictModel):
    api_version: Literal["skills.vav.io/v1"] = Field(alias="apiVersion")
    kind: Literal["Skill"]
    metadata: Metadata
    spec: SkillSpec

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
