from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_architecture_certification_is_honest_and_checksums_artifacts(
    tmp_path: Path,
) -> None:
    output = tmp_path / "skill-platform.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/certification/skill_platform.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["technical_status"] == "PASS"
    assert report["certification_level"] == "tested"
    assert report["production_certification"] == "NOT_CERTIFIED"
    assert report["release_allowed"] is False
    assert report["evidence"]["sandbox-escape"]["status"] == "NOT_EVALUATED"
    assert output.with_suffix(".json.sha256").is_file()


def test_production_certification_requires_complete_commit_bound_evidence(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/certification/skill_platform.py"),
            "--mode",
            "production",
            "--evidence-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "report.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "missing production evidence" in result.stderr
