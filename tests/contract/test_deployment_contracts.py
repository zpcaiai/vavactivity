from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import vav.cli.seed_test_showcase as seed_test_showcase_module
from scripts.release.build_release_manifest import git_commit
from scripts.release.render_deployment import render

ROOT = Path(__file__).resolve().parents[2]


def test_render_blueprint_declares_fail_closed_staging_inputs() -> None:
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    api = next(
        service
        for service in blueprint["services"]
        if service["name"] == "vav-platform-api"
    )
    environment = {item["key"]: item for item in api["envVars"]}

    assert api["healthCheckPath"] == "/api/v1/health/live"
    fail_closed_values = {
        "APP_ENV": "staging",
        "APP_DEBUG": "false",
        "AUTH_COOKIE_SECURE": "true",
        "PAYMENT_TEST_FAKE_ENABLED": "false",
        "COURSE_VIDEO_PROVIDER": "approved_private",
        "COUNSELING_MEETING_PROVIDER": "approved",
        "KNOWLEDGE_EMBEDDING_PROVIDER": "approved",
        "AI_ENABLED": "true",
        "AI_MODEL_PROVIDER": "gemini",
        "AI_MODEL_NAME": "gemini-3.6-flash",
        "AI_CONVERSATION_ENCRYPTION_ENABLED": "true",
        "NOTIFICATION_EMAIL_PROVIDER": "transactional",
        "PRIVACY_FIELD_ENCRYPTION_ENABLED": "true",
        "PRIVACY_EXPORT_ENCRYPTION_ENABLED": "true",
    }
    assert all(
        environment[key].get("value") == value
        for key, value in fail_closed_values.items()
    )

    public_runtime_values = {
        "APP_CORS_ORIGINS": '["https://vavactivity.vercel.app"]',
        "AUTH_ALLOWED_ORIGINS": '["https://vavactivity.vercel.app"]',
        "USER_WEB_URL": "https://vavactivity.vercel.app",
        "PUBLIC_WEB_BASE_URL": "https://vavactivity.vercel.app",
        "PUBLIC_API_BASE_URL": "https://vav-platform-api.onrender.com",
    }
    assert all(
        environment[key].get("value") == value
        for key, value in public_runtime_values.items()
    )

    externally_managed = {
        "ADMIN_WEB_URL",
        "DATABASE_URL",
        "MEDIA_S3_ENDPOINT",
        "MEDIA_S3_PUBLIC_ENDPOINT",
        "MEDIA_S3_ACCESS_KEY",
        "MEDIA_S3_SECRET_KEY",
        "AUTH_PRIVATE_KEY",
        "AUTH_PUBLIC_KEY",
        "GEMINI_API_KEY",
    }
    assert all(environment[key].get("sync") is False for key in externally_managed)
    assert all("value" not in environment[key] for key in externally_managed)

    generated_secrets = {
        "AUTH_REFRESH_TOKEN_PEPPER",
        "BACKUP_ENCRYPTION_KEY",
        "PRIVACY_SEARCH_HMAC_PEPPER",
        "NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET",
    }
    assert all(
        environment[key].get("generateValue") is True for key in generated_secrets
    )
    assert all("value" not in environment[key] for key in generated_secrets)


def test_neon_staging_migrates_before_seeding_the_complete_showcase() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/backend-ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["neon-migrations"]
    assert job["timeout-minutes"] >= 30
    steps = job["steps"]
    migration_step = next(
        step for step in steps if step.get("name") == "Apply pending migrations to Neon"
    )
    assert migration_step["env"]["APP_ENV"] == "staging"
    assert "alembic -c services/api/alembic.ini upgrade head" in migration_step["run"]

    verification_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Verify the live Neon schema"
    )
    showcase_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Seed deterministic staging showcases"
    )
    assert verification_index < showcase_index

    showcase_step = steps[showcase_index]
    assert showcase_step["env"]["APP_ENV"] == "staging"
    assert "python -m vav.cli.seed_admin_showcase" in showcase_step["run"]
    assert "--confirm-admin-showcase" in showcase_step["run"]
    assert "seed_test_showcase" not in showcase_step["run"]

    admin_showcase_source = (
        ROOT / "services/api/src/vav/cli/seed_admin_showcase.py"
    ).read_text(encoding="utf-8")
    test_showcase_source = (
        ROOT / "services/api/src/vav/cli/seed_test_showcase.py"
    ).read_text(encoding="utf-8")
    assert "business_counts = await seed_test_showcase()" in admin_showcase_source
    assert "await seed_test_user()" in test_showcase_source

    manifest = yaml.safe_load(
        (ROOT / "config/seeds/manifest.yaml").read_text(encoding="utf-8")
    )
    assert "vav.cli.seed_test_showcase" in manifest["groups"]["test"]
    assert "test" not in manifest["production_allowed_groups"]


def test_showcase_ids_are_stable_and_namespaced() -> None:
    first = seed_test_showcase_module._id("notification:1")
    assert first == seed_test_showcase_module._id("notification:1")
    assert first != seed_test_showcase_module._id("notification:2")


@pytest.mark.parametrize("environment", ["production", "dr"])
@pytest.mark.asyncio
async def test_showcase_seed_rejects_protected_environment_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    reference_data_accessed = False

    async def forbidden_reference_data() -> None:
        nonlocal reference_data_accessed
        reference_data_accessed = True
        raise AssertionError(
            "protected seed policy must run before reference-data access"
        )

    monkeypatch.setattr(
        seed_test_showcase_module,
        "get_settings",
        lambda: SimpleNamespace(environment=environment),
    )
    monkeypatch.setattr(
        seed_test_showcase_module,
        "_seed_reference_data",
        forbidden_reference_data,
    )

    with pytest.raises(RuntimeError, match=f"protected environment: {environment}"):
        await seed_test_showcase_module.seed_test_showcase()

    assert reference_data_accessed is False


def test_production_compose_uses_external_state_and_immutable_images() -> None:
    path = ROOT / "deploy/compose/docker-compose.prod.yml"
    raw = path.read_text(encoding="utf-8")
    compose = yaml.safe_load(raw)
    forbidden = {"postgres", "redis", "minio", "mailpit"}
    assert forbidden.isdisjoint(compose["services"])
    for service in compose["services"].values():
        image = service.get("image")
        if image:
            assert "IMAGE" in image or re.search(r"@sha256:[0-9a-f]{64}$", image)
        assert service.get("security_opt") == ["no-new-privileges:true"]


def test_production_kubernetes_has_isolation_and_availability_guards() -> None:
    files = list((ROOT / "deploy/kubernetes/base").glob("*.yaml"))
    documents = []
    for path in files:
        documents.extend(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    kinds = {document["kind"] for document in documents if document}
    assert {
        "NetworkPolicy",
        "PodDisruptionBudget",
        "HorizontalPodAutoscaler",
        "Ingress",
    } <= kinds
    deployments = [
        document
        for document in documents
        if document and document["kind"] == "Deployment"
    ]
    assert deployments
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        assert pod.get("securityContext", {}).get("runAsNonRoot") is True

    runtime_config = next(
        document
        for document in documents
        if document
        and document["kind"] == "ConfigMap"
        and document["metadata"]["name"] == "vav-runtime"
    )["data"]
    assert runtime_config["MEDIA_S3_ENDPOINT"].startswith("https://")
    assert runtime_config["MEDIA_S3_PUBLIC_ENDPOINT"].startswith("https://")


def test_no_production_secret_values_are_committed() -> None:
    candidates = [
        ROOT / "config/env/production.template.yaml",
        ROOT / "config/env/dr.yaml",
    ]
    for path in candidates:
        raw = path.read_text(encoding="utf-8")
        assert "PRIVATE KEY-----" not in raw
        assert "sk_live_" not in raw
        assert "password:" not in raw.lower()
        assert "cloud://" in raw


def test_image_security_gate_scans_high_and_critical_findings() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/build-images.yml").read_text(encoding="utf-8")
    )
    build_steps = workflow["jobs"]["build"]["steps"]
    trivy = next(
        step
        for step in build_steps
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
    )
    assert trivy["uses"].startswith("aquasecurity/trivy-action@v")
    assert trivy["with"]["severity"] == "CRITICAL,HIGH"
    assert trivy["with"]["exit-code"] == "1"
    assert trivy["with"]["ignore-unfixed"] is True
    assert "HIGH" not in trivy["with"]


def test_split_release_builds_only_owned_images_and_requires_frontend_handoff() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/build-images.yml").read_text(encoding="utf-8")
    )
    matrix = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    assert {item["name"] for item in matrix} == {"api", "worker"}
    release_job = workflow["jobs"]["release-manifest"]
    condition = release_job["if"]
    assert "frontend_commit" in condition
    assert "user_web_image" in condition
    assert "admin_web_image" in condition
    command = next(
        step["run"]
        for step in release_job["steps"]
        if step.get("name") == "Build checksummed release manifest"
    )
    assert "--frontend-commit" in command
    assert "inputs.user_web_image" in command
    assert "inputs.admin_web_image" in command


def test_release_manifest_requires_full_backend_and_frontend_commit_identities() -> (
    None
):
    commit = "a" * 40
    assert git_commit(commit) == commit
    for invalid in ("abc123", "A" * 40, "g" * 40, "a" * 64):
        with pytest.raises(argparse.ArgumentTypeError, match="full lowercase"):
            git_commit(invalid)


def test_release_manifest_renders_every_workload_with_immutable_images(
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    manifest = tmp_path / "release.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "release": {"version": "v1", "git_commit": "abc123"},
                "images": {
                    "api": f"registry.example/vav-api@sha256:{digest}",
                    "worker": f"registry.example/vav-worker@sha256:{digest}",
                    "user_web": f"registry.example/vav-user@sha256:{digest}",
                    "admin_web": f"registry.example/vav-admin@sha256:{digest}",
                },
            }
        ),
        encoding="utf-8",
    )
    checksum = tmp_path / "release.yaml.sha256"
    checksum.write_text(
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n",
        encoding="utf-8",
    )
    rendered_input = tmp_path / "kubernetes.yaml"
    rendered_input.write_text(
        subprocess.run(
            [
                "kubectl",
                "kustomize",
                str(ROOT / "deploy/kubernetes/overlays/production"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout,
        encoding="utf-8",
    )
    output = tmp_path / "rendered.yaml"
    replacements = render(manifest, checksum, rendered_input, output, "v1", "abc123")
    raw = output.read_text(encoding="utf-8")
    assert replacements == 10
    assert "sha256:0000000000000000" not in raw
    assert raw.count(f"@sha256:{digest}") == 10


def test_release_manifest_checksum_is_fail_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "release.yaml"
    manifest.write_text("schema_version: 1.0.0\n", encoding="utf-8")
    checksum = tmp_path / "release.yaml.sha256"
    checksum.write_text(f"{'0' * 64}  {manifest.name}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        render(manifest, checksum, manifest, tmp_path / "out.yaml", None, None)


def test_kubernetes_queue_arguments_remain_single_arguments() -> None:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "deploy/kubernetes/overlays/production")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    documents = [value for value in yaml.safe_load_all(rendered) if value]
    deployments = {
        value["metadata"]["name"]: value
        for value in documents
        if value.get("kind") == "Deployment"
    }
    default_args = deployments["worker-default"]["spec"]["template"]["spec"][
        "containers"
    ][0]["args"]
    ai_args = deployments["worker-ai"]["spec"]["template"]["spec"]["containers"][0][
        "args"
    ]
    assert "--queues=default,commerce,activities,courses,counseling" in default_args
    assert "--queues=ai,knowledge,recommendations" in ai_args
    namespaced = [value for value in documents if value.get("kind") != "Namespace"]
    assert {value.get("metadata", {}).get("namespace") for value in namespaced} == {
        "vav-production"
    }
    external_secret = next(
        value for value in documents if value.get("kind") == "ExternalSecret"
    )
    secret_data = external_secret["spec"]["data"]
    references = [item["remoteRef"]["key"] for item in secret_data]
    assert {item["secretKey"] for item in secret_data} == {
        "DATABASE_URL",
        "REDIS_URL",
        "AUTH_REFRESH_TOKEN_PEPPER",
        "PRIVACY_SEARCH_HMAC_PEPPER",
        "CHECKIN_LAST_FOUR_HMAC_KEY",
        "CHECKIN_TOKEN_SIGNING_KEY",
        "SHARE_LINK_SECRET",
        "PROFILE_MEDIA_TOKEN_SECRET",
        "DISCOVERY_IP_MARKER_SALT",
        "BACKUP_ENCRYPTION_KEY",
        "auth-private.pem",
        "auth-public.pem",
        "MEDIA_S3_ACCESS_KEY",
        "MEDIA_S3_SECRET_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_WEBHOOK_ID",
        "NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET",
        "GEMINI_API_KEY",
    }
    assert all(reference.startswith("vav/production/") for reference in references)
    backend_names = {
        "api",
        "database-migration",
        "scheduler",
        "worker-ai",
        "worker-default",
        "worker-notifications",
        "worker-privacy",
        "worker-safety",
    }
    for workload in (
        value
        for value in documents
        if value.get("kind") in {"Deployment", "Job"}
        and value.get("metadata", {}).get("name") in backend_names
    ):
        mounts = workload["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
        assert any(
            mount.get("name") == "runtime-auth" and mount.get("readOnly") is True
            for mount in mounts
        )
