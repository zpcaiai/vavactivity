from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from vav.common.exceptions import VavError

FORBIDDEN_COMMAND_MARKERS = ("direct_sql", "set_state", "mark_paid", "fabricate", "create_consent")
SENSITIVE_KEYS = {"email", "phone", "address", "notes", "content", "evidence", "private_reflection"}


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def validate_command(command_code: str | None, capability_type: str) -> None:
    if capability_type not in {"view", "search"} and not command_code:
        raise VavError(
            "ADMIN_DOMAIN_COMMAND_REQUIRED",
            "Write capability requires a domain command.",
            status_code=422,
        )
    if command_code and any(
        marker in command_code.casefold() for marker in FORBIDDEN_COMMAND_MARKERS
    ):
        raise VavError(
            "ADMIN_UNSAFE_COMMAND", "Unsafe administration command is forbidden.", status_code=422
        )


def validate_query(
    definition: dict[str, Any], filters: dict[str, Any], sort: str, columns: list[str]
) -> None:
    allowed_filters = set(definition["filter_schema"].get("fields", []))
    allowed_sorts = set(definition["sort_schema"].get("fields", []))
    allowed_columns = set(definition["column_schema"].get("fields", []))
    if (
        not set(filters).issubset(allowed_filters)
        or sort not in allowed_sorts
        or not set(columns).issubset(allowed_columns)
    ):
        raise VavError(
            "ADMIN_QUERY_SCHEMA_VIOLATION", "Query uses unregistered fields.", status_code=422
        )


def mask_value(value: Any, rule: str) -> Any:
    if value is None or rule == "none":
        return value
    text = str(value)
    if rule == "full":
        return "***"
    if rule == "partial_email":
        local, separator, domain = text.partition("@")
        return f"{local[:1]}***@{domain}" if separator else "***"
    if rule == "partial_phone":
        return f"{text[:3]}******{text[-3:]}" if len(text) >= 8 else "***"
    if rule == "last_four":
        return f"***{text[-4:]}"
    if rule == "date_year_only":
        return text[:4]
    if rule == "hashed_reference":
        return stable_hash(text)[:16]
    if rule == "range_only":
        return "restricted-range"
    return "[REDACTED]"


def minimize(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key.casefold() not in SENSITIVE_KEYS}


def step_up_current(authenticated_at: datetime | None, maximum_age_seconds: int = 900) -> bool:
    if authenticated_at is None:
        return False
    return (datetime.now(UTC) - authenticated_at).total_seconds() <= maximum_age_seconds
