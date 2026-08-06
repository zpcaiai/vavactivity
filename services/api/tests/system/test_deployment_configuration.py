from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from vav.core.deployment_config import (
    DeploymentConfiguration,
    configuration_fingerprint,
    diff_configuration,
    load_deployment_configuration,
)

ROOT = Path(__file__).resolve().parents[4]


def test_every_environment_is_typed_and_secret_free() -> None:
    files = sorted((ROOT / "config" / "env").glob("*.yaml"))
    assert len(files) == 6
    environments = {load_deployment_configuration(path).environment for path in files}
    assert environments == {"development", "test", "ci", "staging", "production", "dr"}
    for path in files:
        raw = path.read_text(encoding="utf-8")
        assert "PRIVATE KEY-----" not in raw
        assert "sk_live_" not in raw


def test_production_rejects_insecure_defaults_and_unknown_keys() -> None:
    source = yaml.safe_load(
        (ROOT / "config" / "env" / "production.template.yaml").read_text(encoding="utf-8")
    )
    source["application"]["debug"] = True
    with pytest.raises(ValidationError, match="debug"):
        DeploymentConfiguration.model_validate(source)
    source["application"]["debug"] = False
    source["unexpected"] = "must fail"
    with pytest.raises(ValidationError, match="Extra inputs"):
        DeploymentConfiguration.model_validate(source)


def test_fingerprint_and_diff_never_emit_secret_references() -> None:
    development = load_deployment_configuration(ROOT / "config/env/development.yaml")
    staging = load_deployment_configuration(ROOT / "config/env/staging.yaml")
    fingerprint = configuration_fingerprint(staging)
    assert len(fingerprint["non_secret_configuration_hash"]) == 64
    assert "cloud://" not in str(fingerprint)
    diff = diff_configuration(development, staging)
    assert diff["secret_references_changed"] is True
    assert "database-url" not in str(diff)
