#!/usr/bin/env python3
"""Safe unauthenticated DAST, API fuzzing, and penetration-regression checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEAK_MARKERS = (
    "traceback (most recent call last)",
    "sqlalchemy.exc",
    "-----begin private key-----",
    "/.dev-secrets/",
    "/app/services/",
)
FUZZ_VALUES = (
    "' OR '1'='1",
    "<script>alert(1)</script>",
    "../../../../etc/passwd",
    "${jndi:ldap://127.0.0.1/a}",
    "%00%00%ED%A0%80",
    "A" * 2048,
)


class Scanner:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.results: list[dict[str, Any]] = []

    def request(
        self,
        name: str,
        category: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        protected: bool = False,
        predicate: str = "no_5xx_or_leak",
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(
            url, data=body, headers=headers or {}, method=method
        )
        started = time.monotonic()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.status
                response_headers = dict(response.headers.items())
                payload = response.read(8192).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            response_headers = dict(exc.headers.items())
            payload = exc.read(8192).decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as exc:
            result = {
                "name": name,
                "category": category,
                "method": method,
                "path": path,
                "status": None,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "passed": False,
                "findings": [f"request failed: {exc}"],
            }
            self.results.append(result)
            return result

        lowered = payload.lower()
        findings = [
            f"response leaks marker: {marker}"
            for marker in LEAK_MARKERS
            if marker in lowered
        ]
        if status >= 500:
            findings.append(f"server returned {status}")
        if protected and status not in {401, 403, 404, 405, 422, 429}:
            findings.append(f"protected operation returned unexpected status {status}")
        if predicate == "trace_rejected" and status not in {400, 405, 501}:
            findings.append(f"TRACE was not rejected: {status}")
        result = {
            "name": name,
            "category": category,
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "passed": not findings,
            "findings": findings,
            "headers": {key.lower(): value for key, value in response_headers.items()},
        }
        self.results.append(result)
        return result


def security_headers(scanner: Scanner) -> None:
    result = scanner.request("security headers", "dast", "GET", "/api/v1/health/ready")
    required = {"x-content-type-options": "nosniff", "x-frame-options": "DENY"}
    for header, expected in required.items():
        if result.get("headers", {}).get(header, "").lower() != expected.lower():
            result["passed"] = False
            result["findings"].append(f"missing or invalid {header}")


def cors_check(scanner: Scanner) -> None:
    result = scanner.request(
        "cross-origin credential rejection",
        "dast",
        "OPTIONS",
        "/api/v1/admin/auth/me",
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    headers = result.get("headers", {})
    if (
        headers.get("access-control-allow-origin") == "https://attacker.invalid"
        and headers.get("access-control-allow-credentials", "").lower() == "true"
    ):
        result["passed"] = False
        result["findings"].append("untrusted origin received credentialed CORS access")


def targeted_regressions(scanner: Scanner) -> None:
    scanner.request(
        "malformed bearer token",
        "penetration-regression",
        "GET",
        "/api/v1/admin/auth/me",
        headers={"Authorization": "Bearer not.a.jwt"},
        protected=True,
    )
    scanner.request(
        "spoofed administrator headers",
        "penetration-regression",
        "GET",
        "/api/v1/admin/users",
        headers={
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Admin": "true",
            "X-Forwarded-User": "admin",
            "X-Original-URL": "/api/v1/admin/users",
        },
        protected=True,
    )
    scanner.request(
        "encoded traversal",
        "penetration-regression",
        "GET",
        "/api/v1/public/catalog/%2e%2e/%2e%2e/admin/users",
    )
    scanner.request(
        "TRACE method rejection",
        "dast",
        "TRACE",
        "/api/v1/health/ready",
        predicate="trace_rejected",
    )


def fuzz_openapi(scanner: Scanner, schema: dict[str, Any], max_cases: int) -> None:
    candidates: list[tuple[str, str, bool]] = []
    methods = {"get", "post", "put", "patch", "delete"}
    for path, path_item in sorted(schema.get("paths", {}).items()):
        if "{" in path:
            continue
        for method in methods.intersection(path_item):
            protected = "/admin/" in path and path != "/api/v1/admin/auth/login"
            safe_public_read = method == "get" and "/public/" in path
            if protected or safe_public_read:
                candidates.append((method.upper(), path, protected))
    random.Random(20260809).shuffle(candidates)
    for index, (method, path, protected) in enumerate(candidates[:max_cases]):
        fuzz = FUZZ_VALUES[index % len(FUZZ_VALUES)]
        headers = {
            "Authorization": "Bearer fuzz.invalid.token",
            "Content-Type": "application/json",
            "X-HTTP-Method-Override": "DELETE",
        }
        if method == "GET":
            separator = "&" if "?" in path else "?"
            path = (
                f"{path}{separator}{urllib.parse.urlencode({'q': fuzz, 'limit': '-1'})}"
            )
            body = None
        else:
            body = json.dumps({"fuzz": fuzz, "__proto__": {"admin": True}}).encode()
        scanner.request(
            f"openapi-{index + 1}",
            "api-fuzz",
            method,
            path,
            headers=headers,
            body=body,
            protected=protected,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--openapi", type=Path, default=Path("packages/contracts/openapi.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("build/security/blackbox-security.json")
    )
    parser.add_argument("--scope", default="local_compose")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-fuzz-cases", type=int, default=100)
    args = parser.parse_args()

    schema_bytes = args.openapi.read_bytes()
    schema = json.loads(schema_bytes)
    scanner = Scanner(args.base_url, args.timeout)
    security_headers(scanner)
    cors_check(scanner)
    targeted_regressions(scanner)
    fuzz_openapi(scanner, schema, args.max_fuzz_cases)

    failures = [result for result in scanner.results if not result["passed"]]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    clean = not subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    categories = {
        category: {
            "executed": sum(item["category"] == category for item in scanner.results),
            "failed": sum(
                item["category"] == category and not item["passed"]
                for item in scanner.results
            ),
        }
        for category in ("dast", "api-fuzz", "penetration-regression")
    }
    report = {
        "status": "LOCAL_PASS" if not failures else "FAIL",
        "evidence_scope": args.scope,
        "production_certification": False,
        "independent_penetration_test": "NOT_EVALUATED",
        "completed_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "worktree_clean": clean,
        "openapi_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "request_count": len(scanner.results),
        "categories": categories,
        "failures": failures,
        "results": scanner.results,
        "note": (
            "This is a safe local black-box regression suite, not an independent "
            "production penetration test."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "request_count", "categories", "failures")
            },
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
