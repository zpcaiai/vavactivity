"""Seed the versioned Batch 16 policy registry without fabricating journeys."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.relationships.domain import STAGES


async def seed_relationships() -> None:
    settings = get_settings()
    unsafe = []
    if not settings.relationship_require_mutual_stage_confirmation:
        unsafe.append("stage changes must require mutual confirmation")
    if settings.relationship_auto_resume_enabled:
        unsafe.append("automatic resume must remain disabled")
    if settings.relationship_ending_requires_other_party_approval:
        unsafe.append("one participant must always be able to end")
    if not settings.relationship_manipulative_reminders_disabled:
        unsafe.append("manipulative reminders must remain disabled")
    if not settings.relationship_fail_closed_on_moderation_error:
        unsafe.append("moderation must fail closed")
    if unsafe:
        raise RuntimeError("; ".join(unsafe))

    manifest = {
        "stages": [
            {"code": code, "order": index, "mutual_confirmation_required": True}
            for index, code in enumerate(STAGES)
        ],
        "forward_skip_allowed": settings.relationship_allow_stage_skip_forward,
        "backward_proposal_allowed": settings.relationship_allow_stage_backward_proposal,
        "health_scoring": False,
    }
    policy = {
        "pause_immediate": True,
        "resume_mutual": True,
        "auto_resume": False,
        "ending_unilateral_after_confirmation": True,
        "reminders_opt_in": True,
        "reminder_max_per_month": settings.relationship_reminder_max_per_month,
    }
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO relationship_stage_registries (registry_code,registry_version,status,manifest,policy,approved_at,activated_at) VALUES (:code,'1.0.0','active',CAST(:manifest AS jsonb),CAST(:policy AS jsonb),now(),now()) ON CONFLICT (registry_code,registry_version) DO UPDATE SET manifest=EXCLUDED.manifest,policy=EXCLUDED.policy,updated_at=now()"
            ),
            {
                "code": settings.relationship_default_stage_registry,
                "manifest": json.dumps(manifest),
                "policy": json.dumps(policy),
            },
        )
        await session.execute(
            text(
                "INSERT INTO relationship_checkin_definitions (definition_code,definition_version,status,manifest,activated_at) VALUES ('gentle-reflection','1.0.0','active',CAST(:manifest AS jsonb),now()) ON CONFLICT (definition_code,definition_version) DO UPDATE SET manifest=EXCLUDED.manifest"
            ),
            {
                "manifest": json.dumps(
                    {
                        "prompts": [
                            "What felt supportive?",
                            "What boundary would help?",
                            "What would you like to communicate?",
                        ],
                        "score": False,
                        "private_by_default": True,
                    }
                )
            },
        )
        await session.commit()
    print(
        f"Relationship baseline ready: {len(STAGES)} stages; mutual progress; unilateral pause/end; no health score."
    )


if __name__ == "__main__":
    asyncio.run(seed_relationships())
