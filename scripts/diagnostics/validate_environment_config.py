#!/usr/bin/env python3
"""Validate every committed environment configuration and emit safe fingerprints."""

from __future__ import annotations

import json
from pathlib import Path

from vav.core.deployment_config import (
    configuration_fingerprint,
    load_deployment_configuration,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "config" / "env"
EXPECTED = {
    "development.yaml": "development",
    "test.yaml": "test",
    "ci.yaml": "ci",
    "staging.yaml": "staging",
    "production.template.yaml": "production",
    "dr.yaml": "dr",
}


def main() -> None:
    fingerprints: dict[str, dict[str, str]] = {}
    for filename, environment in EXPECTED.items():
        config = load_deployment_configuration(CONFIG_ROOT / filename)
        if config.environment != environment:
            raise SystemExit(f"{filename}: expected environment {environment}")
        fingerprints[environment] = configuration_fingerprint(config)
    print(
        json.dumps(
            {"status": "PASS", "fingerprints": fingerprints}, indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
