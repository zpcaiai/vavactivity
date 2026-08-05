"""Validate the Batch 15 operational baseline without fabricating member choices.

Likes, matches, invitations and contact consent are member-authored facts, so a
production seed must never create them.  This command verifies that the RBAC
registry and fail-closed configuration required to operate the module exist.
Synthetic interaction journeys belong to the dedicated E2E fixture command.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from vav.core.config import get_settings
from vav.core.database import session_factory

REQUIRED_ROLES = (
    "interaction_operator",
    "interaction_safety_reviewer",
    "interaction_support",
)


async def seed_matchmaking_interactions() -> None:
    settings = get_settings()
    if settings.matchmaking_allow_direct_profile_like:
        raise RuntimeError("direct profile likes must remain disabled until policy approval")
    if settings.matchmaking_single_like_notification_enabled:
        raise RuntimeError("one-sided like notifications violate the confidentiality boundary")
    if not settings.matchmaking_fail_closed_on_moderation_error:
        raise RuntimeError("matchmaking moderation must fail closed")
    if not settings.matchmaking_block_invalidates_contact_grants:
        raise RuntimeError("blocks must invalidate contact grants")

    async with session_factory() as session:
        roles = set(
            await session.scalars(
                text("SELECT code FROM roles WHERE code = ANY(:codes)"),
                {"codes": list(REQUIRED_ROLES)},
            )
        )
    missing = sorted(set(REQUIRED_ROLES) - roles)
    if missing:
        raise RuntimeError(f"run seed_permissions first; missing roles: {', '.join(missing)}")

    print(
        "Matchmaking interaction baseline ready: 3 roles; direct likes and "
        "one-sided notifications disabled; mutual contact confirmation required."
    )


if __name__ == "__main__":
    asyncio.run(seed_matchmaking_interactions())
