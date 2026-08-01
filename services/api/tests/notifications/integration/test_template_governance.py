from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import select, text

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.cli.seed_notification_templates import seed_notification_templates
from vav.core.database import session_factory
from vav.models.identity import AuthSession, User
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.notifications.admin_router import (
    _template_transition,
    rollback_template_release,
)
from vav.modules.notifications.schemas import StatusReasonRequest


def request_fixture() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/notifications/template-releases/test",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
async def test_template_release_transitions_and_rollback_are_executable() -> None:
    await seed_notification_templates()
    async with session_factory() as session:
        actor = await session.scalar(select(User).where(User.id == SYSTEM_USER_ID))
        assert actor is not None
        principal = AuthenticatedPrincipal(
            user=actor,
            session=cast(AuthSession, cast(Any, None)),
            audience="vav-admin",
            permissions=frozenset(),
        )
        old_release_id = await session.scalar(
            text(
                "SELECT r.id FROM notification_template_releases r "
                "JOIN notification_template_definitions d ON d.id=r.template_definition_id "
                "WHERE d.template_code='password-changed' AND r.locale='en' "
                "AND r.channel='in_app' AND r.status='active'"
            )
        )
        assert old_release_id is not None
        version = f"8.0.{uuid4().int}"
        new_release_id = await session.scalar(
            text(
                "INSERT INTO notification_template_releases "
                "(template_definition_id,semantic_version,locale,channel,subject_template,title_template,"
                "body_html_template,body_text_template,action_label_template,action_url_template,"
                "checksum_sha256,status,created_by) "
                "SELECT template_definition_id,:version,locale,channel,subject_template,"
                "title_template,"
                "body_html_template,body_text_template,action_label_template,action_url_template,"
                ":checksum,'draft',:actor FROM notification_template_releases "
                "WHERE id=:old_id RETURNING id"
            ),
            {
                "version": version,
                "checksum": uuid4().hex,
                "actor": actor.id,
                "old_id": old_release_id,
            },
        )
        await session.commit()
        assert new_release_id is not None

        for target, allowed in [
            ("in_review", {"draft"}),
            ("approved", {"in_review"}),
            ("active", {"approved"}),
        ]:
            await _template_transition(
                release_id=UUID(str(new_release_id)),
                target=target,
                allowed=allowed,
                request=request_fixture(),
                principal=principal,
                session=session,
            )
        statuses = (
            await session.execute(
                text(
                    "SELECT id,status FROM notification_template_releases "
                    "WHERE id IN (:old_id,:new_id)"
                ),
                {"old_id": old_release_id, "new_id": new_release_id},
            )
        ).all()
        assert {str(row.id): row.status for row in statuses} == {
            str(old_release_id): "superseded",
            str(new_release_id): "active",
        }

        await rollback_template_release(
            UUID(str(old_release_id)),
            StatusReasonRequest(reason="Automated rollback acceptance verification."),
            request_fixture(),
            principal,
            session,
        )
        restored_status = await session.scalar(
            text("SELECT status FROM notification_template_releases WHERE id=:id"),
            {"id": old_release_id},
        )
        replacement_status = await session.scalar(
            text("SELECT status FROM notification_template_releases WHERE id=:id"),
            {"id": new_release_id},
        )
        assert restored_status == "active"
        assert replacement_status == "superseded"
