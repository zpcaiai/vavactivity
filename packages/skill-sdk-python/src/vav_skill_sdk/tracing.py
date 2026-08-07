"""Metadata-only tracing boundary with explicit redaction."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol

SENSITIVE_KEYS = frozenset(
    {"authorization", "cookie", "password", "secret", "token", "input", "output"}
)


def safe_trace_attributes(attributes: dict[str, Any]) -> dict[str, str | int | float | bool]:
    safe: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if key.lower() in SENSITIVE_KEYS:
            safe[key] = "[REDACTED]"
        elif isinstance(value, (str, int, float, bool)):
            safe[key] = value
    return safe


class SkillTracer(Protocol):
    def span(
        self, name: str, *, attributes: dict[str, str | int | float | bool]
    ) -> AbstractContextManager[object]: ...
