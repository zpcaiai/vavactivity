"""Seed the governed deterministic Trust & Safety rule baseline."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory

RULES = (
    (
        "block.pair.v1",
        "blocking",
        {"signal": "pair_blocked", "operator": "eq", "value": True},
        {"action": "deny", "reason_code": "pair_blocked"},
        "critical",
        10000,
        [
            "profile-view",
            "recommendation",
            "interaction",
            "contact-exchange",
            "relationship",
            "activity",
        ],
    ),
    (
        "fraud.money_request.v1",
        "fraud",
        {"signal": "money_request_detected", "operator": "eq", "value": True},
        {"action": "content_hold", "reason_code": "money_request"},
        "high",
        5000,
        ["interaction", "relationship"],
    ),
    (
        "fraud.external_payment.v1",
        "fraud",
        {"signal": "external_payment_link_detected", "operator": "eq", "value": True},
        {"action": "content_hold", "reason_code": "external_payment_link"},
        "high",
        5000,
        ["interaction", "relationship"],
    ),
    (
        "harassment.post_decline.v1",
        "harassment",
        {"signal": "post_decline_contact_count", "operator": "gte", "value": 3},
        {"action": "human_review_required", "reason_code": "repeated_post_decline_contact"},
        "high",
        4000,
        ["interaction"],
    ),
    (
        "auth.takeover.reverify.v1",
        "account_takeover",
        {"signal": "account_takeover_signal", "operator": "eq", "value": True},
        {"action": "require_reverification", "reason_code": "account_security_review"},
        "high",
        5000,
        ["interaction", "contact-exchange", "ai"],
    ),
)


async def seed_trust_safety() -> None:
    settings = get_settings()
    if not settings.safety_fail_closed:
        raise RuntimeError("Trust & Safety must fail closed")
    if settings.safety_auto_permanent_ban_enabled:
        raise RuntimeError("automated permanent bans are forbidden")
    await ensure_system_user()
    async with session_factory() as session:
        for code, category, condition, action, severity, score, modules in RULES:
            await session.execute(
                text(
                    "INSERT INTO safety_risk_rules "
                    "(rule_code,semantic_version,category,rule_type,condition_schema,condition_definition,"
                    "action_definition,severity,score_delta,status,applicable_modules,rollout_basis_points,"
                    "created_by,approved_at,activated_at) VALUES "
                    "(:code,'1.0.0',:category,'deterministic',CAST(:schema AS jsonb),"
                    "CAST(:condition AS jsonb),CAST(:action AS jsonb),:severity,:score,'active',"
                    "CAST(:modules AS jsonb),10000,:actor,now(),now()) "
                    "ON CONFLICT (rule_code,semantic_version) DO UPDATE SET "
                    "condition_definition=EXCLUDED.condition_definition,action_definition=EXCLUDED.action_definition,"
                    "applicable_modules=EXCLUDED.applicable_modules,status='active'"
                ),
                {
                    "code": code,
                    "category": category,
                    "schema": json.dumps({"dsl": "registered-signals-v1"}),
                    "condition": json.dumps(condition),
                    "action": json.dumps(action),
                    "severity": severity,
                    "score": score,
                    "modules": json.dumps(modules),
                    "actor": SYSTEM_USER_ID,
                },
            )
        await session.commit()
    print(f"Trust & Safety seed complete: {len(RULES)} governed rules")


if __name__ == "__main__":
    asyncio.run(seed_trust_safety())
