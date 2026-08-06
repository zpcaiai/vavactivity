#!/usr/bin/env python3
"""Show a redacted deployment-configuration diff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vav.core.deployment_config import diff_configuration, load_deployment_configuration

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "development": "development.yaml",
    "test": "test.yaml",
    "ci": "ci.yaml",
    "staging": "staging.yaml",
    "production": "production.template.yaml",
    "dr": "dr.yaml",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", choices=sorted(FILES))
    parser.add_argument(
        "--from-environment", default="development", choices=sorted(FILES)
    )
    args = parser.parse_args()
    root = ROOT / "config" / "env"
    left = load_deployment_configuration(root / FILES[args.from_environment])
    right = load_deployment_configuration(root / FILES[args.environment])
    print(json.dumps(diff_configuration(left, right), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
