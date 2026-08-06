from __future__ import annotations

from uuid import uuid4

import pytest

from tests.skill_support import context, registered_version
from vav_skill_runtime.registry import SkillRegistry
from vav_skill_runtime.runtime import ExecutionEngine, RuntimeFailure


def engine() -> ExecutionEngine:
    registry = SkillRegistry()
    version = registered_version()
    registry.register(version)
    runtime = ExecutionEngine(registry)

    async def echo(payload: dict[str, object], _context: object) -> dict[str, object]:
        return {"message": payload["message"]}

    runtime.register_adapter("vav.example.echo", "1.0.0", echo)  # type: ignore[arg-type]
    return runtime


@pytest.mark.asyncio
async def test_execution_validates_and_pins_version() -> None:
    runtime = engine()
    record, output = await runtime.execute(
        installation_id=uuid4(),
        name="vav.example.echo",
        version="1.0.0",
        payload={"message": "hello"},
        context=context(),
        installation_grants=frozenset(),
        runtime_policy=frozenset(),
    )
    assert output == {"message": "hello"}
    assert record.status == "succeeded"
    assert record.skill_version == "1.0.0"
    assert record.input_hash and record.output_hash


@pytest.mark.asyncio
async def test_invalid_input_never_reaches_adapter() -> None:
    runtime = engine()
    with pytest.raises(RuntimeFailure, match="input") as error:
        await runtime.execute(
            installation_id=uuid4(),
            name="vav.example.echo",
            version="1.0.0",
            payload={"message": "hello", "injected": True},
            context=context(),
            installation_grants=frozenset(),
            runtime_policy=frozenset(),
        )
    assert error.value.code == "SKILL_INPUT_INVALID"


@pytest.mark.asyncio
async def test_invalid_output_is_not_delivered() -> None:
    runtime = engine()

    async def invalid(
        _payload: dict[str, object], _context: object
    ) -> dict[str, object]:
        return {"unexpected": "secret"}

    runtime.register_adapter("vav.example.echo", "1.0.0", invalid)  # type: ignore[arg-type]
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
    assert error.value.code == "SKILL_OUTPUT_INVALID"
