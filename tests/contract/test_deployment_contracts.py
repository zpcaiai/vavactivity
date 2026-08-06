from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.release.render_deployment import render

ROOT = Path(__file__).resolve().parents[2]


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
    references = [item["remoteRef"]["key"] for item in external_secret["spec"]["data"]]
    assert len(references) == 15
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
