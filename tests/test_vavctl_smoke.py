from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_smoke(
    tmp_path: Path,
    *,
    environment: str,
    login_status: int,
    include_test: bool,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
case "$*" in
  *"/api/v1/admin/auth/login"*) printf '401' ;;
  *"/api/v1/auth/login"*) printf '%s' "$FAKE_TEST_LOGIN_STATUS" ;;
  *) printf '200' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
case "$*" in
  *"get_settings().environment"*) printf '%s\n' "$FAKE_VAV_ENVIRONMENT" ;;
  *"alembic current"*) printf 'test-revision (head)\n' ;;
  *"redis-cli ping"*) printf 'PONG\n' ;;
  *) printf 'unexpected docker invocation: %s\n' "$*" >&2; exit 9 ;;
esac
""",
    )
    return subprocess.run(
        [str(ROOT / "scripts/vavctl"), "smoke"],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_VAV_ENVIRONMENT": environment,
            "FAKE_TEST_LOGIN_STATUS": str(login_status),
            "VAV_INCLUDE_TEST": "true" if include_test else "false",
        },
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("environment", ["development", "test", "ci"])
def test_smoke_warns_and_accepts_existing_local_test_fixture(
    tmp_path: Path,
    environment: str,
) -> None:
    result = _run_smoke(
        tmp_path,
        environment=environment,
        login_status=200,
        include_test=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        f"WARNING default test fixture remains login-ready in local environment: {environment}"
        in result.stdout
    )


@pytest.mark.parametrize(
    ("environment", "include_test"),
    [("production", False), ("production", True), ("dr", False), ("dr", True)],
)
def test_smoke_fails_closed_when_default_credentials_work_in_protected_environment(
    tmp_path: Path,
    environment: str,
    include_test: bool,
) -> None:
    result = _run_smoke(
        tmp_path,
        environment=environment,
        login_status=200,
        include_test=include_test,
    )

    assert result.returncode != 0
    assert (
        f"default test credentials are login-ready in protected environment: {environment}"
        in result.stdout
    )


def test_smoke_accepts_rejected_default_credentials(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        environment="production",
        login_status=401,
        include_test=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PASS    user login endpoint reachable" in result.stdout


def test_smoke_requires_explicitly_included_test_account_to_work(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        environment="test",
        login_status=401,
        include_test=True,
    )

    assert result.returncode != 0
    assert "Test account login failed: 401" in result.stderr
