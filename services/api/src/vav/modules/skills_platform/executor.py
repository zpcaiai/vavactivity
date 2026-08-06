# ruff: noqa: E501

"""Persistent, fail-closed Skill execution worker.

Only adapters explicitly installed into the worker image and listed in the deployment
allowlist can run. Third-party code is never dynamically loaded into the API process.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.modules.privacy.crypto import decrypt_private, encrypt_private

Adapter = Callable[[dict[str, Any], "ExecutionContext"], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: UUID
    actor_user_id: UUID | None
    installation_id: UUID
    permissions: frozenset[str]
    trace_id: str
    deadline: datetime


@dataclass(frozen=True)
class AdapterRegistration:
    adapter: Adapter
    isolated: bool


class ExecutionRejected(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class AdapterRegistry:
    """Exact name/version adapter allowlist, populated by the worker deployment."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], AdapterRegistration] = {}

    def register(
        self,
        skill_name: str,
        version: str,
        adapter: Adapter,
        *,
        isolated: bool = False,
    ) -> None:
        key = (skill_name, version)
        if key in self._adapters:
            raise ValueError(f"Skill adapter already registered: {skill_name}@{version}")
        self._adapters[key] = AdapterRegistration(adapter=adapter, isolated=isolated)

    def resolve(self, skill_name: str, version: str) -> AdapterRegistration:
        try:
            return self._adapters[(skill_name, version)]
        except KeyError as exc:
            raise ExecutionRejected(
                "SKILL_RUNTIME_UNAVAILABLE", "The approved Skill runtime is unavailable."
            ) from exc


def _hash(payload: object) -> str:
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(value.encode()).hexdigest()


def _validate(schema: object, payload: object, *, code: str, message: str) -> None:
    if not isinstance(schema, dict):
        raise ExecutionRejected("SKILL_SCHEMA_UNAVAILABLE", "Skill contracts are unavailable.")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    if errors:
        raise ExecutionRejected(code, message)


def _encrypted_payload(value: object) -> dict[str, str]:
    return {"ciphertext": encrypt_private(value)}


async def _finish(
    session: AsyncSession,
    execution_id: UUID,
    *,
    status: str,
    output: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    await session.execute(
        text(
            "UPDATE skill_executions SET status=:status,output_encrypted=CAST(:output AS jsonb),"
            "output_hash=:output_hash,error_code=:error,error_message_safe=:message,completed_at=now(),updated_at=now() "
            "WHERE id=:id AND status='running'"
        ),
        {
            "id": execution_id,
            "status": status,
            "output": json.dumps(_encrypted_payload(output)) if output is not None else None,
            "output_hash": _hash(output) if output is not None else None,
            "error": error_code,
            "message": error_message,
        },
    )
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (NULL,'system',:action,'skill_execution',:id,CAST(:context AS jsonb),now())"
        ),
        {
            "action": f"skill.execution.{status}",
            "id": str(execution_id),
            "context": json.dumps({"error_code": error_code} if error_code else {}),
        },
    )
    await session.commit()


async def process_next_execution(session: AsyncSession, registry: AdapterRegistry) -> bool:
    """Claim and execute one queued record. Returns False when no work is available."""

    row = (
        (
            await session.execute(
                text(
                    "SELECT e.id,e.installation_id,e.actor_user_id,e.input_encrypted,e.permission_snapshot,"
                    "e.timeout_at,e.trace_id,e.status,v.semantic_version,v.manifest,v.input_schema,v.output_schema,"
                    "v.signature_status,v.security_status,v.compatibility_status,v.revoked_at,s.skill_name,s.trust_level "
                    "FROM skill_executions e JOIN registered_skill_versions v ON v.id=e.skill_version_id "
                    "JOIN registered_skills s ON s.id=v.registered_skill_id "
                    "JOIN skill_installations i ON i.id=e.installation_id "
                    "WHERE e.status IN ('queued','cancel_requested') AND i.status='active' "
                    "ORDER BY e.created_at FOR UPDATE OF e SKIP LOCKED LIMIT 1"
                )
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return False
    execution_id = row["id"]
    if row["status"] == "cancel_requested":
        await session.execute(
            text(
                "UPDATE skill_executions SET status='cancelled',completed_at=now(),updated_at=now() WHERE id=:id"
            ),
            {"id": execution_id},
        )
        await session.commit()
        return True
    if row["timeout_at"] <= datetime.now(UTC):
        await session.execute(
            text(
                "UPDATE skill_executions SET status='timed_out',error_code='SKILL_DEADLINE_EXCEEDED',"
                "error_message_safe='The Skill execution deadline expired.',completed_at=now(),updated_at=now() WHERE id=:id"
            ),
            {"id": execution_id},
        )
        await session.commit()
        return True
    await session.execute(
        text(
            "UPDATE skill_executions SET status='running',started_at=now(),updated_at=now() WHERE id=:id AND status='queued'"
        ),
        {"id": execution_id},
    )
    await session.commit()

    try:
        if (
            row["signature_status"] != "verified"
            or row["security_status"] not in {"passed", "passed_with_warnings"}
            or row["compatibility_status"] != "compatible"
            or row["revoked_at"] is not None
            or row["trust_level"] in {"unverified", "quarantined", "revoked"}
        ):
            raise ExecutionRejected(
                "SKILL_EXECUTION_GATE_FAILED",
                "The Skill no longer passes execution security gates.",
            )
        encrypted = row["input_encrypted"]
        if not isinstance(encrypted, dict) or not isinstance(encrypted.get("ciphertext"), str):
            raise ExecutionRejected(
                "SKILL_INPUT_ENCRYPTION_INVALID", "The encrypted Skill input is unavailable."
            )
        payload = decrypt_private(encrypted["ciphertext"])
        if not isinstance(payload, dict):
            raise ExecutionRejected("SKILL_INPUT_INVALID", "Skill input must be an object.")
        _validate(
            row["input_schema"],
            payload,
            code="SKILL_INPUT_INVALID",
            message="Skill input did not match its contract.",
        )
        manifest = row["manifest"]
        requested = frozenset(manifest.get("spec", {}).get("permissions", []))
        permissions = frozenset(row["permission_snapshot"])
        if not requested.issubset(permissions):
            raise ExecutionRejected(
                "SKILL_PERMISSION_DENIED", "The Skill does not have all declared permissions."
            )
        runtime = manifest.get("spec", {}).get("runtime")
        registration = registry.resolve(row["skill_name"], row["semantic_version"])
        if runtime == "sandbox" and not registration.isolated:
            raise ExecutionRejected(
                "SKILL_SANDBOX_REQUIRED", "This Skill requires an isolated runtime."
            )
        if (
            row["trust_level"] not in {"builtin_trusted", "official_signed"}
            and not registration.isolated
        ):
            raise ExecutionRejected(
                "SKILL_ISOLATION_REQUIRED", "Third-party Skills require an isolated runtime."
            )
        context = ExecutionContext(
            execution_id=execution_id,
            actor_user_id=row["actor_user_id"],
            installation_id=row["installation_id"],
            permissions=permissions,
            trace_id=row["trace_id"] or "",
            deadline=row["timeout_at"],
        )
        timeout = min(
            float(manifest.get("spec", {}).get("execution", {}).get("timeoutSeconds", 30)),
            max(0.001, (row["timeout_at"] - datetime.now(UTC)).total_seconds()),
        )
        async with asyncio.timeout(timeout):
            output = registration.adapter(payload, context)
            if not inspect.isawaitable(output):
                raise ExecutionRejected(
                    "SKILL_ADAPTER_INVALID", "The Skill adapter violated the runtime contract."
                )
            result = await output
        if not isinstance(result, dict):
            raise ExecutionRejected("SKILL_OUTPUT_INVALID", "Skill output must be an object.")
        _validate(
            row["output_schema"],
            result,
            code="SKILL_OUTPUT_INVALID",
            message="Skill output did not match its contract.",
        )
        await _finish(session, execution_id, status="succeeded", output=result)
    except TimeoutError:
        await _finish(
            session,
            execution_id,
            status="timed_out",
            error_code="SKILL_TIMEOUT",
            error_message="The Skill exceeded its execution deadline.",
        )
    except ExecutionRejected as exc:
        await _finish(
            session,
            execution_id,
            status="failed",
            error_code=exc.code,
            error_message=exc.safe_message,
        )
    except Exception:
        await _finish(
            session,
            execution_id,
            status="failed",
            error_code="SKILL_INTERNAL_ERROR",
            error_message="The Skill could not complete safely.",
        )
    return True


async def process_execution_batch(
    session: AsyncSession, registry: AdapterRegistry, *, limit: int = 50
) -> int:
    processed = 0
    while processed < limit and await process_next_execution(session, registry):
        processed += 1
    return processed
