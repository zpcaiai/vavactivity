"""Populate staging/test administration surfaces for ``admin@vav.com``.

The seed is deterministic, repeatable and deliberately refuses production/DR.  It
does not create or reset an administrator password: bootstrap the account through
``vav.cli.create_super_admin`` first, then run this command to attach synthetic
operational data to the existing super administrator.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.cli.seed_admin_platform import seed_admin_platform
from vav.cli.seed_data_governance import seed_data_governance
from vav.cli.seed_design_system import seed_design_system
from vav.cli.seed_knowledge import seed_knowledge
from vav.cli.seed_privacy_inventory import seed_privacy_inventory
from vav.cli.seed_process_governance import seed_process_governance
from vav.cli.seed_quality import seed_quality
from vav.cli.seed_test_showcase import seed_test_showcase
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.privacy.crypto import encrypt_private

ADMIN_EMAIL = "admin@vav.com"
PROTECTED_ENVIRONMENTS = frozenset({"production", "dr"})
SHOWCASE_PREFIX = "admin-showcase"
ADMIN_PAGE_COVERAGE = {
    "administrators": 3,
    "admin_sessions": 3,
    "admin_invitations": 3,
    "security_audit": 3,
    "capabilities": 3,
    "work_items": 3,
    "saved_views": 3,
    "bulk_jobs": 3,
    "approvals": 3,
    "exceptions": 3,
    "configurations": 3,
    "field_policies": 3,
    "reveal_history": 3,
    "certifications": 3,
    "operation_audit": 3,
    "quality_requirements": 3,
    "design_components": 3,
    "experience_routes": 3,
    "process_definitions": 3,
    "data_assets": 3,
    "privacy_assets": 3,
    "knowledge_documents": 3,
    "system_feature_flags": 3,
    "system_releases": 3,
    "system_jobs": 3,
    "system_backups": 3,
    "system_restore_drills": 3,
    "system_capacity": 3,
    "skill_publishers": 3,
    "registered_skills": 3,
    "skill_dependencies": 3,
    "skill_installations": 3,
    "skill_executions": 3,
    "skill_marketplace": 3,
    "skill_reviews": 3,
    "skill_incidents": 3,
}


def _id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"vav:{SHOWCASE_PREFIX}:{key}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def _admin_identity(session: AsyncSession) -> tuple[UUID, UUID]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT u.id,r.id role_id FROM users u "
                    "JOIN user_roles ur ON ur.user_id=u.id AND ur.revoked_at IS NULL "
                    "JOIN roles r ON r.id=ur.role_id "
                    "WHERE lower(u.email)=:email AND u.status='active' AND r.code='super_admin'"
                ),
                {"email": ADMIN_EMAIL},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RuntimeError(
            f"{ADMIN_EMAIL} must be an active super administrator. Run "
            f"`python -m vav.cli.create_super_admin --email {ADMIN_EMAIL}` securely first; "
            "this showcase seed never creates or resets administrator credentials."
        )
    return cast(UUID, row["id"]), cast(UUID, row["role_id"])


async def _seed_identity_surfaces(
    session: AsyncSession, admin_id: UUID, super_admin_role_id: UUID
) -> None:
    """Seed three safe display rows for each administrator access/audit list."""

    now = datetime.now(UTC)
    placeholder_ids: list[UUID] = []
    for index in range(1, 3):
        user_id = _id(f"placeholder-admin:{index}")
        placeholder_ids.append(user_id)
        await session.execute(
            text(
                "INSERT INTO users (id,email,display_email,password_hash,status,email_verified_at,preferred_locale,timezone) "
                "VALUES (:id,:email,:email,NULL,'suspended',now(),'zh-CN','Asia/Shanghai') "
                "ON CONFLICT (id) DO UPDATE SET status='suspended',password_hash=NULL,updated_at=now()"
            ),
            {"id": user_id, "email": f"admin-showcase-operator-{index}@example.invalid"},
        )
        await session.execute(
            text(
                "INSERT INTO user_roles (user_id,role_id,granted_by,grant_reason) "
                "VALUES (:user,:role,:admin,'Synthetic staging administrator display record') "
                "ON CONFLICT (user_id,role_id) DO UPDATE SET revoked_at=NULL,revoked_by=NULL,revoke_reason=NULL"
            ),
            {"user": user_id, "role": super_admin_role_id, "admin": admin_id},
        )

    devices = ("Safari · macOS", "Chrome · Windows", "Mobile Safari · iPhone")
    for index, device in enumerate(devices, start=1):
        session_id = _id(f"session:{index}")
        await session.execute(
            text(
                "INSERT INTO auth_sessions (id,user_id,session_family_id,refresh_token_hash,audience,status,issued_at,expires_at,last_used_at,device_name,user_agent_hash,ip_address_hash) "
                "VALUES (:id,:admin,:family,:token,'vav-admin','active',:issued,:expires,:used,:device,:ua,:ip) "
                "ON CONFLICT (id) DO UPDATE SET status='active',expires_at=EXCLUDED.expires_at,last_used_at=EXCLUDED.last_used_at,device_name=EXCLUDED.device_name,updated_at=now()"
            ),
            {
                "id": session_id,
                "admin": admin_id,
                "family": _id(f"session-family:{index}"),
                "token": hashlib.sha256(f"{SHOWCASE_PREFIX}:refresh:{index}".encode()).hexdigest(),
                "issued": now - timedelta(days=index),
                "expires": now + timedelta(days=14 + index),
                "used": now - timedelta(hours=index),
                "device": device,
                "ua": hashlib.sha256(f"{device}:ua".encode()).hexdigest(),
                "ip": hashlib.sha256(f"{SHOWCASE_PREFIX}:ip:{index}".encode()).hexdigest(),
            },
        )

    invitation_states = ("pending", "accepted", "revoked")
    for index, state in enumerate(invitation_states, start=1):
        invitation_id = _id(f"invitation:{index}")
        await session.execute(
            text(
                "INSERT INTO admin_invitations (id,email,token_hash,proposed_role_ids,invited_by,reason,expires_at,accepted_at,revoked_at) "
                "VALUES (:id,:email,:token,CAST(:roles AS jsonb),:admin,:reason,:expires,:accepted,:revoked) "
                "ON CONFLICT (id) DO UPDATE SET expires_at=EXCLUDED.expires_at,accepted_at=EXCLUDED.accepted_at,revoked_at=EXCLUDED.revoked_at"
            ),
            {
                "id": invitation_id,
                "email": f"admin-showcase-invite-{index}@example.invalid",
                "token": hashlib.sha256(f"{SHOWCASE_PREFIX}:invite:{index}".encode()).hexdigest(),
                "roles": _json([str(super_admin_role_id)]),
                "admin": admin_id,
                "reason": "Synthetic staging invitation for administration UI display",
                "expires": now + timedelta(days=7),
                "accepted": now - timedelta(days=1) if state == "accepted" else None,
                "revoked": now - timedelta(hours=12) if state == "revoked" else None,
            },
        )

    event_specs = (
        ("admin.showcase.login", "info", "Administrator login display event"),
        ("admin.showcase.permission_review", "warning", "Permission review display event"),
        ("admin.showcase.session_review", "info", "Session review display event"),
    )
    for index, (event_type, severity, reason) in enumerate(event_specs, start=1):
        await session.execute(
            text(
                "INSERT INTO security_audit_events (id,event_type,severity,actor_type,actor_user_id,actor_session_id,target_type,target_id,request_id,reason,metadata,ip_address_hash,user_agent_hash,occurred_at) "
                "VALUES (:id,:type,:severity,'admin',:admin,:session,'user',:admin,:request,:reason,CAST(:metadata AS jsonb),:ip,:ua,:occurred) "
                "ON CONFLICT (id) DO UPDATE SET occurred_at=EXCLUDED.occurred_at,reason=EXCLUDED.reason"
            ),
            {
                "id": _id(f"security-event:{index}"),
                "type": event_type,
                "severity": severity,
                "admin": admin_id,
                "session": _id(f"session:{index}"),
                "request": _id(f"request:{index}"),
                "reason": reason,
                "metadata": _json({"fixture": SHOWCASE_PREFIX, "sequence": index}),
                "ip": hashlib.sha256(f"{SHOWCASE_PREFIX}:event-ip:{index}".encode()).hexdigest(),
                "ua": hashlib.sha256(f"{SHOWCASE_PREFIX}:event-ua:{index}".encode()).hexdigest(),
                "occurred": now - timedelta(minutes=index * 20),
            },
        )


async def _seed_admin_platform_surfaces(session: AsyncSession, admin_id: UUID) -> None:
    query_rows = list(
        (
            await session.execute(
                text(
                    "SELECT query_code FROM admin_query_definitions WHERE lifecycle_status='active' ORDER BY query_code LIMIT 3"
                )
            )
        ).scalars()
    )
    operation_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,operation_code FROM admin_bulk_operation_definitions WHERE lifecycle_status='active' ORDER BY operation_code LIMIT 3"
                )
            )
        ).mappings()
    )
    policy_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,policy_code FROM admin_approval_policies WHERE lifecycle_status='active' ORDER BY policy_code LIMIT 3"
                )
            )
        ).mappings()
    )
    namespace_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,namespace_code FROM admin_configuration_namespaces WHERE lifecycle_status='active' ORDER BY namespace_code LIMIT 3"
                )
            )
        ).mappings()
    )
    field_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,policy_code FROM admin_field_access_policies WHERE lifecycle_status='active' ORDER BY policy_code LIMIT 3"
                )
            )
        ).mappings()
    )
    if not query_rows or not operation_rows or len(namespace_rows) < 3 or len(field_rows) < 3:
        raise RuntimeError(
            "Administration reference definitions are incomplete; run seed_admin_platform first."
        )
    if not policy_rows:
        raise RuntimeError(
            "Administration approval policies are missing; run seed_admin_platform first."
        )

    now = datetime.now(UTC)
    for index in range(1, 4):
        entity_id = _id(f"entity:{index}")
        query_code = query_rows[(index - 1) % len(query_rows)]
        operation = operation_rows[(index - 1) % len(operation_rows)]
        policy = policy_rows[(index - 1) % len(policy_rows)]
        namespace = namespace_rows[index - 1]
        field_policy = field_rows[index - 1]

        await session.execute(
            text(
                "INSERT INTO admin_saved_views (id,owner_user_id,query_code,name,description,filter_definition,sort_definition,column_definition,visibility,is_default) "
                "VALUES (:id,:admin,:query,:name,:description,'{}'::jsonb,'{}'::jsonb,'[]'::jsonb,'private',false) "
                "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description,updated_at=now()"
            ),
            {
                "id": _id(f"saved-view:{index}"),
                "admin": admin_id,
                "query": query_code,
                "name": f"展示视图 {index}",
                "description": "Synthetic staging saved view",
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_work_items (id,work_item_code,work_item_type,source_module,source_entity_type,source_entity_id,status,priority,title_snapshot,safe_summary,assigned_to,required_capability_code,action_route_code,deduplication_key,due_at) "
                "VALUES (:id,:code,'showcase','admin_platform','showcase_record',:entity,:status,:priority,:title,:summary,:admin,NULL,'ROUTE-ADMIN-WORKBENCH',:dedupe,:due) "
                "ON CONFLICT (deduplication_key) DO UPDATE SET status=EXCLUDED.status,priority=EXCLUDED.priority,title_snapshot=EXCLUDED.title_snapshot,due_at=EXCLUDED.due_at"
            ),
            {
                "id": _id(f"work-item:{index}"),
                "code": f"ADMIN-SHOWCASE-{index:03d}",
                "entity": entity_id,
                "status": ("available", "assigned", "in_progress")[index - 1],
                "priority": ("normal", "high", "critical")[index - 1],
                "title": f"管理员展示待办 {index}",
                "summary": "Synthetic staging work item",
                "admin": admin_id,
                "dedupe": f"{SHOWCASE_PREFIX}:work-item:{index}",
                "due": now + timedelta(hours=index),
            },
        )
        encrypted_parameters = {
            "ciphertext": encrypt_private({"fixture": SHOWCASE_PREFIX, "sequence": index})
        }
        await session.execute(
            text(
                "INSERT INTO admin_bulk_jobs (id,operation_definition_id,requested_by,selection_type,selection_snapshot,input_parameters_encrypted,input_hash,dry_run,status,total_count,eligible_count,succeeded_count,idempotency_key) "
                "VALUES (:id,:operation,:admin,'explicit_ids',CAST(:selection AS jsonb),CAST(:parameters AS jsonb),:hash,true,:status,3,3,:succeeded,:key) "
                "ON CONFLICT (idempotency_key) DO UPDATE SET status=EXCLUDED.status,succeeded_count=EXCLUDED.succeeded_count"
            ),
            {
                "id": _id(f"bulk-job:{index}"),
                "operation": operation["id"],
                "admin": admin_id,
                "selection": _json([{"entity_id": str(entity_id), "expected_version": 1}]),
                "parameters": _json(encrypted_parameters),
                "hash": hashlib.sha256(f"bulk:{index}".encode()).hexdigest(),
                "status": ("planned", "dry_run_completed", "completed")[index - 1],
                "succeeded": 3 if index == 3 else 0,
                "key": f"{SHOWCASE_PREFIX}:bulk:{index}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_approval_requests (id,approval_number,policy_id,requested_capability_code,target_entity_type,target_entity_id,requested_by,request_payload_encrypted,request_hash,status,business_state_snapshot,expires_at) "
                "VALUES (:id,:number,:policy,'ADMIN-SHOWCASE-REVIEW','showcase_record',:entity,:admin,CAST(:payload AS jsonb),:hash,:status,'{}'::jsonb,:expires) "
                "ON CONFLICT (approval_number) DO UPDATE SET status=EXCLUDED.status,expires_at=EXCLUDED.expires_at"
            ),
            {
                "id": _id(f"approval:{index}"),
                "number": f"APR-SHOWCASE-{index:03d}",
                "policy": policy["id"],
                "entity": entity_id,
                "admin": admin_id,
                "payload": _json(encrypted_parameters),
                "hash": hashlib.sha256(f"approval:{index}".encode()).hexdigest(),
                "status": ("submitted", "in_review", "approved")[index - 1],
                "expires": now + timedelta(days=1),
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_exception_items (id,exception_code,exception_type,source_module,source_reference_type,source_reference_id,severity,status,safe_summary,evidence_reference,allowed_diagnostic_codes,allowed_repair_codes,assigned_team,assigned_to,due_at) "
                "VALUES (:id,:code,'showcase_gap','admin_platform','showcase_record',:entity,:severity,:status,:summary,'{}'::jsonb,'[\"admin.inspect\"]'::jsonb,'[\"admin.repair\"]'::jsonb,'platform-operations',:admin,:due) "
                "ON CONFLICT (exception_code) DO UPDATE SET status=EXCLUDED.status,severity=EXCLUDED.severity,due_at=EXCLUDED.due_at"
            ),
            {
                "id": _id(f"exception:{index}"),
                "code": f"ADMIN-SHOWCASE-EX-{index:03d}",
                "entity": entity_id,
                "severity": ("low", "high", "critical")[index - 1],
                "status": ("open", "diagnosing", "verification_required")[index - 1],
                "summary": f"Synthetic administration exception {index}",
                "admin": admin_id,
                "due": now + timedelta(hours=index),
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_configuration_versions (id,namespace_id,environment,version_number,semantic_version,configuration_encrypted,non_secret_checksum,status,created_by) "
                "VALUES (:id,:namespace,'staging',:version,:semantic,CAST(:configuration AS jsonb),:checksum,:status,:admin) "
                "ON CONFLICT (namespace_id,environment,version_number) DO UPDATE SET semantic_version=EXCLUDED.semantic_version,status=EXCLUDED.status"
            ),
            {
                "id": _id(f"configuration:{index}"),
                "namespace": namespace["id"],
                "version": 900 + index,
                "semantic": f"0.0.{index}-showcase",
                "configuration": _json(encrypted_parameters),
                "checksum": hashlib.sha256(f"configuration:{index}".encode()).hexdigest(),
                "status": ("draft", "review_required", "active")[index - 1],
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_sensitive_reveal_grants (id,admin_user_id,policy_id,entity_type,entity_id,purpose_code,reason_encrypted,status,issued_at,expires_at,revoked_at) "
                "VALUES (:id,:admin,:policy,'showcase_record',:entity,'customer_support',:reason,:status,:issued,:expires,:revoked) "
                "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,expires_at=EXCLUDED.expires_at,revoked_at=EXCLUDED.revoked_at"
            ),
            {
                "id": _id(f"reveal:{index}"),
                "admin": admin_id,
                "policy": field_policy["id"],
                "entity": entity_id,
                "reason": encrypt_private(f"Synthetic staging reveal history {index}"),
                "status": ("active", "expired", "revoked")[index - 1],
                "issued": now - timedelta(days=index),
                "expires": now + timedelta(minutes=30)
                if index == 1
                else now - timedelta(hours=index),
                "revoked": now - timedelta(hours=1) if index == 3 else None,
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_operation_receipts (id,capability_code,admin_user_id,target_entity_type,target_entity_id,status,safe_result_summary,request_id,trace_id,executed_at) "
                "VALUES (:id,'ADMIN-SHOWCASE-REVIEW',:admin,'showcase_record',:entity,:status,:summary,:request,:trace,:executed) "
                "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,safe_result_summary=EXCLUDED.safe_result_summary,executed_at=EXCLUDED.executed_at"
            ),
            {
                "id": _id(f"receipt:{index}"),
                "admin": admin_id,
                "entity": entity_id,
                "status": ("succeeded", "denied", "failed")[index - 1],
                "summary": f"Synthetic administration operation {index}",
                "request": _id(f"operation-request:{index}"),
                "trace": f"admin-showcase-trace-{index}",
                "executed": now - timedelta(hours=index),
            },
        )
        await session.execute(
            text(
                "INSERT INTO admin_domain_certifications (id,business_domain,release_version,environment,required_capability_count,implemented_capability_count,verified_capability_count,observable_coverage_ratio,operable_coverage_ratio,approval_coverage_ratio,recovery_coverage_ratio,masking_coverage_ratio,audit_coverage_ratio,unresolved_critical_gaps,status,evidence_ids,evaluated_by) "
                "VALUES (:id,:domain,'showcase-1.0','staging',3,3,:verified,:ratio,:ratio,:ratio,:ratio,:ratio,:ratio,:gaps,:status,CAST(:evidence AS jsonb),:admin) "
                "ON CONFLICT (business_domain,release_version,environment) DO UPDATE SET verified_capability_count=EXCLUDED.verified_capability_count,status=EXCLUDED.status,evaluated_at=now()"
            ),
            {
                "id": _id(f"certification:{index}"),
                "domain": ("content", "commerce", "identity")[index - 1],
                "verified": index,
                "ratio": index / 3,
                "gaps": 3 - index,
                "status": ("not_certified", "eligible", "certified")[index - 1],
                "evidence": _json([str(_id(f"evidence:{index}"))]),
                "admin": admin_id,
            },
        )


async def _seed_system_surfaces(session: AsyncSession, admin_id: UUID) -> None:
    now = datetime.now(UTC)
    for index in range(1, 4):
        release = f"showcase-0.0.{index}"
        backup_id = _id(f"system-backup:{index}")
        await session.execute(
            text(
                "INSERT INTO system_feature_flags (id,flag_code,status,targeting_policy,default_value,description,created_by) VALUES (:id,:code,:status,'{}'::jsonb,CAST(:value AS jsonb),'Synthetic staging feature flag',:admin) ON CONFLICT (flag_code) DO UPDATE SET status=EXCLUDED.status,default_value=EXCLUDED.default_value,updated_at=now()"
            ),
            {
                "id": _id(f"system-flag:{index}"),
                "code": f"admin_showcase_feature_{index}",
                "status": ("draft", "approved", "active")[index - 1],
                "value": _json(index == 3),
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO system_release_records (id,release_version,git_commit,status,image_digests,database_revision,contract_checksums,configuration_fingerprint,evidence_manifest,created_by) VALUES (:id,:release,:commit,:status,'{}'::jsonb,'showcase-head','{}'::jsonb,'{}'::jsonb,'{\"fixture\":true}'::jsonb,:admin) ON CONFLICT (release_version) DO UPDATE SET status=EXCLUDED.status,updated_at=now()"
            ),
            {
                "id": _id(f"system-release:{index}"),
                "release": release,
                "commit": hashlib.sha256(release.encode()).hexdigest(),
                "status": ("candidate", "staging", "active")[index - 1],
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO system_backfill_jobs (id,job_code,release_version,status,cursor_snapshot,processed_count,failed_count,idempotency_namespace,started_at,completed_at) VALUES (:id,:code,:release,:status,'{}'::jsonb,:processed,0,:namespace,:started,:completed) ON CONFLICT (job_code,release_version) DO UPDATE SET status=EXCLUDED.status,processed_count=EXCLUDED.processed_count,updated_at=now()"
            ),
            {
                "id": _id(f"system-job:{index}"),
                "code": f"admin-showcase-job-{index}",
                "release": release,
                "status": ("pending", "running", "completed")[index - 1],
                "processed": index * 100,
                "namespace": f"{SHOWCASE_PREFIX}:system-job:{index}",
                "started": now - timedelta(hours=index),
                "completed": now if index == 3 else None,
            },
        )
        await session.execute(
            text(
                "INSERT INTO system_backup_records (id,backup_type,environment,status,started_at,completed_at,backup_reference_encrypted,checksum_manifest,source_release_version,source_database_revision,verified_at,expires_at) VALUES (:id,:type,'staging',:status,:started,:completed,:reference,CAST(:checksum AS jsonb),:release,'showcase-head',:verified,:expires) ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,completed_at=EXCLUDED.completed_at,verified_at=EXCLUDED.verified_at"
            ),
            {
                "id": backup_id,
                "type": ("postgres_full", "object_storage", "configuration")[index - 1],
                "status": ("started", "completed", "verified")[index - 1],
                "started": now - timedelta(days=index),
                "completed": now if index > 1 else None,
                "reference": encrypt_private(f"showcase://backup/{index}"),
                "checksum": _json(
                    {"sha256": hashlib.sha256(f"backup:{index}".encode()).hexdigest()}
                ),
                "release": release,
                "verified": now if index == 3 else None,
                "expires": now + timedelta(days=30),
            },
        )
        await session.execute(
            text(
                "INSERT INTO system_restore_drills (id,drill_code,environment,backup_record_id,status,target_release_version,target_database_revision,verification_manifest,failure_summary,started_at,completed_at) VALUES (:id,:code,'staging',:backup,:status,:release,'showcase-head','{\"fixture\":true}'::jsonb,:failure,:started,:completed) ON CONFLICT (drill_code) DO UPDATE SET status=EXCLUDED.status,completed_at=EXCLUDED.completed_at"
            ),
            {
                "id": _id(f"system-restore:{index}"),
                "code": f"ADMIN-SHOWCASE-DRILL-{index}",
                "backup": backup_id,
                "status": ("started", "passed", "failed")[index - 1],
                "release": release,
                "failure": "Synthetic recovery check" if index == 3 else None,
                "started": now - timedelta(hours=index),
                "completed": now if index > 1 else None,
            },
        )
        await session.execute(
            text(
                "INSERT INTO system_capacity_baselines (id,release_version,environment,scenario_code,infrastructure_snapshot,load_snapshot,result_metrics,status,tested_at) VALUES (:id,:release,'staging',:scenario,'{}'::jsonb,CAST(:load AS jsonb),CAST(:metrics AS jsonb),:status,:tested) ON CONFLICT (release_version,environment,scenario_code) DO UPDATE SET result_metrics=EXCLUDED.result_metrics,status=EXCLUDED.status,tested_at=EXCLUDED.tested_at"
            ),
            {
                "id": _id(f"system-capacity:{index}"),
                "release": release,
                "scenario": f"admin-showcase-load-{index}",
                "load": _json({"requests_per_second": index * 25}),
                "metrics": _json({"p95_ms": 100 + index * 10}),
                "status": ("not_certified", "passed", "failed")[index - 1],
                "tested": now - timedelta(days=index),
            },
        )


async def _seed_skill_surfaces(session: AsyncSession, admin_id: UUID) -> None:
    now = datetime.now(UTC)
    schema = _json({"type": "object", "additionalProperties": False})
    for index in range(1, 4):
        publisher_id = _id(f"skill-publisher:{index}")
        skill_id = _id(f"skill:{index}")
        version_id = _id(f"skill-version:{index}")
        installation_id = _id(f"skill-installation:{index}")
        listing_id = _id(f"skill-listing:{index}")
        checksum = hashlib.sha256(f"skill:{index}".encode()).hexdigest()
        await session.execute(
            text(
                "INSERT INTO skill_publishers (id,publisher_code,display_name,publisher_type,verification_status,signing_key_manifest,status,created_by,verified_at) VALUES (:id,:code,:name,:type,:verification,'{}'::jsonb,'active',:admin,:verified) ON CONFLICT (publisher_code) DO UPDATE SET display_name=EXCLUDED.display_name,verification_status=EXCLUDED.verification_status,status='active'"
            ),
            {
                "id": publisher_id,
                "code": f"admin-showcase-publisher-{index}",
                "name": f"展示发布者 {index}",
                "type": ("official", "verified_partner", "community")[index - 1],
                "verification": ("verified", "pending", "verified")[index - 1],
                "admin": admin_id,
                "verified": now if index != 2 else None,
            },
        )
        await session.execute(
            text(
                "INSERT INTO registered_skills (id,skill_name,publisher_id,display_name,description,skill_type,visibility,trust_level,lifecycle_status) VALUES (:id,:name,:publisher,:display,'Synthetic staging Skill catalog record','workflow',:visibility,:trust,'active') ON CONFLICT (skill_name) DO UPDATE SET display_name=EXCLUDED.display_name,lifecycle_status='active',updated_at=now()"
            ),
            {
                "id": skill_id,
                "name": f"admin-showcase-skill-{index}",
                "publisher": publisher_id,
                "display": f"展示 Skill {index}",
                "visibility": ("builtin", "organization_private", "marketplace_public")[index - 1],
                "trust": ("builtin_trusted", "verified_publisher", "community_reviewed")[index - 1],
            },
        )
        await session.execute(
            text(
                "INSERT INTO registered_skill_versions (id,registered_skill_id,semantic_version,manifest_version,runtime_api_version,manifest,manifest_checksum,package_reference_encrypted,package_checksum,signature_status,security_status,review_status,compatibility_status,published_at,input_schema,output_schema,error_schema,submitted_by) VALUES (:id,:skill,'1.0.0','1','1',CAST(:manifest AS jsonb),:checksum,:package,:checksum,'verified','passed','approved','compatible',now(),CAST(:schema AS jsonb),CAST(:schema AS jsonb),CAST(:schema AS jsonb),:admin) ON CONFLICT (registered_skill_id,semantic_version) DO UPDATE SET security_status='passed',review_status='approved',compatibility_status='compatible'"
            ),
            {
                "id": version_id,
                "skill": skill_id,
                "manifest": _json({"name": f"admin-showcase-skill-{index}", "fixture": True}),
                "checksum": checksum,
                "package": encrypt_private(f"showcase://skill/{index}"),
                "schema": schema,
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "UPDATE registered_skills SET current_stable_version_id=:version,latest_version_id=:version WHERE id=:skill"
            ),
            {"version": version_id, "skill": skill_id},
        )
        await session.execute(
            text(
                "INSERT INTO skill_dependencies (id,skill_version_id,dependency_type,dependency_name,version_constraint,resolution_status) VALUES (:id,:version,:type,:name,'>=1','resolved') ON CONFLICT (skill_version_id,dependency_type,dependency_name) DO UPDATE SET resolution_status='resolved'"
            ),
            {
                "id": _id(f"skill-dependency:{index}"),
                "version": version_id,
                "type": ("platform", "runtime", "provider")[index - 1],
                "name": f"admin-showcase-dependency-{index}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO skill_installations (id,registered_skill_id,installed_version_id,environment,status,configuration_encrypted,granted_permissions,granted_capabilities,installed_by,installed_at,activated_at) VALUES (:id,:skill,:version,'staging',:status,CAST(:configuration AS jsonb),'[]'::jsonb,'[]'::jsonb,:admin,now(),:activated) ON CONFLICT (registered_skill_id,environment) DO UPDATE SET installed_version_id=EXCLUDED.installed_version_id,status=EXCLUDED.status,configuration_encrypted=EXCLUDED.configuration_encrypted,updated_at=now()"
            ),
            {
                "id": installation_id,
                "skill": skill_id,
                "version": version_id,
                "status": ("draft", "active", "disabled")[index - 1],
                "configuration": _json(
                    {"ciphertext": encrypt_private({"fixture": True, "sequence": index})}
                ),
                "admin": admin_id,
                "activated": now if index == 2 else None,
            },
        )
        await session.execute(
            text(
                "INSERT INTO skill_executions (id,installation_id,skill_version_id,actor_user_id,invocation_source,status,input_encrypted,input_hash,output_encrypted,output_hash,idempotency_key,permission_snapshot,configuration_version,timeout_at,started_at,completed_at,trace_id,request_id) VALUES (:id,:installation,:version,:admin,'admin_api',:status,CAST(:input AS jsonb),:hash,CAST(:output AS jsonb),:hash,:key,'[]'::jsonb,1,:timeout,:started,:completed,:trace,:request) ON CONFLICT (installation_id,actor_user_id,idempotency_key) DO UPDATE SET status=EXCLUDED.status,completed_at=EXCLUDED.completed_at,updated_at=now()"
            ),
            {
                "id": _id(f"skill-execution:{index}"),
                "installation": installation_id,
                "version": version_id,
                "admin": admin_id,
                "status": ("queued", "succeeded", "failed")[index - 1],
                "input": _json({"ciphertext": encrypt_private({"fixture": True})}),
                "output": _json({"ciphertext": encrypt_private({"ok": index == 2})}),
                "hash": checksum,
                "key": f"{SHOWCASE_PREFIX}:skill-execution:{index}",
                "timeout": now + timedelta(minutes=5),
                "started": now - timedelta(minutes=index),
                "completed": now if index > 1 else None,
                "trace": f"admin-showcase-skill-{index}",
                "request": _id(f"skill-request:{index}"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO marketplace_listings (id,registered_skill_id,listing_status,visibility,category_codes,summary_localizations,pricing_model,support_policy,privacy_disclosure,reviewed_version_id,published_at,created_by) VALUES (:id,:skill,:status,:visibility,'[\"showcase\"]'::jsonb,CAST(:summary AS jsonb),'free','{}'::jsonb,'{}'::jsonb,:version,:published,:admin) ON CONFLICT (registered_skill_id) DO UPDATE SET listing_status=EXCLUDED.listing_status,visibility=EXCLUDED.visibility,summary_localizations=EXCLUDED.summary_localizations,updated_at=now()"
            ),
            {
                "id": listing_id,
                "skill": skill_id,
                "status": ("draft", "approved", "published")[index - 1],
                "visibility": ("unlisted", "private", "public")[index - 1],
                "summary": _json({"zh-CN": f"展示 Skill {index}"}),
                "version": version_id,
                "published": now if index == 3 else None,
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO skill_security_incidents (id,skill_version_id,listing_id,severity,status,reason_code,evidence,created_by) VALUES (:id,:version,:listing,:severity,:status,'admin_showcase_review',CAST(:evidence AS jsonb),:admin) ON CONFLICT (id) DO UPDATE SET severity=EXCLUDED.severity,status=EXCLUDED.status,evidence=EXCLUDED.evidence"
            ),
            {
                "id": _id(f"skill-incident:{index}"),
                "version": version_id,
                "listing": listing_id,
                "severity": ("low", "medium", "high")[index - 1],
                "status": ("open", "investigating", "resolved")[index - 1],
                "evidence": _json({"fixture": SHOWCASE_PREFIX}),
                "admin": admin_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO marketplace_reviews (id,listing_id,skill_version_id,review_type,status,report,package_checksum,reviewer_id,completed_at) VALUES (:id,:listing,:version,:type,:status,CAST(:report AS jsonb),:checksum,:admin,:completed) ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,report=EXCLUDED.report,completed_at=EXCLUDED.completed_at"
            ),
            {
                "id": _id(f"skill-review:{index}"),
                "listing": listing_id,
                "version": version_id,
                "type": ("automated", "human", "security")[index - 1],
                "status": ("pending", "passed", "changes_required")[index - 1],
                "report": _json({"fixture": SHOWCASE_PREFIX, "sequence": index}),
                "checksum": checksum,
                "admin": admin_id,
                "completed": now if index > 1 else None,
            },
        )


async def _coverage_counts(session: AsyncSession, admin_id: UUID) -> dict[str, int]:
    queries = {
        "administrators": "SELECT count(DISTINCT u.id) FROM users u JOIN user_roles ur ON ur.user_id=u.id AND ur.revoked_at IS NULL JOIN roles r ON r.id=ur.role_id WHERE r.code<>'member' AND (u.id=:admin OR u.email LIKE 'admin-showcase-%@example.invalid')",
        "admin_sessions": "SELECT count(*) FROM auth_sessions WHERE user_id=:admin AND audience='vav-admin' AND id IN (:one,:two,:three)",
        "admin_invitations": "SELECT count(*) FROM admin_invitations WHERE invited_by=:admin AND email LIKE 'admin-showcase-%@example.invalid'",
        "security_audit": "SELECT count(*) FROM security_audit_events WHERE actor_user_id=:admin AND event_type LIKE 'admin.showcase.%'",
        "capabilities": "SELECT count(*) FROM admin_capability_definitions WHERE lifecycle_status='active'",
        "work_items": "SELECT count(*) FROM admin_work_items WHERE deduplication_key LIKE 'admin-showcase:%'",
        "saved_views": "SELECT count(*) FROM admin_saved_views WHERE owner_user_id=:admin AND name LIKE '展示视图 %'",
        "bulk_jobs": "SELECT count(*) FROM admin_bulk_jobs WHERE requested_by=:admin AND idempotency_key LIKE 'admin-showcase:%'",
        "approvals": "SELECT count(*) FROM admin_approval_requests WHERE requested_by=:admin AND approval_number LIKE 'APR-SHOWCASE-%'",
        "exceptions": "SELECT count(*) FROM admin_exception_items WHERE exception_code LIKE 'ADMIN-SHOWCASE-EX-%'",
        "configurations": "SELECT count(*) FROM admin_configuration_versions WHERE created_by=:admin AND semantic_version LIKE '%-showcase'",
        "field_policies": "SELECT count(*) FROM admin_field_access_policies WHERE lifecycle_status='active'",
        "reveal_history": "SELECT count(*) FROM admin_sensitive_reveal_grants WHERE admin_user_id=:admin AND entity_type='showcase_record'",
        "certifications": "SELECT count(*) FROM admin_domain_certifications WHERE evaluated_by=:admin AND release_version='showcase-1.0'",
        "operation_audit": "SELECT count(*) FROM admin_operation_receipts WHERE admin_user_id=:admin AND trace_id LIKE 'admin-showcase-%'",
        "quality_requirements": "SELECT count(*) FROM quality_requirements",
        "design_components": "SELECT count(*) FROM ui_components",
        "experience_routes": "SELECT count(*) FROM experience_routes",
        "process_definitions": "SELECT count(*) FROM process_definitions",
        "data_assets": "SELECT count(*) FROM data_assets",
        "privacy_assets": "SELECT count(*) FROM privacy_data_assets",
        "knowledge_documents": "SELECT count(*) FROM knowledge_documents",
        "system_feature_flags": "SELECT count(*) FROM system_feature_flags WHERE flag_code LIKE 'admin_showcase_feature_%'",
        "system_releases": "SELECT count(*) FROM system_release_records WHERE release_version LIKE 'showcase-%'",
        "system_jobs": "SELECT count(*) FROM system_backfill_jobs WHERE job_code LIKE 'admin-showcase-job-%'",
        "system_backups": "SELECT count(*) FROM system_backup_records WHERE id IN (:system_backup_one,:system_backup_two,:system_backup_three)",
        "system_restore_drills": "SELECT count(*) FROM system_restore_drills WHERE drill_code LIKE 'ADMIN-SHOWCASE-DRILL-%'",
        "system_capacity": "SELECT count(*) FROM system_capacity_baselines WHERE scenario_code LIKE 'admin-showcase-load-%'",
        "skill_publishers": "SELECT count(*) FROM skill_publishers WHERE publisher_code LIKE 'admin-showcase-publisher-%'",
        "registered_skills": "SELECT count(*) FROM registered_skills WHERE skill_name LIKE 'admin-showcase-skill-%'",
        "skill_dependencies": "SELECT count(*) FROM skill_dependencies WHERE dependency_name LIKE 'admin-showcase-dependency-%'",
        "skill_installations": "SELECT count(*) FROM skill_installations i JOIN registered_skills s ON s.id=i.registered_skill_id WHERE s.skill_name LIKE 'admin-showcase-skill-%'",
        "skill_executions": "SELECT count(*) FROM skill_executions WHERE idempotency_key LIKE 'admin-showcase:skill-execution:%'",
        "skill_marketplace": "SELECT count(*) FROM marketplace_listings l JOIN registered_skills s ON s.id=l.registered_skill_id WHERE s.skill_name LIKE 'admin-showcase-skill-%'",
        "skill_reviews": "SELECT count(*) FROM marketplace_reviews WHERE id IN (:skill_review_one,:skill_review_two,:skill_review_three)",
        "skill_incidents": "SELECT count(*) FROM skill_security_incidents WHERE reason_code='admin_showcase_review'",
    }
    parameters = {
        "admin": admin_id,
        "one": _id("session:1"),
        "two": _id("session:2"),
        "three": _id("session:3"),
        "system_backup_one": _id("system-backup:1"),
        "system_backup_two": _id("system-backup:2"),
        "system_backup_three": _id("system-backup:3"),
        "skill_review_one": _id("skill-review:1"),
        "skill_review_two": _id("skill-review:2"),
        "skill_review_three": _id("skill-review:3"),
    }
    counts = {
        name: int(await session.scalar(text(query), parameters) or 0)
        for name, query in queries.items()
    }
    missing = {
        name: {"expected_at_least": ADMIN_PAGE_COVERAGE[name], "actual": count}
        for name, count in counts.items()
        if count < ADMIN_PAGE_COVERAGE[name]
    }
    if missing:
        raise RuntimeError(f"Admin showcase coverage is incomplete: {_json(missing)}")
    return counts


async def _seed_reference_and_business_data() -> dict[str, int]:
    business_counts = await seed_test_showcase()
    await seed_knowledge()
    await seed_privacy_inventory()
    await seed_quality()
    await seed_design_system()
    await seed_process_governance()
    await seed_data_governance()
    await seed_admin_platform()
    return business_counts


async def seed_admin_showcase() -> dict[str, int]:
    environment = get_settings().environment
    if environment in PROTECTED_ENVIRONMENTS:
        raise RuntimeError(
            f"Refusing to seed administrator showcase data in protected environment: {environment}."
        )
    business_counts = await _seed_reference_and_business_data()
    async with session_factory() as session:
        admin_id, role_id = await _admin_identity(session)
        await _seed_identity_surfaces(session, admin_id, role_id)
        await _seed_admin_platform_surfaces(session, admin_id)
        await _seed_system_surfaces(session, admin_id)
        await _seed_skill_surfaces(session, admin_id)
        await session.commit()
        admin_counts = await _coverage_counts(session, admin_id)
    return {
        **{f"business.{key}": value for key, value in business_counts.items()},
        **{f"admin.{key}": value for key, value in admin_counts.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=ADMIN_EMAIL)
    parser.add_argument("--confirm-admin-showcase", action="store_true")
    args = parser.parse_args()
    if args.email.casefold() != ADMIN_EMAIL:
        raise SystemExit(f"This deterministic seed only targets {ADMIN_EMAIL}.")
    if not args.confirm_admin_showcase:
        raise SystemExit(
            "Refusing to seed administrator showcase data without explicit confirmation."
        )
    counts = asyncio.run(seed_admin_showcase())
    print(f"Admin showcase ready for {ADMIN_EMAIL}: {_json(counts)}")


if __name__ == "__main__":
    main()
