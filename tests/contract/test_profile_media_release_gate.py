from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/profile_media_activation_gate.py"
SPEC = importlib.util.spec_from_file_location("profile_media_activation_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
ActivationGateError = GATE.ActivationGateError
validate_activation_evidence = GATE.validate_activation_evidence

IMAGE = f"registry.example/vav-api@sha256:{'a' * 64}"
REQUIRED_WORKLOADS = {"api", "worker-privacy", "scheduler"}


def _evidence() -> dict[str, object]:
    return {
        "database_revision": "20260813_0112",
        "profile_media_enabled": False,
        "automatic_rollback_enabled": False,
        "active_assets_without_storage_key": 0,
        "approved_workload_images": {name: IMAGE for name in REQUIRED_WORKLOADS},
        "workloads": [
            {
                "name": name,
                "image": IMAGE,
                "ready_replicas": 1,
                "desired_replicas": 1,
            }
            for name in sorted(REQUIRED_WORKLOADS)
        ],
    }


def _validate(evidence: dict[str, object]) -> None:
    validate_activation_evidence(
        evidence,
        required_workloads=REQUIRED_WORKLOADS,
        alembic_config=ROOT / "services/api/alembic.ini",
    )


def test_activation_gate_accepts_only_a_complete_quiesced_rollout() -> None:
    _validate(_evidence())


@pytest.mark.parametrize(
    ("field", "unsafe_value", "message"),
    [
        ("database_revision", "20260813_0111", "must include migration"),
        ("profile_media_enabled", True, "must still be false"),
        ("automatic_rollback_enabled", True, "rollback must be disabled"),
        ("active_assets_without_storage_key", 1, "must have a storage_key"),
    ],
)
def test_activation_gate_rejects_unsafe_release_facts(
    field: str, unsafe_value: object, message: str
) -> None:
    evidence = _evidence()
    evidence[field] = unsafe_value
    with pytest.raises(ActivationGateError, match=message):
        _validate(evidence)


def test_activation_gate_rejects_an_old_or_partially_ready_workload() -> None:
    old_image = deepcopy(_evidence())
    old_image["workloads"][0]["image"] = f"registry.example/old@sha256:{'b' * 64}"  # type: ignore[index]
    with pytest.raises(ActivationGateError, match="approved backend image"):
        _validate(old_image)

    partial = deepcopy(_evidence())
    partial["workloads"][0]["ready_replicas"] = 0  # type: ignore[index]
    with pytest.raises(ActivationGateError, match="not fully ready"):
        _validate(partial)

    mutable_approval = deepcopy(_evidence())
    mutable_approval["approved_workload_images"]["api"] = "vav-api:latest"  # type: ignore[index]
    with pytest.raises(ActivationGateError, match="immutable @sha256"):
        _validate(mutable_approval)


def test_activation_gate_rejects_missing_required_workload_evidence() -> None:
    evidence = _evidence()
    evidence["workloads"] = [
        item
        for item in evidence["workloads"]
        if item["name"] != "worker-privacy"  # type: ignore[index,union-attr]
    ]
    with pytest.raises(ActivationGateError, match="worker-privacy"):
        _validate(evidence)


def test_all_production_targets_keep_storage_v2_off_until_the_gate() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy/compose/docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    api = compose["services"]["api"]
    assert api["environment"]["PROFILE_MEDIA_ENABLED"] == (
        "${PROFILE_MEDIA_ENABLED:-false}"
    )
    assert api["deploy"]["update_config"] == {
        "order": "stop-first",
        "failure_action": "pause",
    }

    kubernetes = yaml.safe_load(
        (ROOT / "deploy/kubernetes/base/configmap.yaml").read_text(encoding="utf-8")
    )
    assert kubernetes["data"]["PROFILE_MEDIA_ENABLED"] == "false"

    render = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    api_service = next(
        item for item in render["services"] if item["name"] == "vav-platform-api"
    )
    render_environment = {item["key"]: item for item in api_service["envVars"]}
    assert render_environment["PROFILE_MEDIA_ENABLED"]["value"] == "false"

    production_environment = (
        ROOT / "config/runtime/production.env.template"
    ).read_text(encoding="utf-8")
    assert "PROFILE_MEDIA_ENABLED=false" in production_environment.splitlines()


def test_expand_migration_binds_pre_0112_writes_before_enforcing_storage_key() -> None:
    migration = (
        ROOT
        / "services/api/migrations/versions/20260813_0112_profile_media_storage_integrity.py"
    ).read_text(encoding="utf-8")
    trigger = migration.index("CREATE TRIGGER profile_media_bind_legacy_storage_key")
    active_check = migration.index(
        "ADD CONSTRAINT profile_media_assets_active_storage_key"
    )
    assert trigger < active_check
    assert "BEFORE INSERT OR UPDATE OF access_token, storage_key, state" in migration
    assert "NEW.storage_key := 'profile-media/' || NEW.access_token" in migration
    assert "NEW.upload_expires_at := now() + interval '20 minutes'" in migration
