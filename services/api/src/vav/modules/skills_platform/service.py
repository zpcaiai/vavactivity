# ruff: noqa: E501

"""Fail-closed persistence control plane for the Skill platform."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.skills_platform.schemas import (
    AppealRequest,
    ExecuteSkillRequest,
    InstallPlanRequest,
    MarketplaceListingRequest,
    ReviewDecisionRequest,
    UpgradeInstallationRequest,
)

HIGH_RISK_MARKERS = (
    ".sensitive.",
    ".export",
    ".payment",
    ".send",
    ".restrict",
    "secrets.",
    "network.",
)
PRODUCTION_TRUST = {
    "builtin_trusted",
    "official_signed",
    "verified_publisher",
    "community_reviewed",
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


async def _audit(
    session: AsyncSession,
    actor_id: UUID,
    action: str,
    subject_type: str,
    subject_id: UUID | None,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,'admin',:action,:subject_type,:subject_id,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id),
            "action": action,
            "subject_type": subject_type,
            "subject_id": str(subject_id) if subject_id else None,
            "context": _json(context or {}),
        },
    )


async def list_skills(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT s.skill_name,s.display_name,s.description,s.skill_type,s.visibility,s.trust_level,"
                "s.lifecycle_status,p.publisher_code,v.semantic_version AS current_version "
                "FROM registered_skills s JOIN skill_publishers p ON p.id=s.publisher_id "
                "LEFT JOIN registered_skill_versions v ON v.id=s.current_stable_version_id "
                "WHERE s.lifecycle_status <> 'revoked' ORDER BY s.skill_name"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def skill_detail(session: AsyncSession, skill_name: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT s.*,p.publisher_code,p.verification_status FROM registered_skills s "
                "JOIN skill_publishers p ON p.id=s.publisher_id WHERE s.skill_name=:name"
            ),
            {"name": skill_name},
        )
    ).first()
    if row is None:
        raise VavError("SKILL_NOT_FOUND", "Skill was not found.", status_code=404)
    return _mapping(row)


async def skill_versions(session: AsyncSession, skill_name: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT v.id,v.semantic_version,v.manifest_version,v.runtime_api_version,"
                "v.signature_status,v.security_status,v.review_status,v.compatibility_status,"
                "v.published_at,v.deprecated_at,v.revoked_at FROM registered_skill_versions v "
                "JOIN registered_skills s ON s.id=v.registered_skill_id WHERE s.skill_name=:name "
                "ORDER BY v.created_at DESC"
            ),
            {"name": skill_name},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def version_detail(session: AsyncSession, version_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT v.id,v.semantic_version,v.manifest_version,v.runtime_api_version,v.manifest,"
                "v.manifest_checksum,v.package_checksum,v.signature_status,v.security_status,"
                "v.review_status,v.compatibility_status,v.published_at,v.deprecated_at,v.revoked_at,"
                "(v.sbom_reference_encrypted IS NOT NULL) AS sbom_present,"
                "(v.provenance_reference_encrypted IS NOT NULL) AS provenance_present,"
                "s.skill_name,s.trust_level FROM registered_skill_versions v JOIN registered_skills s "
                "ON s.id=v.registered_skill_id WHERE v.id=:id"
            ),
            {"id": version_id},
        )
    ).first()
    if row is None:
        raise VavError("SKILL_VERSION_NOT_FOUND", "Skill version was not found.", status_code=404)
    return _mapping(row)


async def create_install_plan(
    session: AsyncSession, actor_id: UUID, payload: InstallPlanRequest
) -> dict[str, Any]:
    version = (
        (
            await session.execute(
                text(
                    "SELECT s.id AS skill_id,s.skill_name,s.trust_level,s.lifecycle_status,v.id AS version_id,"
                    "v.semantic_version,v.manifest,v.signature_status,v.security_status,v.compatibility_status,"
                    "v.revoked_at FROM registered_skills s JOIN registered_skill_versions v "
                    "ON v.registered_skill_id=s.id WHERE s.skill_name=:name AND v.semantic_version=:version"
                ),
                {"name": payload.skill_name, "version": payload.semantic_version},
            )
        )
        .mappings()
        .first()
    )
    if version is None:
        raise VavError("SKILL_VERSION_NOT_FOUND", "Skill version was not found.", status_code=404)
    if version["lifecycle_status"] in {"quarantined", "revoked"} or version["revoked_at"]:
        raise VavError(
            "SKILL_VERSION_REVOKED", "Revoked Skill versions cannot be installed.", status_code=409
        )
    if version["signature_status"] != "verified":
        raise VavError(
            "SKILL_SIGNATURE_REQUIRED", "A verified package signature is required.", status_code=409
        )
    if version["security_status"] not in {"passed", "passed_with_warnings"}:
        raise VavError(
            "SKILL_SECURITY_GATE_FAILED", "Skill security checks have not passed.", status_code=409
        )
    if version["compatibility_status"] != "compatible":
        raise VavError(
            "SKILL_INCOMPATIBLE", "Skill is not compatible with this platform.", status_code=409
        )
    if payload.environment == "production" and version["trust_level"] not in PRODUCTION_TRUST:
        raise VavError(
            "SKILL_TRUST_INSUFFICIENT",
            "Unverified Skills cannot be installed in production.",
            status_code=409,
        )

    requested = set(version["manifest"].get("spec", {}).get("permissions", []))
    granted = set(payload.granted_permissions)
    if not requested.issuperset(granted):
        raise VavError(
            "SKILL_PERMISSION_NOT_DECLARED",
            "Installation grants exceed the manifest.",
            status_code=422,
        )
    missing = sorted(requested - granted)
    dependencies = list(
        (
            await session.execute(
                text(
                    "SELECT dependency_type,dependency_name,version_constraint,optional,peer,resolution_status "
                    "FROM skill_dependencies WHERE skill_version_id=:version ORDER BY dependency_type,dependency_name"
                ),
                {"version": version["version_id"]},
            )
        ).mappings()
    )
    unresolved = [
        dict(item)
        for item in dependencies
        if item["resolution_status"] not in {"resolved"} and not item["optional"]
    ]
    if unresolved:
        raise VavError(
            "SKILL_DEPENDENCY_UNRESOLVED",
            "Required Skill dependencies are unresolved.",
            status_code=409,
        )
    high_risk = sorted(
        permission
        for permission in granted
        if any(marker in permission for marker in HIGH_RISK_MARKERS)
    )
    approval_required = bool(high_risk or missing or payload.environment == "production")
    plan = {
        "target_skill": {
            "name": version["skill_name"],
            "version": version["semantic_version"],
            "trust_level": version["trust_level"],
        },
        "dependencies": [dict(item) for item in dependencies],
        "permission_changes": {
            "requested": sorted(requested),
            "granted": sorted(granted),
            "missing": missing,
            "high_risk": high_risk,
        },
        "configuration_keys": sorted(payload.configuration),
        "database_migrations": version["manifest"]
        .get("spec", {})
        .get("state", {})
        .get("migrations", []),
        "scheduled_jobs": version["manifest"].get("spec", {}).get("schedules", []),
        "event_subscriptions": version["manifest"]
        .get("spec", {})
        .get("events", {})
        .get("subscribes", []),
        "ui_extensions": version["manifest"].get("spec", {}).get("ui", {}).get("extensions", []),
        "approval_required": approval_required,
        "rollback_supported": not bool(
            version["manifest"].get("spec", {}).get("state", {}).get("irreversible", False)
        ),
    }
    checksum = _checksum(plan)
    row = (
        await session.execute(
            text(
                "INSERT INTO skill_install_plans (registered_skill_id,target_version_id,environment,plan,"
                "plan_checksum,approval_required,created_by,expires_at) VALUES (:skill,:target,:environment,"
                "CAST(:plan AS jsonb),:checksum,:approval,:actor,now()+interval '30 minutes') RETURNING *"
            ),
            {
                "skill": version["skill_id"],
                "target": version["version_id"],
                "environment": payload.environment,
                "plan": _json(plan),
                "checksum": checksum,
                "approval": approval_required,
                "actor": actor_id,
            },
        )
    ).first()
    assert row is not None
    await _audit(
        session,
        actor_id,
        "skill.install.plan_created",
        "skill_install_plan",
        row.id,
        {"checksum": checksum},
    )
    await session.commit()
    return _mapping(row)


async def create_installation(
    session: AsyncSession, actor_id: UUID, plan_id: UUID, expected_checksum: str
) -> dict[str, Any]:
    plan = (
        (
            await session.execute(
                text("SELECT * FROM skill_install_plans WHERE id=:id FOR UPDATE"), {"id": plan_id}
            )
        )
        .mappings()
        .first()
    )
    if plan is None or plan["status"] != "ready" or plan["expires_at"] <= datetime.now(UTC):
        raise VavError(
            "SKILL_INSTALL_PLAN_INVALID", "Install plan is unavailable or expired.", status_code=409
        )
    if plan["plan_checksum"] != expected_checksum:
        raise VavError(
            "SKILL_INSTALL_PLAN_CHANGED", "Install plan checksum changed.", status_code=409
        )
    status = "approval_required" if plan["approval_required"] else "validating"
    row = (
        await session.execute(
            text(
                "INSERT INTO skill_installations (registered_skill_id,installed_version_id,environment,status,"
                "configuration_encrypted,granted_permissions,granted_capabilities,installed_by,installed_at) "
                "VALUES (:skill,:version,:environment,:status,'{}'::jsonb,CAST(:permissions AS jsonb),'[]'::jsonb,"
                ":actor,now()) ON CONFLICT (registered_skill_id,environment) DO NOTHING RETURNING *"
            ),
            {
                "skill": plan["registered_skill_id"],
                "version": plan["target_version_id"],
                "environment": plan["environment"],
                "status": status,
                "permissions": _json(plan["plan"]["permission_changes"]["granted"]),
                "actor": actor_id,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_ALREADY_INSTALLED",
            "Skill is already installed in this environment.",
            status_code=409,
        )
    await session.execute(
        text("UPDATE skill_install_plans SET status='consumed' WHERE id=:id"), {"id": plan_id}
    )
    await _audit(
        session, actor_id, "skill.installed", "skill_installation", row.id, {"status": status}
    )
    await session.commit()
    return _mapping(row)


async def list_installations(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT i.id,s.skill_name,v.semantic_version,i.environment,i.status,i.configuration_version,"
                "i.granted_permissions,i.installed_at,i.activated_at,i.disabled_at,i.version,i.created_at "
                "FROM skill_installations i JOIN registered_skills s ON s.id=i.registered_skill_id "
                "JOIN registered_skill_versions v ON v.id=i.installed_version_id ORDER BY i.created_at DESC"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def installation_detail(session: AsyncSession, installation_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT i.*,s.skill_name,s.trust_level,v.semantic_version,v.signature_status,v.security_status,"
                "v.compatibility_status FROM skill_installations i JOIN registered_skills s ON s.id=i.registered_skill_id "
                "JOIN registered_skill_versions v ON v.id=i.installed_version_id WHERE i.id=:id"
            ),
            {"id": installation_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_INSTALLATION_NOT_FOUND", "Skill installation was not found.", status_code=404
        )
    return _mapping(row)


async def approve_installation(
    session: AsyncSession, installation_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE skill_installations SET status='validating',approved_by=:actor,version=version+1,updated_at=now() "
                "WHERE id=:id AND status='approval_required' AND installed_by<>:actor RETURNING *"
            ),
            {"id": installation_id, "actor": actor_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_APPROVAL_REJECTED",
            "Approval requires a separate administrator and pending installation.",
            status_code=409,
        )
    await _audit(session, actor_id, "skill.install.approved", "skill_installation", installation_id)
    await session.commit()
    return _mapping(row)


async def activate_installation(
    session: AsyncSession, installation_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE skill_installations i SET status='active',activated_at=now(),disabled_at=NULL,version=version+1,updated_at=now() "
                "FROM registered_skill_versions v,registered_skills s WHERE i.id=:id AND i.installed_version_id=v.id "
                "AND i.registered_skill_id=s.id AND i.status='validating' AND v.signature_status='verified' "
                "AND v.security_status IN ('passed','passed_with_warnings') AND v.compatibility_status='compatible' "
                "AND v.revoked_at IS NULL AND s.trust_level NOT IN ('unverified','quarantined','revoked') RETURNING i.*"
            ),
            {"id": installation_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_ACTIVATION_GATE_FAILED",
            "Skill installation did not pass activation gates.",
            status_code=409,
        )
    await _audit(session, actor_id, "skill.activated", "skill_installation", installation_id)
    await session.commit()
    return _mapping(row)


async def transition_installation(
    session: AsyncSession, installation_id: UUID, actor_id: UUID, operation: str, reason_code: str
) -> dict[str, Any]:
    transitions = {
        "disable": ("active", "disabled", "skill.disabled"),
        "uninstall": ("disabled", "uninstalled", "skill.uninstalled"),
    }
    transition = transitions.get(operation)
    if transition is None:
        raise VavError(
            "SKILL_OPERATION_INVALID", "Unsupported installation operation.", status_code=404
        )
    source, target, event = transition
    row = (
        await session.execute(
            text(
                "UPDATE skill_installations SET status=:target,disabled_at=CASE WHEN :target='disabled' THEN now() ELSE disabled_at END,"
                "version=version+1,updated_at=now() WHERE id=:id AND status=:source RETURNING *"
            ),
            {"target": target, "id": installation_id, "source": source},
        )
    ).first()
    if row is None:
        raise VavError("SKILL_STATE_CONFLICT", "Skill installation state changed.", status_code=409)
    await _audit(
        session,
        actor_id,
        event,
        "skill_installation",
        installation_id,
        {"reason_code": reason_code},
    )
    await session.commit()
    return _mapping(row)


async def upgrade_installation(
    session: AsyncSession,
    installation_id: UUID,
    actor_id: UUID,
    payload: UpgradeInstallationRequest,
) -> dict[str, Any]:
    current = await installation_detail(session, installation_id)
    target = await version_detail(session, payload.target_version_id)
    if (
        target["skill_name"] != current["skill_name"]
        or target["compatibility_status"] != "compatible"
        or target["signature_status"] != "verified"
        or target["security_status"] not in {"passed", "passed_with_warnings"}
        or target["revoked_at"]
    ):
        raise VavError(
            "SKILL_UPGRADE_GATE_FAILED", "Target version failed upgrade gates.", status_code=409
        )
    requested = set(target["manifest"].get("spec", {}).get("permissions", []))
    granted = set(payload.granted_permissions)
    old_granted = set(current["granted_permissions"])
    if not granted.issubset(requested):
        raise VavError(
            "SKILL_PERMISSION_NOT_DECLARED",
            "Upgrade grants exceed the target manifest.",
            status_code=422,
        )
    permission_increase = bool(granted - old_granted)
    status = "approval_required" if permission_increase else "validating"
    row = (
        await session.execute(
            text(
                "UPDATE skill_installations SET previous_version_id=installed_version_id,installed_version_id=:target,"
                "granted_permissions=CAST(:permissions AS jsonb),status=:status,approved_by=NULL,version=version+1,updated_at=now() "
                "WHERE id=:id AND version=:expected AND status IN ('active','disabled') RETURNING *"
            ),
            {
                "target": payload.target_version_id,
                "permissions": _json(sorted(granted)),
                "status": status,
                "id": installation_id,
                "expected": payload.expected_version,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_UPGRADE_CONFLICT", "Installation version or state changed.", status_code=409
        )
    await _audit(
        session,
        actor_id,
        "skill.upgrade_started",
        "skill_installation",
        installation_id,
        {"permission_increase": permission_increase},
    )
    await session.commit()
    return _mapping(row)


async def rollback_installation(
    session: AsyncSession, installation_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE skill_installations SET installed_version_id=previous_version_id,previous_version_id=installed_version_id,"
                "status='validating',approved_by=NULL,version=version+1,updated_at=now() WHERE id=:id AND previous_version_id IS NOT NULL "
                "AND status IN ('disabled','failed','validating') RETURNING *"
            ),
            {"id": installation_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_ROLLBACK_UNAVAILABLE",
            "A compatible rollback version is unavailable.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id,
        "skill.rolled_back",
        "skill_installation",
        installation_id,
        {"reason_code": reason_code},
    )
    await session.commit()
    return _mapping(row)


async def queue_execution(
    session: AsyncSession, actor_id: UUID, skill_name: str, payload: ExecuteSkillRequest
) -> dict[str, Any]:
    if (
        payload.deadline.tzinfo is None
        or payload.deadline <= datetime.now(UTC)
        or payload.deadline > datetime.now(UTC) + timedelta(minutes=15)
    ):
        raise VavError(
            "SKILL_DEADLINE_INVALID",
            "Execution deadline must be within 15 minutes.",
            status_code=422,
        )
    installation = (
        (
            await session.execute(
                text(
                    "SELECT i.id,i.installed_version_id,i.configuration_version,i.granted_permissions,v.semantic_version,v.manifest "
                    "FROM skill_installations i JOIN registered_skills s ON s.id=i.registered_skill_id "
                    "JOIN registered_skill_versions v ON v.id=i.installed_version_id WHERE s.skill_name=:name "
                    "AND i.status='active' AND v.revoked_at IS NULL ORDER BY i.activated_at DESC LIMIT 1"
                ),
                {"name": skill_name},
            )
        )
        .mappings()
        .first()
    )
    if installation is None:
        raise VavError(
            "SKILL_NOT_ACTIVE", "No active Skill installation is available.", status_code=409
        )
    execution = installation["manifest"].get("spec", {}).get("execution", {})
    if (
        execution.get("idempotency") in {"required", "caller_provided"}
        and not payload.idempotency_key
    ):
        raise VavError(
            "SKILL_IDEMPOTENCY_REQUIRED", "This Skill requires an idempotency key.", status_code=422
        )
    input_hash = _checksum(payload.input)
    if payload.idempotency_key:
        existing = (
            await session.execute(
                text(
                    "SELECT id,status,created_at FROM skill_executions WHERE installation_id=:installation "
                    "AND actor_user_id=:actor AND idempotency_key=:key"
                ),
                {
                    "installation": installation["id"],
                    "actor": actor_id,
                    "key": payload.idempotency_key,
                },
            )
        ).first()
        if existing is not None:
            return _mapping(existing)
    row = (
        await session.execute(
            text(
                "INSERT INTO skill_executions (installation_id,skill_version_id,actor_user_id,invocation_source,status,"
                "input_encrypted,input_hash,idempotency_key,permission_snapshot,configuration_version,timeout_at,trace_id) "
                "VALUES (:installation,:version,:actor,:source,'queued',CAST(:input AS jsonb),:input_hash,:key,"
                "CAST(:permissions AS jsonb),:configuration,:deadline,:trace) RETURNING id,status,created_at"
            ),
            {
                "installation": installation["id"],
                "version": installation["installed_version_id"],
                "actor": actor_id,
                "source": payload.invocation_source,
                "input": _json(payload.input),
                "input_hash": input_hash,
                "key": payload.idempotency_key,
                "permissions": _json(installation["granted_permissions"]),
                "configuration": installation["configuration_version"],
                "deadline": payload.deadline,
                "trace": hashlib.sha256(f"{actor_id}:{input_hash}".encode()).hexdigest()[:32],
            },
        )
    ).first()
    assert row is not None
    await _audit(
        session,
        actor_id,
        "skill.execution.started",
        "skill_execution",
        row.id,
        {"skill_name": skill_name, "source": payload.invocation_source},
    )
    await session.commit()
    return _mapping(row)


async def list_executions(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT e.id,s.skill_name,v.semantic_version,e.invocation_source,e.status,e.input_hash,e.output_hash,"
                "e.error_code,e.error_message_safe,e.trace_id,e.started_at,e.completed_at,e.created_at "
                "FROM skill_executions e JOIN registered_skill_versions v ON v.id=e.skill_version_id "
                "JOIN registered_skills s ON s.id=v.registered_skill_id ORDER BY e.created_at DESC LIMIT 200"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def cancel_execution(
    session: AsyncSession, execution_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE skill_executions SET status='cancel_requested',updated_at=now() WHERE id=:id "
                "AND status IN ('created','validating','authorizing','queued','running','waiting_for_dependency') "
                "RETURNING id,status,updated_at"
            ),
            {"id": execution_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_EXECUTION_NOT_CANCELLABLE", "Execution cannot be cancelled.", status_code=409
        )
    await _audit(session, actor_id, "skill.execution.cancelled", "skill_execution", execution_id)
    await session.commit()
    return _mapping(row)


async def submit_listing(
    session: AsyncSession, actor_id: UUID, payload: MarketplaceListingRequest
) -> dict[str, Any]:
    version = await version_detail(session, payload.version_id)
    if version["skill_name"] != payload.skill_name:
        raise VavError(
            "MARKETPLACE_VERSION_MISMATCH",
            "Reviewed version does not belong to the Skill.",
            status_code=422,
        )
    gates = {
        "signature": version["signature_status"] == "verified",
        "security": version["security_status"] in {"passed", "passed_with_warnings"},
        "compatibility": version["compatibility_status"] == "compatible",
        "sbom": bool(version.get("sbom_present")),
        "provenance": bool(version.get("provenance_present")),
        "data_disclosure": True,
    }
    if not all(gates.values()):
        raise VavError(
            "MARKETPLACE_AUTOMATED_REVIEW_FAILED",
            "Listing failed automated review gates.",
            status_code=409,
        )
    skill = await skill_detail(session, payload.skill_name)
    row = (
        await session.execute(
            text(
                "INSERT INTO marketplace_listings (registered_skill_id,listing_status,visibility,category_codes,"
                "summary_localizations,documentation_reference,pricing_model,support_policy,privacy_disclosure,"
                "reviewed_version_id,created_by) VALUES (:skill,'human_review','unlisted',CAST(:categories AS jsonb),"
                "CAST(:summaries AS jsonb),:docs,:pricing,CAST(:support AS jsonb),CAST(:privacy AS jsonb),:version,:actor) "
                "ON CONFLICT (registered_skill_id) DO UPDATE SET listing_status='human_review',visibility='unlisted',"
                "category_codes=EXCLUDED.category_codes,summary_localizations=EXCLUDED.summary_localizations,"
                "documentation_reference=EXCLUDED.documentation_reference,pricing_model=EXCLUDED.pricing_model,"
                "support_policy=EXCLUDED.support_policy,privacy_disclosure=EXCLUDED.privacy_disclosure,"
                "reviewed_version_id=EXCLUDED.reviewed_version_id,updated_at=now() RETURNING *"
            ),
            {
                "skill": skill["id"],
                "categories": _json(payload.category_codes),
                "summaries": _json(payload.summary_localizations),
                "docs": payload.documentation_reference,
                "pricing": payload.pricing_model,
                "support": _json(payload.support_policy),
                "privacy": _json(payload.privacy_disclosure),
                "version": payload.version_id,
                "actor": actor_id,
            },
        )
    ).first()
    assert row is not None
    await session.execute(
        text(
            "INSERT INTO marketplace_reviews (listing_id,skill_version_id,review_type,status,report,package_checksum,completed_at) "
            "VALUES (:listing,:version,'automated','passed',CAST(:report AS jsonb),:checksum,now())"
        ),
        {
            "listing": row.id,
            "version": payload.version_id,
            "report": _json(gates),
            "checksum": version["package_checksum"],
        },
    )
    await _audit(session, actor_id, "skill.marketplace.submitted", "marketplace_listing", row.id)
    await session.commit()
    return _mapping(row)


async def list_marketplace(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT l.id,s.skill_name,s.display_name,p.publisher_code,l.listing_status,l.visibility,"
                "l.category_codes,l.summary_localizations,l.pricing_model,l.published_at,l.suspended_at,l.created_at "
                "FROM marketplace_listings l JOIN registered_skills s ON s.id=l.registered_skill_id "
                "JOIN skill_publishers p ON p.id=s.publisher_id ORDER BY l.created_at DESC"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def decide_listing(
    session: AsyncSession, listing_id: UUID, actor_id: UUID, payload: ReviewDecisionRequest
) -> dict[str, Any]:
    target = {
        "approved": "approved",
        "changes_required": "changes_required",
        "rejected": "changes_required",
    }[payload.decision]
    row = (
        await session.execute(
            text(
                "UPDATE marketplace_listings SET listing_status=:status,updated_at=now() WHERE id=:id "
                "AND listing_status='human_review' AND created_by<>:actor RETURNING *"
            ),
            {"status": target, "id": listing_id, "actor": actor_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "MARKETPLACE_REVIEW_REJECTED",
            "Human review requires separation of duties and pending status.",
            status_code=409,
        )
    await session.execute(
        text(
            "INSERT INTO marketplace_reviews (listing_id,skill_version_id,review_type,status,report,package_checksum,reviewer_id,completed_at) "
            "SELECT l.id,l.reviewed_version_id,'human',:status,CAST(:report AS jsonb),v.package_checksum,:actor,now() "
            "FROM marketplace_listings l JOIN registered_skill_versions v ON v.id=l.reviewed_version_id WHERE l.id=:id"
        ),
        {
            "status": "passed" if payload.decision == "approved" else "changes_required",
            "report": _json({"reason_code": payload.reason_code, "findings": payload.findings}),
            "actor": actor_id,
            "id": listing_id,
        },
    )
    await _audit(
        session,
        actor_id,
        f"skill.marketplace.{payload.decision}",
        "marketplace_listing",
        listing_id,
        {"reason_code": payload.reason_code},
    )
    await session.commit()
    return _mapping(row)


async def publish_listing(
    session: AsyncSession, listing_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE marketplace_listings l SET listing_status='published',visibility='public',published_at=now(),updated_at=now() "
                "FROM registered_skill_versions v WHERE l.id=:id AND l.reviewed_version_id=v.id AND l.listing_status='approved' "
                "AND v.signature_status='verified' AND v.security_status IN ('passed','passed_with_warnings') "
                "AND v.compatibility_status='compatible' AND v.revoked_at IS NULL RETURNING l.*"
            ),
            {"id": listing_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "MARKETPLACE_PUBLISH_GATE_FAILED",
            "Only an approved healthy version can be published.",
            status_code=409,
        )
    await _audit(
        session, actor_id, "skill.marketplace.published", "marketplace_listing", listing_id
    )
    await session.commit()
    return _mapping(row)


async def suspend_listing(
    session: AsyncSession, listing_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE marketplace_listings SET listing_status='suspended',visibility='unlisted',suspended_at=now(),updated_at=now() "
                "WHERE id=:id AND listing_status IN ('published','approved') RETURNING *"
            ),
            {"id": listing_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "MARKETPLACE_STATE_CONFLICT",
            "Listing cannot be suspended from its current state.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id,
        "skill.marketplace.suspended",
        "marketplace_listing",
        listing_id,
        {"reason_code": reason_code},
    )
    await session.commit()
    return _mapping(row)


async def create_appeal(
    session: AsyncSession,
    listing_id: UUID,
    actor_id: UUID,
    publisher_id: UUID,
    payload: AppealRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO marketplace_appeals (listing_id,publisher_id,reason_code,statement_encrypted) "
                "SELECT :listing,:publisher,:reason,:statement WHERE EXISTS (SELECT 1 FROM marketplace_listings "
                "WHERE id=:listing AND listing_status IN ('changes_required','suspended','removed')) RETURNING *"
            ),
            {
                "listing": listing_id,
                "publisher": publisher_id,
                "reason": payload.reason_code,
                "statement": payload.statement,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "MARKETPLACE_APPEAL_NOT_ALLOWED", "Listing is not eligible for appeal.", status_code=409
        )
    await session.execute(
        text(
            "UPDATE marketplace_listings SET listing_status='appeal_pending',updated_at=now() WHERE id=:id"
        ),
        {"id": listing_id},
    )
    await _audit(session, actor_id, "skill.marketplace.appealed", "marketplace_listing", listing_id)
    await session.commit()
    return _mapping(row)
