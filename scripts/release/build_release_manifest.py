#!/usr/bin/env python3
"""Build a checksummed release manifest without logging secret configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api/src"))
from vav.modules.commerce.providers.china import CHINA_PAYMENT_DECISION  # noqa: E402


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


def migration_head(versions_dir: Path) -> str:
    """Resolve the single head of the Alembic chain.

    Previously the manifest carried a hard-coded revision. It had drifted 26
    revisions behind the repository, so a release report would have told an
    operator to expect a schema that no longer matched the images it shipped
    alongside. Reading the chain removes the class of error: a head is the
    revision nothing else declares as its `down_revision`.
    """

    revisions: dict[str, str | None] = {}
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        # Both spellings occur in this repository: the older migrations use an
        # annotated assignment (`revision: str = "..."`), the newer ones a bare
        # one. Matching only the bare form silently skipped 26 of 112 files.
        revision = re.search(r'^revision\s*(?::[^=]+)?=\s*["\']([^"\']+)["\']', text, re.M)
        down = re.search(r'^down_revision\s*(?::[^=]+)?=\s*["\']([^"\']+)["\']', text, re.M)
        if revision:
            revisions[revision.group(1)] = down.group(1) if down else None
    if not revisions:
        raise ValueError(f"no Alembic revisions found under {versions_dir}")
    parents = {down for down in revisions.values() if down}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        # A release must not guess which of several heads it is deploying.
        raise ValueError(f"expected exactly one migration head, found {heads}")
    return heads[0]


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
        "database": {
            "target_revision": migration_head(root / "services/api/migrations/versions")
        },
        "contracts": {
            "openapi_sha256": checksum(root / "packages/contracts/openapi.json"),
            "events_sha256": checksum(root / "config/events/manifest.yaml"),
        },
        "configuration": {
            "schema_version": "1.0.0",
            "non_secret_fingerprint": args.configuration_fingerprint,
        },
        # Acceptance for PAY-003: the decision that keeps a channel closed has
        # to be visible in the release report, not only in the code that
        # refuses. An operator reading this manifest should be able to see
        # which capabilities are absent by decision rather than by defect.
        "pending_decisions": [
            {
                "id": CHINA_PAYMENT_DECISION,
                "title": "China and international payment entities",
                "status": "PROPOSED",
                "blocks": ["OPS-004", "PAY-002", "PAY-003"],
                "effect": (
                    "WeChat Pay and Alipay are stubbed and refused; "
                    "Stripe and PayPal are the only offered channels."
                ),
            }
        ],
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
