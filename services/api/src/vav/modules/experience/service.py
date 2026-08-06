# ruff: noqa: E501

"""Persistence and policy services for Batch 23 experience orchestration."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.experience.domain import (
    closure_checks,
    evaluate_route,
    minimize_feedback_context,
    scan_route_graph,
    support_queue,
    validate_identifier_context,
)
from vav.modules.experience.schemas import (
    ClosureEvaluation,
    DeepLinkCreate,
    FeedbackCreate,
    HandoffCreate,
    JourneyReconcile,
    JourneyStart,
    SupportRequestCreate,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _row(value: Any) -> dict[str, Any]:
    return dict(value._mapping)


async def _audit(
    session: AsyncSession,
    actor_id: UUID,
    action: str,
    subject_type: str,
    subject_id: UUID,
    context: dict[str, Any] | None = None,
    *,
    actor_type: str = "user",
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,:actor_type,:action,:subject_type,:subject_id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "actor_type": actor_type,
            "action": action,
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "context": _json(context or {}),
        },
    )


async def list_routes(
    session: AsyncSession, application_code: str | None = None
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM experience_routes WHERE lifecycle='active'"
    params: dict[str, Any] = {}
    if application_code:
        sql += " AND application_code=:app"
        params["app"] = application_code
    sql += " ORDER BY application_code,sort_order,route_code"
    rows = (await session.execute(text(sql), params)).mappings()
    return [dict(row) for row in rows]


async def route_eligibility(
    session: AsyncSession,
    route_code: str,
    *,
    authenticated: bool,
    permissions: set[str],
    capabilities: set[str] | None = None,
    enabled_features: set[str] | None = None,
    restriction_codes: set[str] | None = None,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM experience_routes WHERE route_code=:code AND lifecycle='active'"),
            {"code": route_code},
        )
    ).first()
    if row is None:
        raise VavError(
            "EXPERIENCE_ROUTE_NOT_FOUND", "The requested route is not registered.", status_code=404
        )
    route = _row(row)
    decision = evaluate_route(
        route,
        authenticated=authenticated,
        permissions=permissions,
        capabilities=capabilities or set(),
        enabled_features=enabled_features or set(),
        restriction_codes=restriction_codes or set(),
    )
    return {
        "route_code": route_code,
        "eligible": decision.eligible,
        "reason_code": decision.reason_code,
        "fallback_route_code": decision.fallback_route_code,
        "route_path": route["route_path"] if decision.eligible else None,
    }


async def navigation(
    session: AsyncSession,
    *,
    application_code: str,
    authenticated: bool,
    permissions: set[str],
    locale: str,
    capabilities: set[str] | None = None,
    enabled_features: set[str] | None = None,
    restriction_codes: set[str] | None = None,
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT r.*,n.localized_labels,n.space,n.parent_node_code "
                "FROM experience_routes r JOIN experience_ia_nodes n ON n.node_code=r.ia_node_code "
                "JOIN experience_ia_versions v ON v.id=n.ia_version_id AND v.status='active' "
                "WHERE r.application_code=:app AND r.lifecycle='active' ORDER BY n.sort_order,r.sort_order,r.route_code"
            ),
            {"app": application_code},
        )
    ).mappings()
    items: list[dict[str, Any]] = []
    for raw in rows:
        route = dict(raw)
        decision = evaluate_route(
            route,
            authenticated=authenticated,
            permissions=permissions,
            capabilities=capabilities or set(),
            enabled_features=enabled_features or set(),
            restriction_codes=restriction_codes or set(),
        )
        if not decision.eligible:
            continue
        labels = route.get("localized_labels") or {}
        items.append(
            {
                "route_code": route["route_code"],
                "route_name": route["route_name"],
                "route_path": route["route_path"],
                "label": labels.get(locale) or labels.get("zh-CN") or route["route_name"],
                "space": route["space"],
                "node_code": route["ia_node_code"],
                "parent_node_code": route["parent_node_code"],
                "critical": route["critical"],
            }
        )
    return {
        "application_code": application_code,
        "locale": locale,
        "items": items,
        "cache_scope": "identity+permission+feature+restriction-version",
    }


async def sync_user_tasks(session: AsyncSession, user_id: UUID) -> dict[str, int]:
    definition_id = await session.scalar(
        text(
            "SELECT id FROM experience_task_definitions WHERE task_code='identity.verify-email' AND active ORDER BY version DESC LIMIT 1"
        )
    )
    user = (
        await session.execute(
            text("SELECT email_verified_at,auth_version,rbac_version FROM users WHERE id=:id"),
            {"id": user_id},
        )
    ).first()
    if user is None:
        raise VavError("USER_NOT_FOUND", "The user account was not found.", status_code=404)
    if definition_id is None:
        raise VavError(
            "EXPERIENCE_TASK_REGISTRY_EMPTY",
            "Task definitions have not been synchronized.",
            status_code=503,
        )
    changed = 0
    if user.email_verified_at is None:
        result = await session.execute(
            text(
                "INSERT INTO experience_user_tasks "
                "(user_id,task_definition_id,source_module,source_entity_type,source_entity_id,deduplication_key,state,priority,authoritative_state_version) "
                "VALUES (:user,:definition,'identity','user',:user,'identity.verify-email','available',950,:version) "
                "ON CONFLICT (user_id,deduplication_key) DO UPDATE SET "
                "task_definition_id=EXCLUDED.task_definition_id,state=CASE WHEN experience_user_tasks.state IN ('completed','invalidated') THEN experience_user_tasks.state ELSE 'available' END,"
                "authoritative_state_version=EXCLUDED.authoritative_state_version,updated_at=now() RETURNING id"
            ),
            {
                "user": user_id,
                "definition": definition_id,
                "version": f"{user.auth_version}:{user.rbac_version}:unverified",
            },
        )
        changed = 1 if result.first() else 0
    else:
        result = await session.execute(
            text(
                "UPDATE experience_user_tasks SET state='completed',completed_at=COALESCE(completed_at,now()),updated_at=now(),"
                "authoritative_state_version=:version WHERE user_id=:user AND deduplication_key='identity.verify-email' "
                "AND state NOT IN ('completed','invalidated') RETURNING id"
            ),
            {"user": user_id, "version": f"{user.auth_version}:{user.rbac_version}:verified"},
        )
        changed = 1 if result.first() else 0
    await session.commit()
    return {"changed": changed}


async def list_tasks(
    session: AsyncSession, user_id: UUID, include_history: bool = False
) -> list[dict[str, Any]]:
    await sync_user_tasks(session, user_id)
    states = "" if include_history else " AND t.state NOT IN ('completed','expired','invalidated')"
    rows = (
        await session.execute(
            text(
                "SELECT t.*,d.task_code,d.title_i18n,d.description_i18n,d.action_route_code,d.fallback_route_code "
                "FROM experience_user_tasks t JOIN experience_task_definitions d ON d.id=t.task_definition_id "
                "WHERE t.user_id=:user"
                + states
                + " ORDER BY t.priority DESC,t.due_at NULLS LAST,t.created_at"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def user_home(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    tasks = await list_tasks(session, user_id)
    identity = (
        (
            await session.execute(
                text(
                    "SELECT id,display_email,email_verified_at,preferred_locale,timezone FROM users WHERE id=:id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .one()
    )
    membership = (
        (
            await session.execute(
                text(
                    "SELECT a.status,a.expires_at,p.plan_code FROM membership_accounts a "
                    "JOIN membership_plans p ON p.id=a.membership_plan_id WHERE a.user_id=:user "
                    "AND a.status IN ('active','trialing','grace_period','past_due','cancel_scheduled') "
                    "ORDER BY (a.source_type='free_default'),a.starts_at DESC LIMIT 1"
                ),
                {"user": user_id},
            )
        )
        .mappings()
        .first()
    )
    unread = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM user_notifications WHERE user_id=:user AND status='active' AND read_at IS NULL AND withdrawn_at IS NULL AND (expires_at IS NULL OR expires_at>now())"
            ),
            {"user": user_id},
        )
        or 0
    )
    journeys = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM experience_journey_instances WHERE user_id=:user AND state IN ('active','blocked','waiting')"
            ),
            {"user": user_id},
        )
        or 0
    )
    return {
        "identity": dict(identity),
        "membership": dict(membership)
        if membership
        else {"status": "not_available", "plan_code": None, "expires_at": None},
        "critical_tasks": [task for task in tasks if int(task["priority"]) >= 900],
        "next_tasks": [task for task in tasks if int(task["priority"]) < 900],
        "unread_notifications": unread,
        "active_journeys": journeys,
        "priority_policy": [
            "safety",
            "privacy",
            "payment",
            "owned_services",
            "next_step",
            "discovery",
            "marketing",
        ],
    }


async def list_journeys(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT i.*,d.journey_code,d.version AS journey_version,d.step_manifest "
                "FROM experience_journey_instances i JOIN experience_journey_definitions d ON d.id=i.definition_id "
                "WHERE i.user_id=:user ORDER BY i.updated_at DESC"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def start_journey(
    session: AsyncSession, user_id: UUID, payload: JourneyStart
) -> dict[str, Any]:
    definition = (
        (
            await session.execute(
                text(
                    "SELECT * FROM experience_journey_definitions WHERE journey_code=:code AND status='active' ORDER BY version DESC LIMIT 1"
                ),
                {"code": payload.journey_code},
            )
        )
        .mappings()
        .first()
    )
    if definition is None:
        raise VavError(
            "EXPERIENCE_JOURNEY_NOT_FOUND",
            "The journey definition is unavailable.",
            status_code=404,
        )
    steps = list(definition["step_manifest"])
    if not steps:
        raise VavError(
            "EXPERIENCE_JOURNEY_INVALID", "The journey has no registered steps.", status_code=409
        )
    existing = (
        await session.execute(
            text(
                "SELECT i.* FROM experience_journey_instances i WHERE i.definition_id=:definition AND i.user_id=:user "
                "AND i.source_module=:source AND i.source_entity_id IS NOT DISTINCT FROM :entity AND i.state IN ('active','blocked','waiting') "
                "ORDER BY i.started_at DESC LIMIT 1"
            ),
            {
                "definition": definition["id"],
                "user": user_id,
                "source": payload.source_module,
                "entity": payload.source_entity_id,
            },
        )
    ).first()
    if existing:
        return _row(existing)
    row = (
        await session.execute(
            text(
                "INSERT INTO experience_journey_instances "
                "(definition_id,user_id,source_module,source_entity_type,source_entity_id,current_step_code,authoritative_state_version) "
                "VALUES (:definition,:user,:source,:entity_type,:entity,:step,:version) RETURNING *"
            ),
            {
                "definition": definition["id"],
                "user": user_id,
                "source": payload.source_module,
                "entity_type": payload.source_entity_type,
                "entity": payload.source_entity_id,
                "step": steps[0]["code"],
                "version": payload.authoritative_state_version,
            },
        )
    ).one()
    item = _row(row)
    await _audit(
        session,
        user_id,
        "experience.journey.started",
        "experience_journey_instance",
        item["id"],
        {"journey_code": payload.journey_code},
    )
    await session.commit()
    return item


async def reconcile_journey(
    session: AsyncSession, actor_id: UUID, journey_id: UUID, payload: JourneyReconcile
) -> dict[str, Any]:
    current = (
        (
            await session.execute(
                text(
                    "SELECT i.*,d.step_manifest FROM experience_journey_instances i "
                    "JOIN experience_journey_definitions d ON d.id=i.definition_id WHERE i.id=:id FOR UPDATE"
                ),
                {"id": journey_id},
            )
        )
        .mappings()
        .first()
    )
    if current is None:
        raise VavError(
            "EXPERIENCE_JOURNEY_NOT_FOUND", "The journey instance was not found.", status_code=404
        )
    if (
        current["authoritative_state_version"] == payload.authoritative_state_version
        and current["current_step_code"] != payload.current_step_code
    ):
        raise VavError(
            "EXPERIENCE_JOURNEY_STALE_PROJECTION",
            "Journey progression requires a newer authoritative business-state version.",
            status_code=409,
        )
    allowed_steps = {str(step["code"]) for step in current["step_manifest"]}
    if payload.current_step_code not in allowed_steps:
        raise VavError(
            "EXPERIENCE_JOURNEY_STEP_INVALID",
            "The step is not part of the active journey version.",
            status_code=409,
        )
    row = (
        await session.execute(
            text(
                "UPDATE experience_journey_instances SET current_step_code=:step,state=:state,block_reason_code=:reason,"
                "authoritative_state_version=:version,updated_at=now(),completed_at=CASE WHEN :state IN ('completed','cancelled','expired','invalidated') THEN now() ELSE NULL END "
                "WHERE id=:id RETURNING *"
            ),
            {
                "step": payload.current_step_code,
                "state": payload.state,
                "reason": payload.block_reason_code,
                "version": payload.authoritative_state_version,
                "id": journey_id,
            },
        )
    ).one()
    item = _row(row)
    await _audit(
        session,
        actor_id,
        "experience.journey.reconciled",
        "experience_journey_instance",
        journey_id,
        {"state": payload.state, "step": payload.current_step_code},
        actor_type="admin",
    )
    await session.commit()
    return item


async def create_handoff(
    session: AsyncSession, user_id: UUID, payload: HandoffCreate
) -> dict[str, Any]:
    definition = (
        (
            await session.execute(
                text(
                    "SELECT * FROM experience_handoff_definitions WHERE handoff_code=:code AND active"
                ),
                {"code": payload.handoff_code},
            )
        )
        .mappings()
        .first()
    )
    if definition is None:
        raise VavError(
            "EXPERIENCE_HANDOFF_NOT_FOUND",
            "The handoff definition is unavailable.",
            status_code=404,
        )
    allowed_keys = set(definition["context_schema"].get("allowed_keys", []))
    context = {key: str(value) for key, value in payload.context.items()}
    validate_identifier_context(context, allowed_keys)
    if payload.source_route_code != definition[
        "return_route_code"
    ] and payload.source_route_code not in {"user.home", "user.experience-home"}:
        raise VavError(
            "EXPERIENCE_HANDOFF_SOURCE_INVALID",
            "The handoff source route is outside its registered return policy.",
            status_code=409,
        )
    context_hash = _checksum(context)
    expires = datetime.now(UTC) + timedelta(seconds=int(definition["ttl_seconds"]))
    row = (
        await session.execute(
            text(
                "INSERT INTO experience_handoff_instances "
                "(definition_id,user_id,source_entity_type,source_entity_id,user_intent,context_encrypted,context_hash,source_route_code,target_route_code,return_route_code,expires_at) "
                "VALUES (:definition,:user,:entity_type,:entity,:intent,:context,:hash,:source,:target,:return,:expires) RETURNING *"
            ),
            {
                "definition": definition["id"],
                "user": user_id,
                "entity_type": payload.source_entity_type,
                "entity": payload.source_entity_id,
                "intent": payload.user_intent,
                "context": encrypt_private(context),
                "hash": context_hash,
                "source": payload.source_route_code,
                "target": definition["completion_policy"]["target_route_code"],
                "return": definition["return_route_code"],
                "expires": expires,
            },
        )
    ).one()
    item = _row(row)
    item.pop("context_encrypted", None)
    await _audit(
        session,
        user_id,
        "experience.handoff.created",
        "experience_handoff_instance",
        item["id"],
        {"handoff_code": payload.handoff_code, "context_hash": context_hash},
    )
    await session.commit()
    return item


async def accept_handoff(
    session: AsyncSession, user_id: UUID, handoff_id: UUID, permissions: set[str]
) -> dict[str, Any]:
    current = (
        (
            await session.execute(
                text("SELECT * FROM experience_handoff_instances WHERE id=:id FOR UPDATE"),
                {"id": handoff_id},
            )
        )
        .mappings()
        .first()
    )
    if current is None or current["user_id"] != user_id:
        raise VavError(
            "EXPERIENCE_HANDOFF_NOT_FOUND", "The handoff was not found.", status_code=404
        )
    if current["state"] != "pending":
        raise VavError(
            "EXPERIENCE_HANDOFF_STATE_INVALID",
            "Only a pending handoff can be accepted.",
            status_code=409,
        )
    if current["expires_at"] <= datetime.now(UTC):
        await session.execute(
            text(
                "UPDATE experience_handoff_instances SET state='expired',updated_at=now() WHERE id=:id"
            ),
            {"id": handoff_id},
        )
        await session.commit()
        raise VavError("EXPERIENCE_HANDOFF_EXPIRED", "The handoff has expired.", status_code=410)
    context = decrypt_private(current["context_encrypted"])
    if not isinstance(context, dict) or _checksum(context) != current["context_hash"]:
        await session.execute(
            text(
                "UPDATE experience_handoff_instances SET state='invalidated',failure_code='context_integrity_failed',updated_at=now() WHERE id=:id"
            ),
            {"id": handoff_id},
        )
        await session.commit()
        raise VavError(
            "EXPERIENCE_HANDOFF_INTEGRITY_FAILED",
            "The handoff context failed integrity validation.",
            status_code=409,
        )
    route = await route_eligibility(
        session, current["target_route_code"], authenticated=True, permissions=permissions
    )
    if not route["eligible"]:
        raise VavError(
            "EXPERIENCE_HANDOFF_TARGET_INELIGIBLE",
            "The target is no longer available to this user.",
            status_code=403,
            details=[route],
        )
    row = (
        await session.execute(
            text(
                "UPDATE experience_handoff_instances SET state='accepted',updated_at=now() WHERE id=:id RETURNING *"
            ),
            {"id": handoff_id},
        )
    ).one()
    item = _row(row)
    item.pop("context_encrypted", None)
    item["route"] = route
    item["route_parameters"] = context
    await _audit(
        session,
        user_id,
        "experience.handoff.accepted",
        "experience_handoff_instance",
        handoff_id,
        {"context_hash": current["context_hash"]},
    )
    await session.commit()
    return item


async def search(
    session: AsyncSession,
    *,
    query: str,
    user_id: UUID | None,
    permissions: set[str],
    admin: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    rows = (
        await session.execute(
            text(
                "SELECT id,document_code,source_module,source_entity_type,title,summary,locale,visibility,permission_codes,owner_user_id,route_code,route_parameters,"
                "ts_rank(search_vector,plainto_tsquery('simple',:query)) AS rank "
                "FROM experience_search_documents WHERE index_status='active' AND NOT blocked AND NOT erased "
                "AND search_vector @@ plainto_tsquery('simple',:query) "
                "AND (visibility='public' OR (visibility='personal' AND owner_user_id=:user) OR (visibility='admin' AND :admin)) "
                "ORDER BY rank DESC,indexed_at DESC LIMIT :limit"
            ),
            {"query": query.strip(), "user": user_id, "admin": admin, "limit": limit},
        )
    ).mappings()
    output: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        required = set(item.pop("permission_codes") or [])
        if required - permissions:
            continue
        item.pop("owner_user_id", None)
        output.append(item)
    return output


async def help_articles(
    session: AsyncSession, *, route_code: str | None, locale: str
) -> list[dict[str, Any]]:
    sql = "SELECT article_code,version,category,route_codes,state_codes,actor_types,locale,title,body_markdown,published_at FROM experience_help_articles WHERE status='published' AND locale=:locale"
    params: dict[str, Any] = {"locale": locale}
    if route_code:
        sql += " AND route_codes @> CAST(:routes AS jsonb)"
        params["routes"] = _json([route_code])
    sql += " ORDER BY category,article_code"
    rows = (await session.execute(text(sql), params)).mappings()
    return [dict(row) for row in rows]


async def create_support_request(
    session: AsyncSession, user_id: UUID, payload: SupportRequestCreate
) -> dict[str, Any]:
    route_exists = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM experience_routes WHERE route_code=:code AND lifecycle='active')"
        ),
        {"code": payload.source_route_code},
    )
    if not route_exists:
        raise VavError(
            "EXPERIENCE_ROUTE_NOT_FOUND",
            "The support source route is not registered.",
            status_code=422,
        )
    queue = support_queue(payload.category)
    row = (
        await session.execute(
            text(
                "INSERT INTO experience_support_requests (user_id,source_route_code,source_entity_type,source_entity_id,category,description_encrypted,assignment_queue) "
                "VALUES (:user,:route,:entity_type,:entity,:category,:description,:queue) RETURNING id,user_id,source_route_code,source_entity_type,source_entity_id,category,assignment_queue,state,created_at"
            ),
            {
                "user": user_id,
                "route": payload.source_route_code,
                "entity_type": payload.source_entity_type,
                "entity": payload.source_entity_id,
                "category": payload.category,
                "description": encrypt_private(payload.description),
                "queue": queue,
            },
        )
    ).one()
    item = _row(row)
    await _audit(
        session,
        user_id,
        "experience.support.created",
        "experience_support_request",
        item["id"],
        {"category": payload.category, "queue": queue},
    )
    await session.commit()
    return item


async def create_feedback(
    session: AsyncSession, user_id: UUID | None, payload: FeedbackCreate
) -> dict[str, Any]:
    context = minimize_feedback_context(payload.context)
    row = (
        await session.execute(
            text(
                "INSERT INTO experience_feedback (user_id,route_code,feedback_type,context_minimized) VALUES (:user,:route,:kind,CAST(:context AS jsonb)) RETURNING *"
            ),
            {
                "user": user_id,
                "route": payload.route_code,
                "kind": payload.feedback_type,
                "context": _json(context),
            },
        )
    ).one()
    await session.commit()
    return _row(row)


async def create_deep_link(
    session: AsyncSession, actor_id: UUID, payload: DeepLinkCreate
) -> dict[str, Any]:
    route = await session.scalar(
        text(
            "SELECT route_code FROM experience_routes WHERE route_code=:code AND lifecycle='active'"
        ),
        {"code": payload.target_route_code},
    )
    fallback = await session.scalar(
        text(
            "SELECT route_code FROM experience_routes WHERE route_code=:code AND lifecycle='active'"
        ),
        {"code": payload.fallback_route_code},
    )
    if not route or not fallback:
        raise VavError(
            "EXPERIENCE_DEEP_LINK_ROUTE_INVALID",
            "Deep-link target and fallback routes must be active.",
            status_code=422,
        )
    params = {key: str(value) for key, value in payload.route_parameters.items()}
    validate_identifier_context(params, set(params))
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    row = (
        await session.execute(
            text(
                "INSERT INTO experience_deep_links (purpose,token_hash,user_id,entity_type,entity_id,target_route_code,fallback_route_code,route_parameters,permission_codes,single_use,expires_at) "
                "VALUES (:purpose,:hash,:user,:entity_type,:entity,:target,:fallback,CAST(:params AS jsonb),CAST(:permissions AS jsonb),:single_use,:expires) RETURNING id,purpose,user_id,entity_type,entity_id,target_route_code,fallback_route_code,single_use,expires_at,created_at"
            ),
            {
                "purpose": payload.purpose,
                "hash": token_hash,
                "user": payload.user_id,
                "entity_type": payload.entity_type,
                "entity": payload.entity_id,
                "target": payload.target_route_code,
                "fallback": payload.fallback_route_code,
                "params": _json(params),
                "permissions": _json(payload.permission_codes),
                "single_use": payload.single_use,
                "expires": datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds),
            },
        )
    ).one()
    item = _row(row)
    item["token"] = raw_token
    await _audit(
        session,
        actor_id,
        "experience.deep_link.created",
        "experience_deep_link",
        item["id"],
        {"purpose": payload.purpose, "target_route_code": payload.target_route_code},
        actor_type="admin",
    )
    await session.commit()
    return item


async def resolve_deep_link(
    session: AsyncSession, user_id: UUID, raw_token: str, permissions: set[str]
) -> dict[str, Any]:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    row = (
        (
            await session.execute(
                text("SELECT * FROM experience_deep_links WHERE token_hash=:hash FOR UPDATE"),
                {"hash": token_hash},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["user_id"] != user_id:
        raise VavError(
            "EXPERIENCE_DEEP_LINK_NOT_FOUND", "The deep link is unavailable.", status_code=404
        )
    fallback = {"route_code": row["fallback_route_code"], "reason_code": "link_unavailable"}
    if (
        row["invalidated_at"]
        or row["expires_at"] <= datetime.now(UTC)
        or (row["single_use"] and row["consumed_at"])
    ):
        return {"resolved": False, "fallback": fallback}
    if set(row["permission_codes"] or []) - permissions:
        return {"resolved": False, "fallback": {**fallback, "reason_code": "permission_changed"}}
    route = await route_eligibility(
        session, row["target_route_code"], authenticated=True, permissions=permissions
    )
    if not route["eligible"]:
        return {"resolved": False, "fallback": {**fallback, "reason_code": route["reason_code"]}}
    if row["single_use"]:
        await session.execute(
            text(
                "UPDATE experience_deep_links SET consumed_at=now() WHERE id=:id AND consumed_at IS NULL"
            ),
            {"id": row["id"]},
        )
    await _audit(
        session,
        user_id,
        "experience.deep_link.resolved",
        "experience_deep_link",
        row["id"],
        {"purpose": row["purpose"]},
    )
    await session.commit()
    return {
        "resolved": True,
        "route": route,
        "route_parameters": row["route_parameters"],
        "purpose": row["purpose"],
    }


ADMIN_TABLES = {
    "ia": ("experience_ia_nodes", "space,sort_order,node_code"),
    "routes": ("experience_routes", "application_code,sort_order,route_code"),
    "tasks": ("experience_task_definitions", "source_module,priority DESC,task_code"),
    "journeys": ("experience_journey_definitions", "journey_code,version DESC"),
    "handoffs": ("experience_handoff_definitions", "handoff_code"),
    "search-governance": ("experience_search_documents", "indexed_at DESC,id"),
    "help": ("experience_help_articles", "category,article_code,version DESC"),
    "support": ("experience_support_requests", "created_at DESC,id"),
    "dead-ends": ("experience_dead_end_findings", "detected_at DESC,id"),
    "evidence": ("experience_closure_checks", "evaluated_at DESC,id"),
}


async def admin_list(session: AsyncSession, section: str) -> list[dict[str, Any]]:
    definition = ADMIN_TABLES.get(section)
    if definition is None:
        raise VavError(
            "EXPERIENCE_SECTION_NOT_FOUND", "The experience section was not found.", status_code=404
        )
    table, order = definition
    rows = (
        await session.execute(text(f"SELECT * FROM {table} ORDER BY {order} LIMIT 500"))
    ).mappings()
    output: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        item.pop("description_encrypted", None)
        item.pop("context_encrypted", None)
        output.append(item)
    return output


async def admin_dashboard(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM experience_ia_nodes) AS ia_nodes,"
                "(SELECT count(*) FROM experience_routes WHERE lifecycle='active') AS active_routes,"
                "(SELECT count(*) FROM experience_user_tasks WHERE state IN ('available','in_progress','waiting_user','waiting_other_party','waiting_platform','waiting_provider')) AS active_tasks,"
                "(SELECT count(*) FROM experience_journey_instances WHERE state IN ('active','blocked','waiting')) AS active_journeys,"
                "(SELECT count(*) FROM experience_handoff_instances WHERE state='pending') AS pending_handoffs,"
                "(SELECT count(*) FROM experience_support_requests WHERE state IN ('open','assigned')) AS open_support,"
                "(SELECT count(*) FROM experience_dead_end_findings WHERE severity='critical' AND status IN ('open','acknowledged')) AS critical_dead_ends,"
                "(SELECT count(*) FROM experience_closure_checks WHERE technical_status<>'pass') AS technical_closure_failures,"
                "(SELECT count(*) FROM experience_closure_checks WHERE production_status='certified') AS certified_capabilities"
            )
        )
    ).one()
    item = _row(row)
    item["technical_gates_passed"] = (
        item["critical_dead_ends"] == 0 and item["technical_closure_failures"] == 0
    )
    item["production_certified"] = (
        item["technical_gates_passed"] and item["certified_capabilities"] > 0
    )
    item["release_allowed"] = item["production_certified"]
    return item


async def scan_dead_ends(session: AsyncSession, actor_id: UUID | None = None) -> dict[str, Any]:
    routes = await list_routes(session)
    findings = scan_route_graph(routes)
    active_codes: list[str] = []
    for finding in findings:
        code = f"{finding['type']}:{finding['route_code']}"
        active_codes.append(code)
        await session.execute(
            text(
                "INSERT INTO experience_dead_end_findings (finding_code,finding_type,route_code,severity,owner_team,evidence,status) "
                "VALUES (:code,:kind,:route,:severity,'product_experience',CAST(:evidence AS jsonb),'open') "
                "ON CONFLICT (finding_code) DO UPDATE SET evidence=EXCLUDED.evidence,severity=EXCLUDED.severity,status=CASE WHEN experience_dead_end_findings.status='resolved' THEN 'open' ELSE experience_dead_end_findings.status END,detected_at=now(),resolved_at=NULL"
            ),
            {
                "code": code,
                "kind": finding["type"],
                "route": finding["route_code"],
                "severity": finding["severity"],
                "evidence": _json(finding),
            },
        )
    if active_codes:
        stmt = text(
            "UPDATE experience_dead_end_findings SET status='resolved',resolved_at=now() WHERE status IN ('open','acknowledged') AND finding_code NOT IN :codes"
        ).bindparams(bindparam("codes", expanding=True))
        await session.execute(stmt, {"codes": active_codes})
    else:
        await session.execute(
            text(
                "UPDATE experience_dead_end_findings SET status='resolved',resolved_at=now() WHERE status IN ('open','acknowledged')"
            )
        )
    if actor_id:
        # Audit the first finding when present; a zero-finding scan is captured by closure evidence.
        finding_id = await session.scalar(
            text("SELECT id FROM experience_dead_end_findings ORDER BY detected_at DESC LIMIT 1")
        )
        if finding_id:
            await _audit(
                session,
                actor_id,
                "experience.dead_end.scan",
                "experience_dead_end_finding",
                finding_id,
                {"finding_count": len(findings)},
                actor_type="admin",
            )
    await session.commit()
    critical = [item for item in findings if item["severity"] == "critical"]
    return {
        "routes_scanned": len(routes),
        "findings": findings,
        "critical_count": len(critical),
        "passed": not critical,
    }


async def evaluate_closure(
    session: AsyncSession, actor_id: UUID, payload: ClosureEvaluation
) -> list[dict[str, Any]]:
    routes = await list_routes(session)
    route_by_code = {route["route_code"]: route for route in routes}
    dead_end = await scan_dead_ends(session)
    output: list[dict[str, Any]] = []
    for capability in payload.capability_codes:
        route = route_by_code.get(capability)
        checks = closure_checks(route) if route else {"route_registered": False}
        checks["critical_dead_ends_zero"] = dead_end["critical_count"] == 0
        technical = "pass" if all(checks.values()) else "fail"
        evidence = {
            "capability": capability,
            "checks": checks,
            "evidence_reference": payload.evidence_reference,
            "git_commit": payload.git_commit,
        }
        row = (
            await session.execute(
                text(
                    "INSERT INTO experience_closure_checks (capability_code,git_commit,environment,checks,technical_status,production_status,evidence_checksum_sha256,evaluated_by) "
                    "VALUES (:capability,:commit,:environment,CAST(:checks AS jsonb),:technical,'not_certified',:checksum,:actor) "
                    "ON CONFLICT (capability_code,git_commit,environment) DO UPDATE SET checks=EXCLUDED.checks,technical_status=EXCLUDED.technical_status,"
                    "production_status='not_certified',evidence_checksum_sha256=EXCLUDED.evidence_checksum_sha256,evaluated_by=EXCLUDED.evaluated_by,evaluated_at=now(),certified_by=NULL,certified_at=NULL,certification_reason=NULL RETURNING *"
                ),
                {
                    "capability": capability,
                    "commit": payload.git_commit,
                    "environment": payload.environment,
                    "checks": _json(checks),
                    "technical": technical,
                    "checksum": _checksum(evidence),
                    "actor": actor_id,
                },
            )
        ).one()
        output.append(_row(row))
    await session.commit()
    return output


def _validate_certification_evidence(manifest: dict[str, Any]) -> None:
    required = {"user_e2e", "admin_e2e", "security", "dead_end_scan", "quality_gate", "ui_gate"}
    if set(manifest) < required:
        raise VavError(
            "EXPERIENCE_CERTIFICATION_EVIDENCE_INCOMPLETE",
            "Experience certification evidence is incomplete.",
            status_code=409,
        )
    for code in required:
        evidence = manifest.get(code)
        if (
            not isinstance(evidence, dict)
            or evidence.get("status") != "accepted"
            or not isinstance(evidence.get("checksum_sha256"), str)
            or len(evidence["checksum_sha256"]) != 64
        ):
            raise VavError(
                "EXPERIENCE_CERTIFICATION_EVIDENCE_INVALID",
                f"Evidence gate '{code}' is not independently accepted and checksum-bound.",
                status_code=409,
            )


async def certify_closure(
    session: AsyncSession,
    actor_id: UUID,
    closure_id: UUID,
    decision: str,
    reason: str,
    evidence_manifest: dict[str, Any],
) -> dict[str, Any]:
    current = (
        await session.execute(
            text("SELECT * FROM experience_closure_checks WHERE id=:id FOR UPDATE"),
            {"id": closure_id},
        )
    ).first()
    if current is None:
        raise VavError(
            "EXPERIENCE_CLOSURE_NOT_FOUND", "The closure record was not found.", status_code=404
        )
    item = _row(current)
    if item["evaluated_by"] == actor_id:
        raise VavError(
            "EXPERIENCE_CERTIFICATION_SEPARATION_REQUIRED",
            "Certification requires an independent reviewer.",
            status_code=409,
        )
    if decision == "certify":
        if item["technical_status"] != "pass":
            raise VavError(
                "EXPERIENCE_TECHNICAL_GATE_FAILED",
                "A failed technical closure cannot be certified.",
                status_code=409,
            )
        _validate_certification_evidence(evidence_manifest)
        target = "certified"
    else:
        target = "rejected"
    row = (
        await session.execute(
            text(
                "UPDATE experience_closure_checks SET production_status=:status,certified_by=:actor,certified_at=now(),certification_reason=:reason WHERE id=:id RETURNING *"
            ),
            {"status": target, "actor": actor_id, "reason": reason, "id": closure_id},
        )
    ).one()
    result = _row(row)
    await _audit(
        session,
        actor_id,
        f"experience.closure.{target}",
        "experience_closure_check",
        closure_id,
        {"evidence_manifest_checksum": _checksum(evidence_manifest)},
        actor_type="admin",
    )
    await session.commit()
    return result


async def analytics(session: AsyncSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT journey_code,event_type,count(*) AS event_count FROM experience_analytics_events "
                "GROUP BY journey_code,event_type ORDER BY journey_code,event_type"
            )
        )
    ).mappings()
    return {
        "events": [dict(row) for row in rows],
        "sensitive_content_collected": False,
        "dimensions_allowlist": ["locale", "application_code", "step_code", "reason_code"],
    }


async def audit_log(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,actor_id,actor_type,action,subject_type,subject_id,context,occurred_at FROM audit_events WHERE action LIKE 'experience.%' ORDER BY occurred_at DESC LIMIT 500"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]
