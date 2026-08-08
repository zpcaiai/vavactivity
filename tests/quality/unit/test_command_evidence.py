from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from vav.core.evidence import combined_status, junit_evidence


def _write_status(path: Path, status: str, exit_code: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
                "command": "pytest",
                "reason": "test fixture",
                "exit_code": exit_code,
            }
        ),
        encoding="utf-8",
    )


def _write_junit(path: Path, *, failures: int = 0, errors: int = 0) -> None:
    path.write_text(
        (
            '<testsuites><testsuite name="quality" tests="2" '
            f'failures="{failures}" errors="{errors}" skipped="0" />'
            "</testsuites>"
        ),
        encoding="utf-8",
    )


def test_junit_without_command_sidecar_is_not_run(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    _write_junit(junit)

    result = junit_evidence(junit, tmp_path / "missing-status.json")

    assert result["status"] == "NOT_RUN"


def test_failed_junit_can_never_become_pass(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    status = tmp_path / "status.json"
    _write_junit(junit, failures=1)
    _write_status(status, "PASS")

    result = junit_evidence(junit, status)

    assert result["status"] == "FAIL"
    assert result["failures"] == 1


def test_passing_junit_is_checksum_bound(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    status = tmp_path / "status.json"
    _write_junit(junit)
    _write_status(status, "PASS")

    result = junit_evidence(junit, status)

    assert result["status"] == "PASS"
    assert result["tests"] == 2
    assert len(result["checksum_sha256"]) == 64
    assert combined_status([result, {"status": "NOT_RUN"}]) == "NOT_RUN"
    assert combined_status([result, {"status": "FAIL"}]) == "FAIL"


def test_run_if_available_writes_machine_readable_status(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/run_if_available.sh"
    status = tmp_path / "command-status.json"
    env = {**os.environ, "RUN_IF_STATUS_FILE": str(status)}

    passed = subprocess.run(
        [str(script), "sh", "-c", "printf 'value with \"quotes\"\\n'"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert passed.returncode == 0
    assert json.loads(status.read_text(encoding="utf-8"))["status"] == "PASS"

    missing = subprocess.run(
        [str(script), "vav-command-that-does-not-exist"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert missing.returncode == 0
    assert json.loads(missing.stdout)["status"] == "NOT_RUN"
    assert json.loads(status.read_text(encoding="utf-8"))["status"] == "NOT_RUN"


def test_run_if_available_does_not_hide_application_file_errors(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/run_if_available.sh"
    status = tmp_path / "status.json"
    environment = os.environ | {"RUN_IF_STATUS_FILE": str(status)}

    failed = subprocess.run(
        [
            str(script),
            "sh",
            "-c",
            "printf '%s\\n' 'FileNotFoundError: [Errno 2] No such file or directory' >&2; exit 1",
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode == 1
    assert "FileNotFoundError" in failed.stderr
    assert json.loads(status.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_run_if_available_marks_webserver_startup_timeout_not_run(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/run_if_available.sh"
    status = tmp_path / "status.json"
    environment = os.environ | {"RUN_IF_STATUS_FILE": str(status)}

    unavailable = subprocess.run(
        [
            str(script),
            "sh",
            "-c",
            "printf '%s\\n' 'Error: Timed out waiting 120000ms from config.webServer.' >&2; exit 1",
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert unavailable.returncode == 0
    assert json.loads(unavailable.stdout)["status"] == "NOT_RUN"
    assert json.loads(status.read_text(encoding="utf-8"))["status"] == "NOT_RUN"
