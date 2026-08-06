# ruff: noqa: E501

"""Synchronize Batch 23 manifests without fabricating release certification."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]
CONFIG = ROOT / "config/experience"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((CONFIG / name).read_text(encoding="utf-8")))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


ENGLISH_HELP_TITLES = {
    "help.home": "Understand your home page",
    "help.tasks": "Task status guide",
    "help.journeys": "Journeys and next steps",
    "help.search": "Search scope",
    "help.account": "Account help",
    "help.activities": "Activity help",
    "help.courses": "Course help",
    "help.counseling": "Counseling help",
    "help.ai": "AI assistant boundaries",
    "help.matchmaking": "Matchmaking help",
    "help.relationships": "Relationship journey help",
    "help.membership": "Membership help",
    "help.privacy": "Privacy rights",
    "help.safety": "Safety support",
    "help.admin": "Experience operations help",
    "help.skill": "Skill console help",
}


async def seed_experience() -> None:
    await ensure_system_user()
    ia = _load("information-architecture.yaml")
    routes = _load("routes.yaml")
    tasks = _load("tasks.yaml")
    journeys = _load("journeys.yaml")
    handoffs = _load("handoffs.yaml")
    help_manifest = _load("help.yaml")
    manifest_checksum = _checksum({"ia": ia, "routes": routes})

    async with session_factory() as session:
        ia_id = await session.scalar(
            text(
                "INSERT INTO experience_ia_versions (version,status,manifest_checksum_sha256,activated_by,activated_at) "
                "VALUES (:version,'active',:checksum,:actor,now()) ON CONFLICT (version) DO UPDATE SET "
                "manifest_checksum_sha256=EXCLUDED.manifest_checksum_sha256 RETURNING id"
            ),
            {"version": ia["ia_version"], "checksum": manifest_checksum, "actor": SYSTEM_USER_ID},
        )
        for node in ia["nodes"]:
            await session.execute(
                text(
                    "INSERT INTO experience_ia_nodes (ia_version_id,node_code,parent_node_code,space,localized_labels,primary_route_code,secondary_route_codes,lifecycle,sort_order) "
                    "VALUES (:version,:code,:parent,:space,CAST(:labels AS jsonb),:primary,CAST(:secondary AS jsonb),'active',:order) "
                    "ON CONFLICT (ia_version_id,node_code) DO UPDATE SET parent_node_code=EXCLUDED.parent_node_code,space=EXCLUDED.space,localized_labels=EXCLUDED.localized_labels,"
                    "primary_route_code=EXCLUDED.primary_route_code,secondary_route_codes=EXCLUDED.secondary_route_codes,sort_order=EXCLUDED.sort_order"
                ),
                {
                    "version": ia_id,
                    "code": node["code"],
                    "parent": node.get("parent"),
                    "space": node["space"],
                    "labels": _json(node["labels"]),
                    "primary": node.get("primary_route"),
                    "secondary": _json(node.get("secondary_routes", [])),
                    "order": node.get("order", 0),
                },
            )
        for route in routes["routes"]:
            await session.execute(
                text(
                    "INSERT INTO experience_routes (route_code,application_code,route_name,route_path,page_code,ia_node_code,route_type,authentication_required,permission_codes,capability_codes,feature_flag,prerequisite_policy,fallback_route_code,breadcrumb_policy,help_context_code,lifecycle,critical,sort_order) "
                    "VALUES (:code,:app,:name,:path,:page,:node,:type,:auth,CAST(:permissions AS jsonb),CAST(:capabilities AS jsonb),:feature,CAST(:prerequisites AS jsonb),:fallback,CAST(:breadcrumbs AS jsonb),:help,'active',:critical,:order) "
                    "ON CONFLICT (route_code) DO UPDATE SET application_code=EXCLUDED.application_code,route_name=EXCLUDED.route_name,route_path=EXCLUDED.route_path,page_code=EXCLUDED.page_code,"
                    "ia_node_code=EXCLUDED.ia_node_code,route_type=EXCLUDED.route_type,authentication_required=EXCLUDED.authentication_required,permission_codes=EXCLUDED.permission_codes,"
                    "capability_codes=EXCLUDED.capability_codes,feature_flag=EXCLUDED.feature_flag,prerequisite_policy=EXCLUDED.prerequisite_policy,fallback_route_code=EXCLUDED.fallback_route_code,"
                    "breadcrumb_policy=EXCLUDED.breadcrumb_policy,help_context_code=EXCLUDED.help_context_code,lifecycle='active',critical=EXCLUDED.critical,sort_order=EXCLUDED.sort_order,updated_at=now()"
                ),
                {
                    "code": route["code"],
                    "app": route["app"],
                    "name": route["name"],
                    "path": route["path"],
                    "page": route["page"],
                    "node": route["node"],
                    "type": route.get("type", "page"),
                    "auth": route.get("auth", False),
                    "permissions": _json(route.get("permissions", [])),
                    "capabilities": _json(route.get("capabilities", [])),
                    "feature": route.get("feature"),
                    "prerequisites": _json(route.get("prerequisites", {})),
                    "fallback": route.get("fallback"),
                    "breadcrumbs": _json(route.get("breadcrumbs", [])),
                    "help": route.get("help"),
                    "critical": route.get("critical", False),
                    "order": route.get("order", 0),
                },
            )
        for task in tasks["tasks"]:
            title = {locale: task["title"] for locale in ("zh-CN", "zh-TW", "en")}
            description = {locale: task["description"] for locale in ("zh-CN", "zh-TW", "en")}
            await session.execute(
                text(
                    "INSERT INTO experience_task_definitions (task_code,version,source_module,title_i18n,description_i18n,priority,completion_policy,action_route_code,fallback_route_code,visibility_policy,active) "
                    "VALUES (:code,1,:module,CAST(:title AS jsonb),CAST(:description AS jsonb),:priority,CAST(:completion AS jsonb),:route,:fallback,'{}'::jsonb,true) "
                    "ON CONFLICT (task_code,version) DO UPDATE SET source_module=EXCLUDED.source_module,title_i18n=EXCLUDED.title_i18n,description_i18n=EXCLUDED.description_i18n,"
                    "priority=EXCLUDED.priority,completion_policy=EXCLUDED.completion_policy,action_route_code=EXCLUDED.action_route_code,fallback_route_code=EXCLUDED.fallback_route_code,active=true"
                ),
                {
                    "code": task["code"],
                    "module": task["module"],
                    "title": _json(title),
                    "description": _json(description),
                    "priority": task["priority"],
                    "completion": _json(task["completion"]),
                    "route": task["route"],
                    "fallback": task["fallback"],
                },
            )
        for journey in journeys["journeys"]:
            await session.execute(
                text(
                    "INSERT INTO experience_journey_definitions (journey_code,version,actor_type,step_manifest,transition_policy,completion_policy,cancellation_policy,status,activated_at) "
                    "VALUES (:code,1,'user',CAST(:steps AS jsonb),CAST(:transition AS jsonb),CAST(:completion AS jsonb),CAST(:cancellation AS jsonb),'active',now()) "
                    "ON CONFLICT (journey_code,version) DO UPDATE SET step_manifest=EXCLUDED.step_manifest,transition_policy=EXCLUDED.transition_policy,completion_policy=EXCLUDED.completion_policy,cancellation_policy=EXCLUDED.cancellation_policy,status='active'"
                ),
                {
                    "code": journey["code"],
                    "steps": _json(journey["steps"]),
                    "transition": _json({"authoritative_source_required": True}),
                    "completion": _json({"terminal_step_required": True}),
                    "cancellation": _json({"user_cancellable": True}),
                },
            )
        for handoff in handoffs["handoffs"]:
            await session.execute(
                text(
                    "INSERT INTO experience_handoff_definitions (handoff_code,source_module,target_module,context_schema,prerequisite_policy,completion_policy,return_route_code,failure_route_code,ttl_seconds,active) "
                    "VALUES (:code,:source,:target,CAST(:schema AS jsonb),CAST(:prerequisites AS jsonb),CAST(:completion AS jsonb),:return,:return,900,true) "
                    "ON CONFLICT (handoff_code) DO UPDATE SET source_module=EXCLUDED.source_module,target_module=EXCLUDED.target_module,context_schema=EXCLUDED.context_schema,"
                    "prerequisite_policy=EXCLUDED.prerequisite_policy,completion_policy=EXCLUDED.completion_policy,return_route_code=EXCLUDED.return_route_code,failure_route_code=EXCLUDED.failure_route_code,active=true"
                ),
                {
                    "code": handoff["code"],
                    "source": handoff["source"],
                    "target": handoff["target"],
                    "schema": _json(
                        {
                            "type": "object",
                            "allowed_keys": handoff["context_keys"],
                            "additionalProperties": False,
                        }
                    ),
                    "completion": _json(
                        {"target_route_code": handoff["target_route"], "domain_state_change": False}
                    ),
                    "prerequisites": _json(
                        {
                            "recheck": [
                                "identity",
                                "permission",
                                "privacy",
                                "safety",
                                "target_state",
                            ]
                        }
                    ),
                    "return": handoff["return_route"],
                },
            )
        for article in help_manifest["articles"]:
            for locale in ("zh-CN", "zh-TW", "en"):
                title_value = (
                    ENGLISH_HELP_TITLES.get(article["code"], article["title"])
                    if locale == "en"
                    else article["title"]
                )
                body_value = (
                    f"Contextual guidance for {title_value}. Domain state and user consent remain authoritative."
                    if locale == "en"
                    else article["body"]
                )
                await session.execute(
                    text(
                        "INSERT INTO experience_help_articles (article_code,version,category,route_codes,state_codes,actor_types,locale,title,body_markdown,status,published_at) "
                        "VALUES (:code,1,:category,CAST(:routes AS jsonb),'[]'::jsonb,'[\"anonymous\",\"member\",\"administrator\"]'::jsonb,:locale,:title,:body,'published',now()) "
                        "ON CONFLICT (article_code,version,locale) DO UPDATE SET category=EXCLUDED.category,route_codes=EXCLUDED.route_codes,title=EXCLUDED.title,body_markdown=EXCLUDED.body_markdown,status='published',published_at=COALESCE(experience_help_articles.published_at,now())"
                    ),
                    {
                        "code": article["code"],
                        "category": article["category"],
                        "routes": _json(article["routes"]),
                        "locale": locale,
                        "title": title_value,
                        "body": body_value,
                    },
                )
        public_documents = [
            ("public.activities", "activities", "活动", "查看可报名活动", "user.activities"),
            ("public.courses", "courses", "课程", "查看课程与学习服务", "user.courses"),
            ("public.counseling", "counseling", "辅导", "查看辅导服务", "user.counseling"),
            ("public.membership", "memberships", "会员", "查看会员计划与权益", "user.membership"),
            ("public.safety", "trust_safety", "安全支持", "举报、屏蔽与安全帮助", "user.safety"),
        ]
        for code, module, title_value, summary, route_code in public_documents:
            await session.execute(
                text(
                    "INSERT INTO experience_search_documents (document_code,source_module,source_entity_type,title,summary,locale,visibility,route_code,source_version,index_status) "
                    "VALUES (:code,:module,'approved_public_projection',:title,:summary,'zh-CN','public',:route,'1','active') "
                    "ON CONFLICT (document_code) DO UPDATE SET title=EXCLUDED.title,summary=EXCLUDED.summary,route_code=EXCLUDED.route_code,source_version=EXCLUDED.source_version,index_status='active',blocked=false,erased=false,indexed_at=now()"
                ),
                {
                    "code": code,
                    "module": module,
                    "title": title_value,
                    "summary": summary,
                    "route": route_code,
                },
            )
        await session.execute(
            text(
                "INSERT INTO quality_gate_definitions (gate_code,semantic_version,name,category,enforcement_level,condition_definition,required_evidence_types,applicable_release_types,applicable_modules,status,created_by) "
                "VALUES ('GATE-EXPERIENCE-CRITICAL-CLOSURE','1.0.0','Critical Capability Experience Closure','release','blocker',CAST(:condition AS jsonb),'[\"experience_closure\",\"dead_end_scan\",\"user_e2e\",\"admin_e2e\"]'::jsonb,'[\"standard\"]'::jsonb,'[\"experience\"]'::jsonb,'draft',:actor) "
                "ON CONFLICT (gate_code,semantic_version) DO UPDATE SET condition_definition=EXCLUDED.condition_definition,required_evidence_types=EXCLUDED.required_evidence_types"
            ),
            {
                "actor": SYSTEM_USER_ID,
                "condition": _json(
                    {
                        "metric": "critical_experience_closure_percent",
                        "operator": "eq",
                        "expected": 100,
                    }
                ),
            },
        )
        await session.commit()
    print(
        "Experience seed complete: "
        f"{len(ia['nodes'])} IA nodes, {len(routes['routes'])} routes, {len(tasks['tasks'])} task definitions, "
        f"{len(journeys['journeys'])} journeys, {len(handoffs['handoffs'])} handoffs and {len(help_manifest['articles']) * 3} localized help articles; production certification remains NOT_CERTIFIED"
    )


if __name__ == "__main__":
    asyncio.run(seed_experience())
