"""Version-pinned Skill execution with validation, authority, timeout, and idempotency."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vav_skill_sdk.context import SkillContext
from vav_skill_sdk.permissions import effective_permissions
from vav_skill_runtime.registry import SkillRegistry

Adapter = Callable[[dict[str, Any], SkillContext], Awaitable[dict[str, Any]]]

ExecutionStatus = Literal[
    "created",
    "validating",
    "authorizing",
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "timed_out",
]


class RuntimeFailure(ValueError):
    def __init__(self, code: str, message_safe: str, *, retryable: bool = False) -> None:
        super().__init__(message_safe)
        self.code = code
        self.message_safe = message_safe
        self.retryable = retryable


@dataclass
class ExecutionRecord:
    execution_id: UUID
    installation_id: UUID
    skill_name: str
    skill_version: str
    actor_user_id: UUID | None
    status: ExecutionStatus = "created"
    input_hash: str = ""
    output_hash: str | None = None
    effective_permissions: frozenset[str] = frozenset()
    error_code: str | None = None
    error_message_safe: str | None = None
    trace_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class ExecutionEngine:
    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._adapters: dict[tuple[str, str], Adapter] = {}
        self._records: dict[UUID, ExecutionRecord] = {}
        self._tasks: dict[UUID, asyncio.Task[dict[str, Any]]] = {}
        self._idempotency: dict[tuple[str, ...], dict[str, Any]] = {}
        self._locks: dict[tuple[str, str], asyncio.Semaphore] = {}

    def register_adapter(self, name: str, version: str, adapter: Adapter) -> None:
        self._adapters[(name, version)] = adapter

    def record(self, execution_id: UUID) -> ExecutionRecord:
        return self._records[execution_id]

    async def cancel(self, execution_id: UUID) -> None:
        record = self._records.get(execution_id)
        task = self._tasks.get(execution_id)
        if record is None or task is None or task.done():
            raise RuntimeFailure("EXECUTION_NOT_RUNNING", "That execution is not running.")
        record.status = "cancel_requested"
        task.cancel()

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def execute(
        self,
        *,
        installation_id: UUID,
        name: str,
        version: str,
        payload: dict[str, Any],
        context: SkillContext,
        installation_grants: frozenset[str],
        runtime_policy: frozenset[str],
    ) -> tuple[ExecutionRecord, dict[str, Any]]:
        registered = self._registry.get(name, version)
        manifest = registered.manifest
        requested = frozenset(manifest.spec.permissions)
        granted = effective_permissions(
            context.permissions, installation_grants, requested, runtime_policy
        )
        if granted != requested:
            missing = sorted(requested - granted)
            raise RuntimeFailure(
                "SKILL_PERMISSION_DENIED", f"Required Skill permissions were not granted: {missing}"
            )

        execution_id = context.execution_id
        record = ExecutionRecord(
            execution_id=execution_id,
            installation_id=installation_id,
            skill_name=name,
            skill_version=version,
            actor_user_id=context.actor_user_id,
            trace_id=context.trace_id,
            effective_permissions=granted,
        )
        self._records[execution_id] = record
        record.status = "validating"
        errors = sorted(
            Draft202012Validator(registered.input_schema).iter_errors(payload),
            key=lambda item: list(item.path),
        )
        if errors:
            record.status = "failed"
            record.error_code = "SKILL_INPUT_INVALID"
            record.error_message_safe = errors[0].message
            record.completed_at = datetime.now(UTC)
            raise RuntimeFailure("SKILL_INPUT_INVALID", "Skill input did not match its schema.")
        record.input_hash = self._payload_hash(payload)

        idempotency_key = context.idempotency_key
        requires_idempotency = manifest.spec.execution.idempotency != "not_required"
        if requires_idempotency and not idempotency_key:
            raise RuntimeFailure(
                "IDEMPOTENCY_KEY_REQUIRED", "This Skill requires an idempotency key."
            )
        cache_key = (
            str(installation_id),
            name,
            version,
            idempotency_key or "",
            str(context.actor_user_id or context.principal.principal_id),
            hashlib.sha256("\n".join(sorted(granted)).encode()).hexdigest(),
            record.input_hash,
        )
        if idempotency_key and cache_key in self._idempotency:
            record.status = "succeeded"
            output = self._idempotency[cache_key]
            record.output_hash = self._payload_hash(output)
            record.completed_at = datetime.now(UTC)
            return record, output

        adapter = self._adapters.get((name, version))
        if adapter is None:
            raise RuntimeFailure("SKILL_RUNTIME_UNAVAILABLE", "The Skill runtime is unavailable.")
        semaphore = self._locks.setdefault(
            (name, version), asyncio.Semaphore(manifest.spec.execution.concurrency_limit)
        )

        async def invoke() -> dict[str, Any]:
            async with semaphore:
                return await adapter(payload, context)

        record.status = "running"
        task = asyncio.create_task(invoke(), name=f"skill:{name}@{version}:{execution_id}")
        self._tasks[execution_id] = task
        try:
            output = await asyncio.wait_for(
                task, timeout=float(manifest.spec.execution.timeout_seconds)
            )
        except TimeoutError as exc:
            record.status = "timed_out"
            record.error_code = "SKILL_TIMEOUT"
            record.error_message_safe = "The Skill exceeded its execution deadline."
            record.completed_at = datetime.now(UTC)
            raise RuntimeFailure(
                "SKILL_TIMEOUT", record.error_message_safe, retryable=True
            ) from exc
        except asyncio.CancelledError as exc:
            record.status = "cancelled"
            record.error_code = "SKILL_CANCELLED"
            record.error_message_safe = "The Skill execution was cancelled."
            record.completed_at = datetime.now(UTC)
            raise RuntimeFailure("SKILL_CANCELLED", record.error_message_safe) from exc
        except RuntimeFailure:
            raise
        except Exception as exc:
            record.status = "failed"
            record.error_code = "SKILL_INTERNAL_ERROR"
            record.error_message_safe = "The Skill could not complete safely."
            record.completed_at = datetime.now(UTC)
            raise RuntimeFailure("SKILL_INTERNAL_ERROR", record.error_message_safe) from exc
        finally:
            self._tasks.pop(execution_id, None)

        output_errors = sorted(
            Draft202012Validator(registered.output_schema).iter_errors(output),
            key=lambda item: list(item.path),
        )
        if output_errors:
            record.status = "failed"
            record.error_code = "SKILL_OUTPUT_INVALID"
            record.error_message_safe = "The Skill produced an invalid response."
            record.completed_at = datetime.now(UTC)
            raise RuntimeFailure("SKILL_OUTPUT_INVALID", record.error_message_safe)
        record.status = "succeeded"
        record.output_hash = self._payload_hash(output)
        record.completed_at = datetime.now(UTC)
        if idempotency_key:
            self._idempotency[cache_key] = output
        return record, output
