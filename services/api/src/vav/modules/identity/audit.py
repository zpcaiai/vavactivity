from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import SecurityAuditEvent
from vav.models.system import OutboxEvent

NOTIFICATION_SECURITY_EVENTS = {
    "auth.registration.created",
    "auth.email_verification.completed",
    "auth.password.changed",
    "auth.password.reset.completed",
    "auth.refresh_token.reuse_detected",
}


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
    user_id = target_id if target_type == "user" and target_id is not None else actor_user_id
    if event_type in NOTIFICATION_SECURITY_EVENTS and user_id is not None:
        session.add(
            OutboxEvent(
                topic=event_type,
                aggregate_type="user",
                aggregate_id=str(user_id),
                payload={"user_id": str(user_id)},
            )
        )
    return event
