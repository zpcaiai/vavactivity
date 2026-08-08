"""Fail-closed helpers for command and JUnit release evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

EvidenceStatus = Literal["PASS", "FAIL", "NOT_RUN"]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for an immutable evidence artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_evidence(path: Path) -> dict[str, Any]:
    """Load a command status sidecar, treating absence as ``NOT_RUN``."""

    if not path.is_file():
        return {
            "status": "NOT_RUN",
            "reason": "command execution evidence is missing",
            "artifact": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "FAIL",
            "reason": "invalid command status evidence",
            "artifact": str(path),
        }
    if not isinstance(payload, dict) or payload.get("status") not in {
        "PASS",
        "FAIL",
        "NOT_RUN",
    }:
        return {
            "status": "FAIL",
            "reason": "invalid command status evidence",
            "artifact": str(path),
        }
    return {
        **payload,
        "artifact": str(path),
        "checksum_sha256": sha256_file(path),
    }


def junit_evidence(junit_path: Path, command_status_path: Path) -> dict[str, Any]:
    """Evaluate a JUnit report together with its command execution record.

    A report without the status sidecar emitted by ``run_if_available.sh`` is
    deliberately treated as ``NOT_RUN``. This prevents stale XML from a prior
    checkout or environment from satisfying a release gate.
    """

    command = command_evidence(command_status_path)
    if command["status"] == "NOT_RUN":
        return {
            "status": "NOT_RUN",
            "reason": command.get("reason", "environment dependency unavailable"),
            "artifact": str(junit_path),
            "command": command,
        }
    if command["status"] == "FAIL":
        return {
            "status": "FAIL",
            "reason": command.get("reason", "test command failed"),
            "artifact": str(junit_path),
            "command": command,
        }
    if not junit_path.is_file():
        return {
            "status": "FAIL",
            "reason": "test command passed without producing JUnit evidence",
            "artifact": str(junit_path),
            "command": command,
        }

    try:
        root = ElementTree.parse(junit_path).getroot()
        if root is None:
            raise ValueError("JUnit document has no root element")
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        if not suites:
            raise ValueError("JUnit document has no test suites")
        counts = {
            field: sum(int(float(suite.attrib.get(field, "0"))) for suite in suites)
            for field in ("tests", "failures", "errors", "skipped")
        }
    except (DefusedXmlException, ElementTree.ParseError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "reason": f"invalid JUnit evidence: {exc}",
            "artifact": str(junit_path),
            "command": command,
        }

    passed = counts["tests"] > 0 and counts["failures"] == 0 and counts["errors"] == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "reason": "all tests passed" if passed else "JUnit contains failures or errors",
        "artifact": str(junit_path),
        "checksum_sha256": sha256_file(junit_path),
        **counts,
        "command": command,
    }


def combined_status(items: list[dict[str, Any]]) -> EvidenceStatus:
    """Combine evidence without converting missing execution into a pass."""

    statuses = {str(item.get("status", "FAIL")) for item in items}
    if "FAIL" in statuses:
        return "FAIL"
    if "NOT_RUN" in statuses:
        return "NOT_RUN"
    return "PASS"
