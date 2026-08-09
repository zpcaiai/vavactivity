#!/usr/bin/env python3
"""Build a checksummed release manifest without logging secret configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml


def immutable_digest(value: str) -> str:
    if "@sha256:" not in value or len(value.rsplit("@sha256:", 1)[1]) != 64:
        raise ValueError(f"mutable or invalid image identity: {value}")
    return value


def git_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError("commit must be a full lowercase 40-character SHA")
    return value


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True, type=git_commit)
    parser.add_argument("--frontend-commit", required=True, type=git_commit)
    parser.add_argument("--api", required=True, type=immutable_digest)
    parser.add_argument("--worker", required=True, type=immutable_digest)
    parser.add_argument("--user-web", required=True, type=immutable_digest)
    parser.add_argument("--admin-web", required=True, type=immutable_digest)
    parser.add_argument("--configuration-fingerprint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest = {
        "schema_version": "1.0.0",
        "release": {
            "version": args.version,
            "git_commit": args.commit,
            "frontend_git_commit": args.frontend_commit,
            "built_at": datetime.now(UTC).isoformat(),
        },
        "images": {
            "api": args.api,
            "worker": args.worker,
            "user_web": args.user_web,
            "admin_web": args.admin_web,
        },
        "database": {"target_revision": "20260806_0086"},
        "contracts": {
            "openapi_sha256": checksum(root / "packages/contracts/openapi.json"),
            "events_sha256": checksum(root / "config/events/manifest.yaml"),
        },
        "configuration": {
            "schema_version": "1.0.0",
            "non_secret_fingerprint": args.configuration_fingerprint,
        },
        "production_certification": "NOT_CERTIFIED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    digest = checksum(args.output)
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="utf-8"
    )
    print(
        json.dumps({"status": "PASS", "manifest": str(args.output), "sha256": digest})
    )


if __name__ == "__main__":
    main()
