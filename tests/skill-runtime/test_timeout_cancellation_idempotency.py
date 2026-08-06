from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from tests.skill_support import context, registered_version
from vav_skill_runtime.registry import SkillRegistry
from vav_skill_runtime.runtime import ExecutionEngine, RuntimeFailure


@pytest.mark.asyncio
async def test_timeout_returns_safe_contract() -> None:
    registry = SkillRegistry()
    version = registered_version()
    manifest_payload = version.manifest.canonical()
    manifest_payload["spec"]["execution"]["timeoutSeconds"] = 1
    version = version.__class__(
        **{
            **version.__dict__,
            "manifest": version.manifest.__class__.model_validate(manifest_payload),
        }
    )
    registry.register(version)
    runtime = ExecutionEngine(registry)

    async def slow(_payload: dict[str, object], _context: object) -> dict[str, object]:
        await asyncio.sleep(2)
        return {"message": "late"}

    runtime.register_adapter("vav.example.echo", "1.0.0", slow)  # type: ignore[arg-type]
    with pytest.raises(RuntimeFailure) as error:
        await runtime.execute(
            installation_id=uuid4(),
            name="vav.example.echo",
            version="1.0.0",
            payload={"message": "hello"},
            context=context(),
            installation_grants=frozenset(),
            runtime_policy=frozenset(),
        )
    assert error.value.code == "SKILL_TIMEOUT"
    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_cancellation_propagates_and_records_terminal_state() -> None:
    registry = SkillRegistry()
    registry.register(registered_version())
    runtime = ExecutionEngine(registry)
    started = asyncio.Event()

    async def waits(_payload: dict[str, object], _context: object) -> dict[str, object]:
        started.set()
        await asyncio.sleep(30)
        return {"message": "late"}

    runtime.register_adapter("vav.example.echo", "1.0.0", waits)  # type: ignore[arg-type]
    execution_context = context()
    task = asyncio.create_task(
        runtime.execute(
            installation_id=uuid4(),
            name="vav.example.echo",
            version="1.0.0",
            payload={"message": "hello"},
            context=execution_context,
            installation_grants=frozenset(),
            runtime_policy=frozenset(),
        )
    )
    await started.wait()
    await runtime.cancel(execution_context.execution_id)
    with pytest.raises(RuntimeFailure) as error:
        await task
    assert error.value.code == "SKILL_CANCELLED"
    assert runtime.record(execution_context.execution_id).status == "cancelled"


@pytest.mark.asyncio
async def test_idempotency_cache_is_scoped_to_input_and_authority() -> None:
    version = registered_version()
    payload = version.manifest.canonical()
    payload["spec"]["execution"]["idempotency"] = "required"
    version = version.__class__(
        **{
            **version.__dict__,
            "manifest": version.manifest.__class__.model_validate(payload),
        }
    )
    registry = SkillRegistry()
    registry.register(version)
    runtime = ExecutionEngine(registry)
    calls = 0

    async def counted(data: dict[str, object], _context: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"message": data["message"]}

    runtime.register_adapter("vav.example.echo", "1.0.0", counted)  # type: ignore[arg-type]
    installation_id = uuid4()
    for _ in range(2):
        await runtime.execute(
            installation_id=installation_id,
            name="vav.example.echo",
            version="1.0.0",
            payload={"message": "same"},
            context=context(idempotency_key="same-request-key"),
            installation_grants=frozenset(),
            runtime_policy=frozenset(),
        )
    assert calls == 1
