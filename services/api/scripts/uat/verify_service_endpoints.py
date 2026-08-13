#!/usr/bin/env python3
"""OPS-003: probe every service the stack needs and report honestly.

Covers the eight endpoints a working local or CI stack exposes: the user app
(5173), the admin app (5174), the API (8000), the API's OpenAPI document,
Mailpit (8025), the MinIO console (9001), PostgreSQL (5432) and Redis (6379).

Two rules this script is built around:

* **An unreachable service is BLOCKED, never skipped.** A probe that could not
  run is not a probe that passed. Every result carries a status, a timestamp and
  the exact command a human can paste to reproduce it.
* **HTTP probes only report what they observed.** A 200 means 200; a 404 on
  ``/health`` is reported as a 404 with the body's first line, not translated
  into "service down" or "service up" by guesswork.

Exit codes: ``0`` everything reachable, ``1`` anything failed or blocked.

Usage::

    python3 batch_p4/scripts/verify_service_endpoints.py
    python3 batch_p4/scripts/verify_service_endpoints.py --host 127.0.0.1 --json probes.json
    python3 batch_p4/scripts/verify_service_endpoints.py --only api,postgres
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import Report, Status, utcnow_iso  # noqa: E402


@dataclass(frozen=True)
class Probe:
    """One thing to check, and what to say when it is not there."""

    key: str
    label: str
    port: int
    kind: str  # "http" or "tcp"
    path: str = "/"
    #: HTTP statuses that mean "this service is up and answering". A dev server
    #: answering 404 on ``/`` is still up, which is why this is per-probe.
    acceptable_status: tuple[int, ...] = (200,)
    remedy: str = ""
    expect_json: bool = False


PROBES: tuple[Probe, ...] = (
    Probe(
        "user_app",
        "User app (Vite dev server)",
        5173,
        "http",
        "/",
        acceptable_status=(200, 304, 404),
        remedy="pnpm --filter user dev  # then re-run",
    ),
    Probe(
        "admin_app",
        "Admin app (Vite dev server)",
        5174,
        "http",
        "/",
        acceptable_status=(200, 304, 404),
        remedy="pnpm --filter admin dev  # then re-run",
    ),
    Probe(
        "api_health",
        "API health endpoint",
        8000,
        "http",
        "/health",
        remedy="uvicorn vav.api.main:app --reload --port 8000  # then re-run",
    ),
    Probe(
        "api_openapi",
        "API OpenAPI document",
        8000,
        "http",
        "/openapi.json",
        expect_json=True,
        remedy="The API is answering but not serving its schema; check the FastAPI app factory.",
    ),
    Probe(
        "mailpit",
        "Mailpit web UI",
        8025,
        "http",
        "/",
        acceptable_status=(200, 304),
        remedy="docker compose up -d mailpit",
    ),
    Probe(
        "minio_console",
        "MinIO console",
        9001,
        "http",
        "/",
        acceptable_status=(200, 307, 403),
        remedy="docker compose up -d minio",
    ),
    Probe(
        "postgres",
        "PostgreSQL",
        5432,
        "tcp",
        remedy=(
            "docker compose up -d postgres  # a TCP probe cannot authenticate; "
            "see verify_migrations.py"
        ),
    ),
    Probe(
        "redis",
        "Redis",
        6379,
        "tcp",
        remedy="docker compose up -d redis",
    ),
)


def tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, str]:
    """Open a socket and close it. Reachability only - no protocol handshake.

    Deliberately does not speak the Postgres or Redis protocol: a TCP probe that
    pretends to have verified authentication would be worse than no probe.
    ``verify_migrations.py`` is what actually talks to the database.
    """

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"TCP {host}:{port} accepted a connection."
    except TimeoutError:
        return False, f"TCP {host}:{port} timed out after {timeout}s."
    except ConnectionRefusedError:
        return False, f"TCP {host}:{port} refused the connection - nothing is listening."
    except socket.gaierror as exc:
        return False, f"Could not resolve {host}: {exc}."
    except OSError as exc:
        return False, f"TCP {host}:{port} failed: {exc}."


def http_probe(url: str, timeout: float) -> tuple[int | None, str, str]:
    """Fetch a URL. Returns ``(status, first line of body, error)``."""

    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "vav-verify/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed http(s) URL
            body = response.read(2048).decode("utf-8", errors="replace")
            return response.status, body.strip().splitlines()[0][:200] if body.strip() else "", ""
    except urllib.error.HTTPError as exc:
        body = exc.read(512).decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body.strip().splitlines()[0][:200] if body.strip() else "", ""
    except urllib.error.URLError as exc:
        return None, "", str(exc.reason)
    except TimeoutError:
        return None, "", f"timed out after {timeout}s"
    except OSError as exc:
        return None, "", str(exc)


def run_probe(report: Report, probe: Probe, *, host: str, timeout: float) -> None:
    if probe.kind == "tcp":
        command = f"nc -z {host} {probe.port}"
        ok, detail = tcp_probe(host, probe.port, timeout)
        report.record(
            probe.key,
            Status.PASS if ok else Status.BLOCKED,
            f"{probe.label}: {detail}",
            command=command,
            remedy="" if ok else probe.remedy,
            port=probe.port,
            probe_kind="tcp",
            observed_at=utcnow_iso(),
        )
        return

    url = f"http://{host}:{probe.port}{probe.path}"
    command = f"curl -sS -o /dev/null -w '%{{http_code}}' {url}"
    status, first_line, error = http_probe(url, timeout)
    if status is None:
        report.record(
            probe.key,
            Status.BLOCKED,
            f"{probe.label}: no HTTP response from {url} ({error}).",
            command=command,
            remedy=probe.remedy,
            port=probe.port,
            probe_kind="http",
            url=url,
            observed_at=utcnow_iso(),
        )
        return
    if status not in probe.acceptable_status:
        report.record(
            probe.key,
            Status.FAIL,
            f"{probe.label}: {url} answered HTTP {status} "
            f"(expected {', '.join(str(code) for code in probe.acceptable_status)}). {first_line}",
            command=command,
            remedy=probe.remedy,
            port=probe.port,
            probe_kind="http",
            http_status=status,
            url=url,
            observed_at=utcnow_iso(),
        )
        return
    if probe.expect_json and not first_line.lstrip().startswith(("{", "[")):
        report.record(
            probe.key,
            Status.FAIL,
            f"{probe.label}: {url} answered HTTP {status} but the body is not JSON: {first_line!r}",
            command=command,
            remedy=probe.remedy,
            port=probe.port,
            probe_kind="http",
            http_status=status,
            url=url,
            observed_at=utcnow_iso(),
        )
        return
    report.record(
        probe.key,
        Status.PASS,
        f"{probe.label}: HTTP {status} from {url}.",
        command=command,
        port=probe.port,
        probe_kind="http",
        http_status=status,
        url=url,
        observed_at=utcnow_iso(),
    )


def select_probes(only: str | None) -> tuple[list[Probe], list[str]]:
    """Filter by key, reporting names that matched nothing rather than ignoring them."""

    if not only:
        return list(PROBES), []
    wanted = [item.strip() for item in only.split(",") if item.strip()]
    known = {probe.key for probe in PROBES}
    unknown = [name for name in wanted if name not in known]
    return [probe for probe in PROBES if probe.key in wanted], unknown


def build_report(*, host: str, timeout: float, only: str | None = None) -> Report:
    report = Report(
        "verify_service_endpoints",
        (
            "OPS-003 service reachability: user app, admin app, API, OpenAPI, "
            "Mailpit, MinIO, Postgres, Redis."
        ),
    )
    probes, unknown = select_probes(only)
    for name in unknown:
        report.record(
            f"selection.{name}",
            Status.FAIL,
            f"--only named '{name}', which is not a known probe.",
            remedy="Valid keys: " + ", ".join(probe.key for probe in PROBES),
        )
    for probe in probes:
        report.guard(
            probe.key,
            f"probe {probe.kind} {host}:{probe.port}{probe.path if probe.kind == 'http' else ''}",
            lambda probe=probe: _guarded(report, probe, host, timeout),
        )
    return report


def _guarded(report: Report, probe: Probe, host: str, timeout: float):  # noqa: ANN202
    """Run a probe through ``Report.guard`` while keeping its own record shape.

    ``run_probe`` appends its own result; this pops it back out so ``guard`` can
    attach the duration and re-add it exactly once.
    """

    before = len(report.results)
    run_probe(report, probe, host=host, timeout=timeout)
    return report.results.pop(before)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default=os.environ.get("VAV_PROBE_HOST", "127.0.0.1"))
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-probe timeout in seconds.")
    parser.add_argument("--only", default=None, help="Comma-separated probe keys.")
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(host=args.host, timeout=args.timeout, only=args.only)
    return report.emit(args.json_path, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
