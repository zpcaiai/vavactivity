"""Typed, secret-free deployment configuration and drift fingerprints."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigurationSensitivity(StrEnum):
    PUBLIC_BUILD = "public_build"
    INTERNAL = "internal"
    SECRET = "secret"
    HIGHLY_RESTRICTED = "highly_restricted"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationDeployment(StrictModel):
    debug: bool = False
    public_api_base_url: str
    user_web_url: str
    admin_web_url: str
    cookie_secure: bool
    cors_origins: list[str]


class ProviderDeployment(StrictModel):
    payment: Literal["fake", "test", "live"]
    email: Literal["mailpit", "fake", "transactional"]
    ai: Literal["deterministic_local", "sandbox", "approved"]


class DataDeployment(StrictModel):
    database_tls: bool
    redis_tls: bool
    object_storage_public: bool
    field_encryption: bool
    backup_encryption: bool


class ObservabilityDeployment(StrictModel):
    otel_endpoint: str | None = None
    trace_sample_ratio: float = Field(ge=0, le=1)
    structured_logs: bool = True


class SecretReferences(StrictModel):
    database: str
    redis: str
    jwt_private_key: str
    jwt_public_key: str
    field_encryption_master_key: str
    privacy_search_hmac_pepper: str
    backup_encryption_key: str
    payment_webhook_secret: str
    email_provider_secret: str
    ai_provider_api_key: str
    # Batch B13-B19 secrets. Each is required rather than optional: production
    # refuses to boot without them (see ``Settings`` in ``core.config``), so a
    # deployment file that omits one describes an environment that cannot
    # start. Declaring them optional here would let that file validate.
    checkin_last_four_hmac_key: str
    checkin_token_signing_key: str
    share_link_secret: str
    profile_media_token_secret: str
    discovery_ip_marker_salt: str


class FeatureFlagDeployment(StrictModel):
    version: str


class DeploymentConfiguration(StrictModel):
    schema_version: Literal["1.0.0"]
    environment: Literal["development", "test", "ci", "staging", "production", "dr"]
    application: ApplicationDeployment
    providers: ProviderDeployment
    data: DataDeployment
    observability: ObservabilityDeployment
    secrets: SecretReferences
    feature_flags: FeatureFlagDeployment

    @model_validator(mode="after")
    def reject_insecure_production_configuration(self) -> DeploymentConfiguration:
        if self.environment not in {"production", "dr"}:
            return self
        violations: list[str] = []
        if self.application.debug:
            violations.append("debug")
        if not self.application.cookie_secure:
            violations.append("insecure cookies")
        if any(
            origin == "*" or origin.startswith("http://")
            for origin in self.application.cors_origins
        ):
            violations.append("unsafe CORS")
        if self.providers.payment != "live":
            violations.append("non-live payment provider")
        if self.providers.email != "transactional":
            violations.append("development email provider")
        if self.providers.ai != "approved":
            violations.append("unapproved AI provider")
        if not self.data.database_tls or not self.data.redis_tls:
            violations.append("unencrypted data connection")
        if self.data.object_storage_public:
            violations.append("public object storage")
        if not self.data.field_encryption or not self.data.backup_encryption:
            violations.append("required encryption disabled")
        if violations:
            raise ValueError("production configuration rejected: " + ", ".join(violations))
        return self


def load_deployment_configuration(path: Path) -> DeploymentConfiguration:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    return DeploymentConfiguration.model_validate(value)


def configuration_fingerprint(config: DeploymentConfiguration) -> dict[str, str]:
    dumped = config.model_dump(mode="json")
    secret_references = dumped.pop("secrets")
    canonical = json.dumps(dumped, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    canonical_refs = json.dumps(
        secret_references, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return {
        "environment": config.environment,
        "config_schema_version": config.schema_version,
        "non_secret_configuration_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "secret_reference_hash": hashlib.sha256(canonical_refs.encode()).hexdigest(),
        "feature_flag_version": config.feature_flags.version,
    }


def diff_configuration(
    left: DeploymentConfiguration, right: DeploymentConfiguration
) -> dict[str, object]:
    left_dump = left.model_dump(mode="json", exclude={"secrets"})
    right_dump = right.model_dump(mode="json", exclude={"secrets"})
    changed = sorted(key for key in left_dump if left_dump[key] != right_dump.get(key))
    return {
        "from_environment": left.environment,
        "to_environment": right.environment,
        "changed_sections": changed,
        "secret_references_changed": left.secrets != right.secrets,
        "from_fingerprint": configuration_fingerprint(left),
        "to_fingerprint": configuration_fingerprint(right),
    }
