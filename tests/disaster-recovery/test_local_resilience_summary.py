from __future__ import annotations

import json
from pathlib import Path

from scripts.resilience.summarize_local_suite import build_summary


def _write_report(path: Path, status: str = "PASS") -> None:
    path.write_text(json.dumps({"status": status}) + "\n", encoding="utf-8")


def test_local_suite_requires_and_accepts_api_ha_evidence(tmp_path: Path) -> None:
    _write_report(tmp_path / "restore-drill-test.json")
    for service in ("api", "redis", "worker", "minio", "scheduler"):
        _write_report(tmp_path / f"chaos-{service}.json")

    without_ha = build_summary(
        tmp_path, git_commit="a" * 40, worktree_clean=True
    )
    assert without_ha["status"] == "FAIL"
    assert without_ha["local_application_ha"] == "FAIL"

    _write_report(tmp_path / "api-ha.json")
    with_ha = build_summary(tmp_path, git_commit="a" * 40, worktree_clean=True)
    assert with_ha["status"] == "LOCAL_PASS"
    assert with_ha["local_application_ha"] == "LOCAL_PASS"
    assert with_ha["application_ha"] == "NOT_EVALUATED"
    assert with_ha["database_ha"] == "NOT_EVALUATED"
    assert with_ha["regional_dr"] == "NOT_EVALUATED"


def test_failed_ha_report_fails_the_suite(tmp_path: Path) -> None:
    _write_report(tmp_path / "restore-drill-test.json")
    for service in ("api", "redis", "worker", "minio", "scheduler"):
        _write_report(tmp_path / f"chaos-{service}.json")
    _write_report(tmp_path / "api-ha.json", status="FAIL")

    summary = build_summary(tmp_path, git_commit="b" * 40, worktree_clean=False)
    assert summary["status"] == "FAIL"
    assert summary["failures"] == ["api-ha.json"]
    assert summary["backup_restore"] == "LOCAL_PASS"
    assert summary["chaos_recovery"] == "LOCAL_PASS"
    assert summary["local_application_ha"] == "FAIL"
