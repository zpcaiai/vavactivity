from __future__ import annotations

from uuid import uuid4

import pytest

from tests.skill_support import context, registered_version
from vav_skill_runtime.registry import SkillRegistry
from vav_skill_runtime.runtime import ExecutionEngine, RuntimeFailure


@pytest.mark.asyncio
async def test_skill_cannot_elevate_caller_or_installation_permissions() -> None:
    version = registered_version()
    payload = version.manifest.canonical()
    payload["spec"]["permissions"] = ["profiles.self.read"]
    version = version.__class__(
        **{
            **version.__dict__,
            "manifest": version.manifest.__class__.model_validate(payload),
        }
    )
    registry = SkillRegistry()
    registry.register(version)
    runtime = ExecutionEngine(registry)
    invoked = False

    async def adapter(data: dict[str, object], _context: object) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return data

    runtime.register_adapter("vav.example.echo", "1.0.0", adapter)
    with pytest.raises(RuntimeFailure) as error:
        await runtime.execute(
            installation_id=uuid4(),
            name="vav.example.echo",
            version="1.0.0",
            payload={"message": "hello"},
            context=context(permissions=frozenset({"profiles.self.read"})),
            installation_grants=frozenset(),
            runtime_policy=frozenset({"profiles.self.read"}),
        )
    assert error.value.code == "SKILL_PERMISSION_DENIED"
    assert invoked is False
