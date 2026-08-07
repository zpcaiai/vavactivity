"""Deny-by-default permission calculations shared by SDK and runtime."""

import re
from collections.abc import Iterable

PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,5}$")
FORBIDDEN_WILDCARDS = {"*", "admin.*", "secret.*", "database.*", "all_user_data.*"}


def validate_permissions(permissions: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(permissions)
    invalid = sorted(
        permission
        for permission in normalized
        if permission in FORBIDDEN_WILDCARDS
        or "*" in permission
        or PERMISSION_PATTERN.fullmatch(permission) is None
    )
    if invalid:
        raise ValueError(f"unregistered or overbroad permission identifiers: {invalid}")
    return normalized


def effective_permissions(
    caller_grants: Iterable[str],
    installation_grants: Iterable[str],
    manifest_requests: Iterable[str],
    runtime_policy: Iterable[str],
) -> frozenset[str]:
    """Authority only narrows as it crosses each boundary."""
    layers = tuple(
        validate_permissions(layer)
        for layer in (caller_grants, installation_grants, manifest_requests, runtime_policy)
    )
    return frozenset.intersection(*layers)
