# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


async def seed_admin_platform() -> None:
    manifest = yaml.safe_load((ROOT / "config/admin-platform/manifest.yaml").read_text())
    async with session_factory() as session:
        for item in manifest["capabilities"]:
            command = item.get("command")
            await session.execute(
                text(
                    "INSERT INTO admin_capability_definitions (capability_code,semantic_version,display_name,description,owning_module,target_entity_type,capability_type,risk_level,required_permissions,required_purposes,step_up_authentication_required,approval_policy_code,idempotency_required,audit_level,admin_route_code,api_operation_id,command_code,lifecycle_status) VALUES (:code,'1.0.0',:name,:description,:owner,:entity,:type,:risk,CAST(:permissions AS jsonb),'[]'::jsonb,:step_up,:approval,:idempotency,:audit,:route,:operation,:command,'active') ON CONFLICT (capability_code,semantic_version) DO UPDATE SET display_name=EXCLUDED.display_name,owning_module=EXCLUDED.owning_module,target_entity_type=EXCLUDED.target_entity_type,capability_type=EXCLUDED.capability_type,risk_level=EXCLUDED.risk_level,required_permissions=EXCLUDED.required_permissions,step_up_authentication_required=EXCLUDED.step_up_authentication_required,approval_policy_code=EXCLUDED.approval_policy_code,idempotency_required=EXCLUDED.idempotency_required,audit_level=EXCLUDED.audit_level,admin_route_code=EXCLUDED.admin_route_code,api_operation_id=EXCLUDED.api_operation_id,command_code=EXCLUDED.command_code,lifecycle_status='active'"
                ),
                {
                    "code": item["code"],
                    "name": item["code"].replace("-", " ").title(),
                    "description": f"Controlled {item['type']} capability owned by {item['owner']}.",
                    "owner": item["owner"],
                    "entity": item["entity"],
                    "type": item["type"],
                    "risk": item["risk"],
                    "permissions": _json([item["permission"]]),
                    "step_up": item["risk"] in {"high", "critical"},
                    "approval": item.get("approval"),
                    "idempotency": item["type"] not in {"view", "search"},
                    "audit": "full_metadata"
                    if item["risk"] in {"high", "critical"}
                    else "standard",
                    "route": item["route"],
                    "operation": item["code"].casefold().replace("-", "_"),
                    "command": command,
                },
            )
        for policy in manifest["approval_policies"]:
            applicable = [
                item["code"]
                for item in manifest["capabilities"]
                if item.get("approval") == policy["code"]
            ]
            await session.execute(
                text(
                    "INSERT INTO admin_approval_policies (policy_code,semantic_version,applicable_capability_codes,approval_steps,separation_policy,validity_seconds,step_up_authentication_required,lifecycle_status) VALUES (:code,'1.0.0',CAST(:applicable AS jsonb),CAST(:steps AS jsonb),CAST(:separation AS jsonb),:validity,:step_up,'active') ON CONFLICT (policy_code,semantic_version) DO UPDATE SET applicable_capability_codes=EXCLUDED.applicable_capability_codes,approval_steps=EXCLUDED.approval_steps,separation_policy=EXCLUDED.separation_policy,validity_seconds=EXCLUDED.validity_seconds,step_up_authentication_required=EXCLUDED.step_up_authentication_required,lifecycle_status='active'"
                ),
                {
                    "code": policy["code"],
                    "applicable": _json(applicable),
                    "steps": _json({"reviewers": policy["steps"], "distinct_reviewers": True}),
                    "separation": _json(
                        {"requester_cannot_approve": True, "distinct_reviewers": True}
                    ),
                    "validity": policy["validity_seconds"],
                    "step_up": policy["step_up"],
                },
            )
        for query in manifest["queries"]:
            await session.execute(
                text(
                    "INSERT INTO admin_query_definitions (query_code,semantic_version,owning_module,target_entity_type,filter_schema,sort_schema,column_schema,maximum_page_size,export_policy,required_permissions,lifecycle_status) VALUES (:code,'1.0.0',:owner,:entity,CAST(:filters AS jsonb),CAST(:sorts AS jsonb),CAST(:columns AS jsonb),:maximum,CAST(:export AS jsonb),CAST(:permissions AS jsonb),'active') ON CONFLICT (query_code,semantic_version) DO UPDATE SET filter_schema=EXCLUDED.filter_schema,sort_schema=EXCLUDED.sort_schema,column_schema=EXCLUDED.column_schema,maximum_page_size=EXCLUDED.maximum_page_size,required_permissions=EXCLUDED.required_permissions,lifecycle_status='active'"
                ),
                {
                    "code": query["code"],
                    "owner": query["owner"],
                    "entity": query["entity"],
                    "filters": _json({"fields": query["filters"]}),
                    "sorts": _json({"fields": query["sorts"]}),
                    "columns": _json({"fields": query["columns"]}),
                    "maximum": query["maximum_page_size"],
                    "permissions": _json([query["permission"]]),
                    "export": _json({"enabled": False}),
                },
            )
        for item in manifest["bulk_operations"]:
            await session.execute(
                text(
                    "INSERT INTO admin_bulk_operation_definitions (operation_code,semantic_version,owning_module,target_entity_type,command_code,eligibility_policy,maximum_batch_size,risk_level,dry_run_required,approval_policy_code,idempotency_policy,retry_policy,lifecycle_status) VALUES (:code,'1.0.0',:owner,:entity,:command,CAST(:eligibility AS jsonb),:maximum,:risk,true,:approval,CAST(:idempotency AS jsonb),CAST(:retry AS jsonb),'active') ON CONFLICT (operation_code,semantic_version) DO UPDATE SET command_code=EXCLUDED.command_code,maximum_batch_size=EXCLUDED.maximum_batch_size,risk_level=EXCLUDED.risk_level,approval_policy_code=EXCLUDED.approval_policy_code,lifecycle_status='active'"
                ),
                {
                    **item,
                    "approval": item.get("approval"),
                    "eligibility": _json({"revalidate_each_item": True}),
                    "idempotency": _json({"scope": "selection_and_parameters"}),
                    "retry": _json({"failed_items_only": True, "maximum_attempts": 3}),
                },
            )
        for item in manifest["field_policies"]:
            await session.execute(
                text(
                    "INSERT INTO admin_field_access_policies (policy_code,semantic_version,asset_code,field_path,classification,allowed_permissions,allowed_purposes,default_masking_rule,reveal_allowed,step_up_required,reveal_duration_seconds,export_allowed,lifecycle_status) VALUES (:code,'1.0.0',:asset,:field,:classification,CAST(:permissions AS jsonb),CAST(:purposes AS jsonb),:masking,:reveal,:step_up,:ttl,false,'active') ON CONFLICT (policy_code,semantic_version) DO UPDATE SET allowed_permissions=EXCLUDED.allowed_permissions,allowed_purposes=EXCLUDED.allowed_purposes,default_masking_rule=EXCLUDED.default_masking_rule,reveal_allowed=EXCLUDED.reveal_allowed,step_up_required=EXCLUDED.step_up_required,reveal_duration_seconds=EXCLUDED.reveal_duration_seconds,lifecycle_status='active'"
                ),
                {
                    **item,
                    "permissions": _json([item["permission"]]),
                    "purposes": _json([item["purpose"]]),
                },
            )
        entity_types = sorted({item["entity"] for item in manifest["capabilities"]})
        for entity_type in entity_types:
            sections = [
                {
                    "code": "summary",
                    "title": "Status summary",
                    "module": next(
                        item["owner"]
                        for item in manifest["capabilities"]
                        if item["entity"] == entity_type
                    ),
                    "permissions": [
                        next(
                            item["permission"]
                            for item in manifest["capabilities"]
                            if item["entity"] == entity_type
                        )
                    ],
                },
                {
                    "code": "audit",
                    "title": "Audit timeline",
                    "module": "admin_platform",
                    "permissions": ["admin.audit.read"],
                },
            ]
            await session.execute(
                text(
                    "INSERT INTO admin_entity_view_definitions (entity_view_code,semantic_version,entity_type,section_manifest,relation_manifest,timeline_manifest,operation_manifest,default_masking_policy_code,lifecycle_status) VALUES (:code,'1.0.0',:entity,CAST(:sections AS jsonb),'[]'::jsonb,CAST(:timeline AS jsonb),'[]'::jsonb,'ADMIN-DEFAULT-MASKING','active') ON CONFLICT (entity_view_code,semantic_version) DO UPDATE SET section_manifest=EXCLUDED.section_manifest,lifecycle_status='active'"
                ),
                {
                    "code": f"ADMIN-ENTITY-{entity_type.upper().replace('_', '-')}",
                    "entity": entity_type,
                    "sections": _json(sections),
                    "timeline": _json({"preserve_event_received_processed_times": True}),
                },
            )
        namespaces = [
            ("admin.workbench.sla", "admin_platform", [], "APPROVAL-HIGH-RISK"),
            (
                "recommendations.policy",
                "recommendations",
                ["provider_token"],
                "APPROVAL-CRITICAL-TWO-PERSON",
            ),
            ("notifications.routing", "notifications", ["provider_secret"], "APPROVAL-HIGH-RISK"),
        ]
        for code, owner, secrets, approval in namespaces:
            await session.execute(
                text(
                    "INSERT INTO admin_configuration_namespaces (namespace_code,owning_module,display_name,description,schema_definition,environment_scope,approval_policy_code,secret_fields,lifecycle_status) VALUES (:code,:owner,:name,:description,CAST(:schema AS jsonb),CAST(:environments AS jsonb),:approval,CAST(:secrets AS jsonb),'active') ON CONFLICT (namespace_code) DO UPDATE SET schema_definition=EXCLUDED.schema_definition,approval_policy_code=EXCLUDED.approval_policy_code,secret_fields=EXCLUDED.secret_fields,lifecycle_status='active'"
                ),
                {
                    "code": code,
                    "owner": owner,
                    "name": code.replace(".", " ").title(),
                    "description": "Versioned non-secret administration configuration.",
                    "approval": approval,
                    "secrets": _json(secrets),
                    "schema": _json({"type": "object"}),
                    "environments": _json(["local", "ci", "staging", "production"]),
                },
            )
        await session.commit()
    print(
        f"Admin platform seed complete: {len(manifest['capabilities'])} capabilities, {len(entity_types)} entity views, {len(manifest['field_policies'])} field policies; production remains NOT_CERTIFIED"
    )


if __name__ == "__main__":
    asyncio.run(seed_admin_platform())
