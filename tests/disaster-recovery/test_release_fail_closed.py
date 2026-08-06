from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_architecture_readiness_never_claims_production_certification(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/release/production-readiness.sh")],
        cwd=ROOT,
        env={**os.environ, "READINESS_EVIDENCE_DIR": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["technical_status"] == "PASS"
    assert report["production_certification"] == "NOT_CERTIFIED"
    assert "not evaluated" in report["reason"]


def test_restore_drill_is_isolated_and_cleans_up() -> None:
    script = (ROOT / "scripts/restore/run-restore-drill.sh").read_text(encoding="utf-8")
    assert "mktemp -d" in script
    assert "docker rm -f" in script
    assert "trap cleanup EXIT" in script
    assert "pg_restore" in script
    assert "information_schema.tables" in script


def test_production_readiness_rejects_evidence_from_another_release(
    tmp_path: Path,
) -> None:
    required = (
        "staging-smoke complete-e2e migration-dry-run backup restore-drill "
        "vulnerability-scan image-signature red-team privacy-e2e payment-e2e "
        "block-propagation production-approval production-smoke"
    ).split()
    for name in required:
        (tmp_path / f"{name}.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "artifact_sha256": "a" * 64,
                    "completed_at": "2026-08-06T00:00:00Z",
                    "release_version": "old-release",
                    "git_commit": "old-commit",
                }
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [str(ROOT / "scripts/release/production-readiness.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PRODUCTION_READINESS_MODE": "production",
            "READINESS_EVIDENCE_DIR": str(tmp_path),
            "PRODUCTION_RELEASE_VERSION": "approved-release",
            "PRODUCTION_RELEASE_COMMIT": "approved-commit",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "evidence release mismatch" in result.stderr
