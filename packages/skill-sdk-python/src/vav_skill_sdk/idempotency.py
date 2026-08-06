"""Installation-scoped idempotency helpers with deterministic payload binding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


def input_digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class IdempotencyScope:
    installation_id: UUID
    semantic_version: str
    actor_reference: str
    key: str
    input_hash: str

    def cache_key(self) -> str:
        raw = ":".join(
            (
                str(self.installation_id),
                self.semantic_version,
                self.actor_reference,
                self.key,
                self.input_hash,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()


class SkillIdempotencyStore(Protocol):
    async def get(self, scope: IdempotencyScope) -> dict[str, Any] | None: ...

    async def put(self, scope: IdempotencyScope, result: dict[str, Any]) -> None: ...
