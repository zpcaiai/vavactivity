#!/usr/bin/env python3
"""Fail-closed gate for activating profile-media storage v2.

Migration 0112 is expand-compatible with the previous API, but the new API
finalizes objects under a different key. A pre-0112 binary therefore is not a
safe rollback target after activation. This gate consumes evidence gathered
from the deployment control plane and refuses activation until the schema,
data, workload image, readiness, feature flag, and rollback facts agree.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

REQUIRED_REVISION = "20260813_0112"
IMMUTABLE_IMAGE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")


class ActivationGateError(ValueError):
    """The supplied live evidence is not safe enough to enable the feature."""


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActivationGateError(f"{name} must be a JSON object")
    return value


def _revision_contains(
    current_revision: str, *, alembic_config: Path, required_revision: str
) -> bool:
    scripts = ScriptDirectory.from_config(Config(str(alembic_config)))
    try:
        revisions = scripts.walk_revisions(base="base", head=current_revision)
        return required_revision in {item.revision for item in revisions}
    except Exception as error:  # Alembic's resolution errors vary by version.
        raise ActivationGateError(
            f"database_revision is not in this release's migration graph: {current_revision}"
        ) from error


def validate_activation_evidence(
    evidence: dict[str, Any],
    *,
    required_workloads: set[str],
    alembic_config: Path,
) -> None:
    current_revision = evidence.get("database_revision")
    if not isinstance(current_revision, str) or not _revision_contains(
        current_revision,
        alembic_config=alembic_config,
        required_revision=REQUIRED_REVISION,
    ):
        raise ActivationGateError(
            f"database schema must include migration {REQUIRED_REVISION}"
        )

    if evidence.get("profile_media_enabled") is not False:
        raise ActivationGateError(
            "PROFILE_MEDIA_ENABLED must still be false while activation is checked"
        )
    if evidence.get("automatic_rollback_enabled") is not False:
        raise ActivationGateError(
            "automatic rollback must be disabled before storage v2 is activated"
        )
    if evidence.get("active_assets_without_storage_key") != 0:
        raise ActivationGateError(
            "every active profile-media row must have a storage_key"
        )

    approved_images = _require_mapping(
        evidence.get("approved_workload_images"), "approved_workload_images"
    )

    workloads_value = evidence.get("workloads")
    if not isinstance(workloads_value, list):
        raise ActivationGateError("workloads must be a JSON array")
    workloads: dict[str, dict[str, Any]] = {}
    for index, raw_workload in enumerate(workloads_value):
        workload = _require_mapping(raw_workload, f"workloads[{index}]")
        name = workload.get("name")
        if not isinstance(name, str) or not name or name in workloads:
            raise ActivationGateError("workload names must be non-empty and unique")
        workloads[name] = workload

    missing = sorted(required_workloads - workloads.keys())
    if missing:
        raise ActivationGateError(
            f"required backend workloads are missing: {', '.join(missing)}"
        )
    for name in sorted(required_workloads):
        workload = workloads[name]
        approved_image = approved_images.get(name)
        if not isinstance(approved_image, str) or not IMMUTABLE_IMAGE.fullmatch(
            approved_image
        ):
            raise ActivationGateError(
                f"approved image for {name} must be an immutable @sha256 digest"
            )
        if workload.get("image") != approved_image:
            raise ActivationGateError(
                f"workload {name} is not running the approved backend image"
            )
        desired = workload.get("desired_replicas")
        ready = workload.get("ready_replicas")
        if not isinstance(desired, int) or isinstance(desired, bool) or desired < 1:
            raise ActivationGateError(
                f"workload {name} must declare at least one desired replica"
            )
        if ready != desired:
            raise ActivationGateError(
                f"workload {name} is not fully ready ({ready!r}/{desired})"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--required-workload",
        action="append",
        default=[],
        help="backend workload that must be fully rolled out; repeat as needed",
    )
    parser.add_argument(
        "--alembic-config",
        type=Path,
        default=Path("services/api/alembic.ini"),
    )
    args = parser.parse_args()
    raw_evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    evidence = _require_mapping(raw_evidence, "evidence")
    required_workloads = set(args.required_workload or ["api"])
    validate_activation_evidence(
        evidence,
        required_workloads=required_workloads,
        alembic_config=args.alembic_config,
    )
    print(
        "profile-media storage v2 activation gate passed; "
        "enable the flag without changing the approved backend images"
    )


if __name__ == "__main__":
    main()
