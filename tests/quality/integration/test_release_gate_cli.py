"""The offline release-gate evaluator must be reproducible and fail closed."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/quality/evaluate_release_gate.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="CLI requires the repository checkout")


def _run(*args: str) -> tuple[int, dict[str, object]]:
    process = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return process.returncode, json.loads(process.stdout)


def test_self_check_fixture_is_no_go() -> None:
    code, payload = _run("--self-check")
    assert code == 1
    assert payload["decision"] == "no_go"
    assert payload["incomplete_flows"] == ["FLOW-COMMERCE-PURCHASE"]
    assert payload["critical_gap_count"] > 0


def test_self_check_is_reproducible() -> None:
    assert _run("--self-check") == _run("--self-check")


def test_clean_request_is_go(tmp_path: Path) -> None:
    request = {
        "release_version": "2026.08.0-rc.1",
        "environment": "staging",
        "inventory": {
            "requirements": [
                {
                    "code": "REQ-VAV-QUALITY-001",
                    "criticality": "blocker",
                    "status": "verified",
                    "capabilities": ["CAP-QUALITY-EVALUATE"],
                    "tests": ["tests/quality/gates/test_go_no_go_decision.py"],
                    "evidence": ["EVID-QUALITY-001"],
                    "owner_team": "quality_engineering",
                }
            ],
            "capabilities": [
                {
                    "code": "CAP-QUALITY-EVALUATE",
                    "capability_type": "admin_action",
                    "criticality": "blocker",
                    "exception_scenarios": ["EXC-QUALITY-EVIDENCE-MISSING"],
                    "metrics": ["quality_gate_runs_total"],
                    "audited": True,
                }
            ],
        },
        "closure_matrix": [
            {
                "flow_code": "FLOW-COMMERCE-PURCHASE",
                "criticality": "blocker",
                "dimensions": {
                    "entry": True,
                    "in_progress_state": True,
                    "success_terminal": True,
                    "failure_terminal": True,
                    "cancel_terminal": True,
                    "expiry_terminal": True,
                    "manual_intervention": True,
                    "compensation_path": True,
                    "user_visible_state": True,
                    "admin_actionable": True,
                },
            }
        ],
        "gate_outcomes": [
            {
                "code": "GATE-REQ-BLOCKER-COVERAGE",
                "enforcement": "blocker",
                "status": "passed",
            }
        ],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    code, payload = _run(str(path))
    assert code == 0
    assert payload["decision"] == "go"
    assert payload["gap_count"] == 0
    assert payload["structural_score"] == 100.0


def test_non_waivable_failure_overrides_a_clean_run(tmp_path: Path) -> None:
    request = {
        "release_version": "2026.08.0-rc.1",
        "environment": "staging",
        "gate_outcomes": [
            {
                "code": "GATE-REQ-BLOCKER-COVERAGE",
                "enforcement": "blocker",
                "status": "passed",
            }
        ],
        "non_waivable_failures": ["block_bypass"],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    code, payload = _run(str(path))
    assert code == 1
    assert payload["decision"] == "no_go"
    assert payload["vetoes"] == ["block_bypass"]


def test_empty_request_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text("{}", encoding="utf-8")
    code, payload = _run(str(path))
    assert code == 1
    assert payload["decision"] == "no_go"


def test_invalid_enum_value_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(
        json.dumps({"non_waivable_failures": ["definitely_not_a_failure"]}), encoding="utf-8"
    )
    code, payload = _run(str(path))
    assert code == 1
    assert payload["decision"] == "no_go"
    assert "error" in payload
