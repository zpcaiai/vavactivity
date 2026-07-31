from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import SecurityAuditEvent


def record_security_event(
    session: AsyncSession,
    *,
    event_type: str,
    severity: str = "info",
    actor_type: str = "system",
    actor_user_id: UUID | None = None,
    actor_session_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    reason: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address_hash: str | None = None,
    user_agent_hash: str | None = None,
) -> SecurityAuditEvent:
    event = SecurityAuditEvent(
        event_type=event_type,
        severity=severity,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_session_id=actor_session_id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        before_state=before_state,
        after_state=after_state,
        event_metadata=metadata or {},
        ip_address_hash=ip_address_hash,
        user_agent_hash=user_agent_hash,
    )
    session.add(event)
    return event
