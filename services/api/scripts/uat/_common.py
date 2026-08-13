"""Shared reporting for the B02/B03 verification scripts.

Standard library only, on purpose: these scripts run on a laptop that has not
installed anything yet, in CI before dependencies are cached, and on a bastion
host during an incident. A verification tool that needs its own dependencies
installed cannot verify the thing it is there to verify.

Three ideas the whole file exists to express:

* A check has three honest outcomes, not two. ``PASS`` and ``FAIL`` are the easy
  ones; ``BLOCKED`` means "this check could not run" - no ``psycopg``, no
  network, no binary - and it is reported loudly rather than skipped. A silent
  skip reads as a pass on a dashboard, which is how "all green" comes to mean
  nothing.
* Every result carries the exact command or probe it ran, so a reader can
  reproduce it by hand instead of trusting the summary.
* Nothing here raises out of a check. A traceback is the least actionable
  output an operations script can produce.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    #: The check could not be performed. Never treated as success.
    BLOCKED = "BLOCKED"
    #: The check ran and the answer is "not wrong, but look at this".
    WARN = "WARN"


#: Statuses that make the run unsuccessful. ``BLOCKED`` is in here deliberately:
#: an unverified system is not a verified one.
FAILING_STATUSES: frozenset[Status] = frozenset({Status.FAIL, Status.BLOCKED})

EXIT_OK = 0
EXIT_ACTIONABLE_FAILURE = 1


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CheckResult:
    """One verified fact, with the evidence needed to reproduce it."""

    name: str
    status: Status
    detail: str
    #: The literal command or probe. ``psql -c 'select 1'``, ``TCP 127.0.0.1:5432``.
    command: str = ""
    #: What the reader should *do*. Required for anything not passing - a
    #: failure without a next step is a complaint, not a report.
    remedy: str = ""
    timestamp: str = field(default_factory=utcnow_iso)
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": str(self.status),
            "detail": self.detail,
            "command": self.command,
            "remedy": self.remedy,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "extra": self.extra,
        }


class Report:
    """Collects results and renders both machine and human output."""

    def __init__(self, tool: str, description: str = "") -> None:
        self.tool = tool
        self.description = description
        self.started_at = utcnow_iso()
        self.results: list[CheckResult] = []

    def add(self, result: CheckResult) -> CheckResult:
        self.results.append(result)
        return result

    def record(
        self,
        name: str,
        status: Status,
        detail: str,
        *,
        command: str = "",
        remedy: str = "",
        duration_ms: int = 0,
        **extra: Any,
    ) -> CheckResult:
        return self.add(
            CheckResult(
                name=name,
                status=status,
                detail=detail,
                command=command,
                remedy=remedy,
                duration_ms=duration_ms,
                extra=dict(extra),
            )
        )

    def guard(self, name: str, command: str, func: Callable[[], CheckResult]) -> CheckResult:
        """Run one check, converting any escaping exception into ``BLOCKED``.

        This is the single reason these scripts cannot traceback: an unexpected
        error becomes a reported, attributed, actionable result instead of a
        stack trace and an exit code nobody can interpret.
        """

        started = time.monotonic()
        try:
            result = func()
        except Exception as exc:  # noqa: BLE001 - a report must never crash
            result = CheckResult(
                name=name,
                status=Status.BLOCKED,
                detail=f"{type(exc).__name__}: {exc}",
                command=command,
                remedy=(
                    "This check could not run. Fix the underlying error above, then "
                    "re-run; a blocked check is not a passing one."
                ),
            )
        result.duration_ms = int((time.monotonic() - started) * 1000)
        if not result.command:
            result.command = command
        return self.add(result)

    @property
    def counts(self) -> dict[str, int]:
        counts = {str(status): 0 for status in Status}
        for result in self.results:
            counts[str(result.status)] += 1
        return counts

    @property
    def ok(self) -> bool:
        return not any(result.status in FAILING_STATUSES for result in self.results)

    def exit_code(self) -> int:
        return EXIT_OK if self.ok else EXIT_ACTIONABLE_FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "description": self.description,
            "started_at": self.started_at,
            "finished_at": utcnow_iso(),
            "host": platform.node(),
            "python": sys.version.split()[0],
            "ok": self.ok,
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def render(self) -> str:
        """Human summary: failures first, because that is what gets read."""

        width = max((len(result.name) for result in self.results), default=10)
        lines = [f"== {self.tool} ==", ""]
        order = {Status.FAIL: 0, Status.BLOCKED: 1, Status.WARN: 2, Status.PASS: 3}
        for result in sorted(self.results, key=lambda item: order[item.status]):
            lines.append(f"[{result.status:<7}] {result.name:<{width}}  {result.detail}")
            if result.command:
                lines.append(f"{'':>10}  $ {result.command}")
            if result.remedy and result.status is not Status.PASS:
                lines.append(f"{'':>10}  -> {result.remedy}")
        counts = self.counts
        lines.extend(
            [
                "",
                f"{counts['PASS']} passed, {counts['FAIL']} failed, "
                f"{counts['BLOCKED']} blocked, {counts['WARN']} warnings.",
                (
                    "RESULT: OK"
                    if self.ok
                    else "RESULT: NOT VERIFIED - blocked checks count as failures."
                ),
            ]
        )
        return "\n".join(lines)

    def emit(self, json_path: str | None = None, *, quiet: bool = False) -> int:
        if json_path:
            try:
                with open(json_path, "w", encoding="utf-8") as handle:
                    handle.write(self.to_json())
            except OSError as exc:
                self.record(
                    "report.write",
                    Status.WARN,
                    f"Could not write {json_path}: {exc}",
                    remedy="Check the path is writable, or drop --json.",
                )
        if not quiet:
            print(self.render())
        return self.exit_code()


# ---------------------------------------------------------------------------
# Small utilities the individual scripts share
# ---------------------------------------------------------------------------


@dataclass
class CommandOutput:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    missing: bool = False


def run_command(
    args: Iterable[str], *, timeout: float = 30.0, env: dict | None = None
) -> CommandOutput:
    """Run a command, reporting a missing binary as data rather than an exception."""

    argv = list(args)
    if not argv:
        return CommandOutput(False, -1, "", "empty command", missing=True)
    if shutil.which(argv[0]) is None:
        return CommandOutput(False, 127, "", f"{argv[0]}: not found on PATH", missing=True)
    try:
        completed = subprocess.run(  # noqa: S603 - argv is constructed, never a shell string
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandOutput(False, -1, "", f"timed out after {timeout}s")
    except OSError as exc:
        return CommandOutput(False, -1, "", str(exc))
    return CommandOutput(
        completed.returncode == 0, completed.returncode, completed.stdout, completed.stderr
    )


def find_repo_root(start: str) -> str:
    """Walk up from ``start`` looking for a repository marker.

    Falls back to ``start`` rather than raising: a script that cannot find the
    repo should say so in a check result, not die during import.
    """

    markers = ("pyproject.toml", "package.json", ".git", "alembic.ini")
    current = os.path.abspath(start)
    while True:
        if any(os.path.exists(os.path.join(current, marker)) for marker in markers):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(start)
        current = parent


def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def read_json(path: str) -> Any | None:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
