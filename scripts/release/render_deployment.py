#!/usr/bin/env python3
"""Render Kubernetes resources from a checksummed immutable release manifest."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_manifest_checksum(manifest_path: Path, checksum_path: Path) -> None:
    fields = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1] != manifest_path.name:
        raise ValueError("release manifest checksum sidecar is malformed")
    if fields[0] != _sha256(manifest_path):
        raise ValueError("release manifest checksum mismatch")


def _immutable_image(value: object, name: str) -> str:
    if not isinstance(value, str) or "@sha256:" not in value:
        raise ValueError(f"release image {name} is not digest pinned")
    digest = value.rsplit("@sha256:", 1)[1]
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"release image {name} has an invalid digest")
    return value


def _image_key(workload_name: str) -> str:
    if workload_name in {"api", "database-migration"}:
        return "api"
    if workload_name == "user-web":
        return "user_web"
    if workload_name == "admin-web":
        return "admin_web"
    if workload_name == "scheduler" or workload_name.startswith("worker-"):
        return "worker"
    raise ValueError(f"unmapped image-bearing workload: {workload_name}")


def render(
    manifest_path: Path,
    checksum_path: Path,
    input_path: Path,
    output_path: Path,
    expected_version: str | None,
    expected_commit: str | None,
    phase: str = "all",
) -> int:
    _verify_manifest_checksum(manifest_path, checksum_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0.0":
        raise ValueError("unsupported release manifest schema")
    release = manifest.get("release")
    images = manifest.get("images")
    if not isinstance(release, dict) or not isinstance(images, dict):
        raise ValueError("release manifest is incomplete")
    if expected_version is not None and release.get("version") != expected_version:
        raise ValueError("release version does not match deployment approval")
    if expected_commit is not None and release.get("git_commit") != expected_commit:
        raise ValueError("release commit does not match deployment checkout")
    immutable_images = {
        key: _immutable_image(images.get(key), key)
        for key in ("api", "worker", "user_web", "admin_web")
    }

    resources: list[dict[str, Any]] = []
    replacements = 0
    for resource in yaml.safe_load_all(input_path.read_text(encoding="utf-8")):
        if not isinstance(resource, dict):
            continue
        kind = resource.get("kind")
        if phase == "migration" and kind in {"Deployment", "StatefulSet", "DaemonSet"}:
            continue
        if phase == "application" and kind == "Job":
            continue
        pod_spec: dict[str, Any] | None = None
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
            pod_spec = resource.get("spec", {}).get("template", {}).get("spec")
        if isinstance(pod_spec, dict):
            workload_name = str(resource.get("metadata", {}).get("name", ""))
            key = _image_key(workload_name)
            for container in pod_spec.get("containers", []):
                if isinstance(container, dict) and "image" in container:
                    container["image"] = immutable_images[key]
                    replacements += 1
        resources.append(resource)
    if replacements == 0:
        raise ValueError("rendered deployment contained no replaceable images")
    rendered = yaml.safe_dump_all(resources, sort_keys=False)
    if "sha256:0000000000000000" in rendered or ":latest" in rendered:
        raise ValueError("rendered deployment still contains mutable image identity")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return replacements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-commit")
    parser.add_argument(
        "--phase", choices=("all", "migration", "application"), default="all"
    )
    args = parser.parse_args()
    replacements = render(
        args.manifest,
        args.checksum,
        args.input,
        args.output,
        args.expected_version,
        args.expected_commit,
        args.phase,
    )
    print(f"rendered {replacements} immutable workload images")


if __name__ == "__main__":
    main()
