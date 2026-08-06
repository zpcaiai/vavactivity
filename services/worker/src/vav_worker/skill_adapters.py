"""Deployment-controlled Skill adapter loader for the worker process."""

from __future__ import annotations

import importlib
import json
import os
import re
from typing import Any, cast

from vav.modules.skills_platform.executor import Adapter, AdapterRegistry

REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


def configured_registry() -> AdapterRegistry:
    """Load only exact entrypoints explicitly supplied by deployment configuration."""

    raw = os.getenv("VAV_SKILL_ADAPTER_ALLOWLIST_JSON", "{}")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("VAV_SKILL_ADAPTER_ALLOWLIST_JSON must be an object")
    registry = AdapterRegistry()
    for skill_ref, configuration in sorted(parsed.items()):
        if (
            not isinstance(skill_ref, str)
            or "@" not in skill_ref
            or not isinstance(configuration, dict)
        ):
            raise ValueError("invalid Skill adapter allowlist entry")
        entrypoint = configuration.get("entrypoint")
        isolated = configuration.get("isolated", False)
        if not isinstance(entrypoint, str) or not REFERENCE.fullmatch(entrypoint):
            raise ValueError(f"invalid Skill entrypoint for {skill_ref}")
        if not isinstance(isolated, bool):
            raise ValueError(f"invalid isolation flag for {skill_ref}")
        module_name, attribute = entrypoint.split(":", 1)
        candidate: Any = getattr(importlib.import_module(module_name), attribute)
        if not callable(candidate):
            raise ValueError(f"Skill entrypoint is not callable: {entrypoint}")
        name, version = skill_ref.rsplit("@", 1)
        registry.register(name, version, cast(Adapter, candidate), isolated=isolated)
    return registry
