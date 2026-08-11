from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_render_is_the_only_active_backend_deployment_target() -> None:
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    api = next(
        service
        for service in blueprint["services"]
        if service["name"] == "vav-platform-api"
    )

    assert api["runtime"] == "docker"
    assert api["branch"] == "main"
    assert api["autoDeployTrigger"] == "checksPass"
    assert api["dockerfilePath"] == "infra/docker/backend.Dockerfile"

    workflows = ROOT / ".github" / "workflows"
    assert not list(workflows.glob("*huggingface*"))
    assert not (workflows / "deploy-production.yml").exists()
    assert not (workflows / "deploy-staging.yml").exists()
    assert not list((ROOT / "scripts" / "hf").glob("*"))
    assert not list((ROOT / "deploy" / "huggingface").glob("*"))
