# ruff: noqa: E501

"""Fail-closed persistence control plane for the Skill platform."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.skills_platform.marketplace_review import automated_review
from vav.modules.skills_platform.registry_ingestion import (
    SkillArtifactStore,
    canonical_signing_key,
    skill_artifact_store,
    validate_release,
)
from vav.modules.skills_platform.schemas import (
    AppealDecisionRequest,
    AppealRequest,
    CreatePublisherRequest,
    ExecuteSkillRequest,
    InstallPlanRequest,
    MarketplaceListingRequest,
    PublisherDecisionRequest,
    PublishSkillVersionRequest,
    ReviewDecisionRequest,
    SecurityReviewRequest,
    SignatureRevocationRequest,
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
    if not get_settings().skills_enabled:
        raise VavError("SKILLS_DISABLED", "The Skill platform is disabled.", status_code=503)
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
    session: AsyncSession,
    actor_id: UUID,
    plan_id: UUID,
    expected_checksum: str,
    configuration: dict[str, Any] | None = None,
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
                "VALUES (:skill,:version,:environment,:status,CAST(:configuration AS jsonb),CAST(:permissions AS jsonb),'[]'::jsonb,"
                ":actor,now()) ON CONFLICT (registered_skill_id,environment) DO NOTHING RETURNING *"
            ),
            {
                "skill": plan["registered_skill_id"],
                "version": plan["target_version_id"],
                "environment": plan["environment"],
                "status": status,
                "configuration": _json({"ciphertext": encrypt_private(configuration or {})}),
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
    settings = get_settings()
    if not settings.skills_enabled:
        raise VavError("SKILLS_DISABLED", "The Skill platform is disabled.", status_code=503)
    if (
        payload.deadline.tzinfo is None
        or payload.deadline <= datetime.now(UTC)
        or payload.deadline
        > datetime.now(UTC) + timedelta(seconds=settings.skill_runtime_max_timeout_seconds)
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
                "input": _json({"ciphertext": encrypt_private(payload.input)}),
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


async def execution_detail(
    session: AsyncSession, execution_id: UUID, *, include_sensitive: bool = False
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT e.*,s.skill_name,v.semantic_version FROM skill_executions e "
                "JOIN registered_skill_versions v ON v.id=e.skill_version_id "
                "JOIN registered_skills s ON s.id=v.registered_skill_id WHERE e.id=:id"
            ),
            {"id": execution_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_EXECUTION_NOT_FOUND", "Skill execution was not found.", status_code=404
        )
    result = _mapping(row)
    encrypted_input = result.pop("input_encrypted", None)
    encrypted_output = result.pop("output_encrypted", None)
    result["input_present"] = encrypted_input is not None
    result["output_present"] = encrypted_output is not None
    if include_sensitive:
        if isinstance(encrypted_input, dict) and isinstance(encrypted_input.get("ciphertext"), str):
            result["input"] = decrypt_private(encrypted_input["ciphertext"])
        if isinstance(encrypted_output, dict) and isinstance(
            encrypted_output.get("ciphertext"), str
        ):
            result["output"] = decrypt_private(encrypted_output["ciphertext"])
    return result


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


async def create_publisher(
    session: AsyncSession, actor_id: UUID, payload: CreatePublisherRequest
) -> dict[str, Any]:
    key_manifest = canonical_signing_key(payload.key_id, payload.public_key_pem)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:code,0))"),
        {"code": payload.publisher_code},
    )
    if await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM skill_publishers WHERE publisher_code=:code)"),
        {"code": payload.publisher_code},
    ):
        raise VavError(
            "SKILL_PUBLISHER_EXISTS", "Publisher code is already registered.", status_code=409
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO skill_publishers (publisher_code,display_name,publisher_type,verification_status,"
                "signing_key_manifest,status,created_by) VALUES (:code,:name,:type,'pending',"
                "CAST(:keys AS jsonb),'active',:actor) RETURNING id,publisher_code,display_name,publisher_type,"
                "verification_status,status,created_at"
            ),
            {
                "code": payload.publisher_code,
                "name": payload.display_name,
                "type": payload.publisher_type,
                "keys": _json(key_manifest),
                "actor": actor_id,
            },
        )
    ).first()
    if row is None:
        raise VavError("SKILL_PUBLISHER_CREATE_FAILED", "Publisher could not be created.")
    await session.execute(
        text(
            "INSERT INTO skill_publisher_members (publisher_id,user_id,member_role) "
            "VALUES (:publisher,:actor,'owner')"
        ),
        {"publisher": row.id, "actor": actor_id},
    )
    await _audit(session, actor_id, "skill.publisher.created", "skill_publisher", row.id)
    await session.commit()
    return _mapping(row)


async def list_publishers(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,publisher_code,display_name,publisher_type,verification_status,status,"
                "created_at,verified_at,suspended_at FROM skill_publishers ORDER BY created_at DESC"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def decide_publisher(
    session: AsyncSession,
    publisher_id: UUID,
    actor_id: UUID,
    payload: PublisherDecisionRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE skill_publishers SET verification_status=CAST(:decision AS varchar),"
                "verified_at=CASE WHEN CAST(:decision AS varchar)='verified' THEN now() ELSE NULL END "
                "WHERE id=:id AND verification_status='pending' AND COALESCE(created_by,:actor)<>:actor "
                "AND NOT EXISTS (SELECT 1 FROM skill_publisher_members m WHERE m.publisher_id=:id "
                "AND m.user_id=:actor AND m.status='active') "
                "RETURNING id,publisher_code,display_name,publisher_type,verification_status,status,verified_at"
            ),
            {"decision": payload.decision, "id": publisher_id, "actor": actor_id},
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_PUBLISHER_REVIEW_REJECTED",
            "Publisher verification requires an independent pending review.",
            status_code=409,
        )
    await _audit(
        session,
        actor_id,
        f"skill.publisher.{payload.decision}",
        "skill_publisher",
        publisher_id,
        {"reason_code": payload.reason_code},
    )
    await session.commit()
    return _mapping(row)


async def publish_skill_version(
    session: AsyncSession,
    actor_id: UUID,
    payload: PublishSkillVersionRequest,
    *,
    artifact_store: SkillArtifactStore = skill_artifact_store,
) -> dict[str, Any]:
    publisher = (
        (
            await session.execute(
                text(
                    "SELECT p.* FROM skill_publishers p JOIN skill_publisher_members m "
                    "ON m.publisher_id=p.id WHERE p.id=:publisher AND m.user_id=:actor "
                    "AND m.status='active' AND m.member_role IN ('owner','release_manager') "
                    "AND p.status='active' AND p.verification_status='verified'"
                ),
                {"publisher": payload.publisher_id, "actor": actor_id},
            )
        )
        .mappings()
        .first()
    )
    if publisher is None:
        raise VavError(
            "SKILL_PUBLISHER_NOT_AUTHORIZED",
            "A verified publisher release manager is required.",
            status_code=403,
        )
    metadata = payload.manifest.get("metadata", {})
    if metadata.get("publisher") != publisher["publisher_code"]:
        raise VavError(
            "SKILL_PUBLISHER_MISMATCH",
            "Manifest publisher does not match the authenticated publisher.",
            status_code=422,
        )
    revoked = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM skill_signature_revocations WHERE publisher_id=:publisher "
            "AND key_id=:key AND (package_checksum IS NULL OR package_checksum=:checksum))"
        ),
        {
            "publisher": payload.publisher_id,
            "key": payload.signature_envelope.get("keyId", ""),
            "checksum": payload.package_checksum,
        },
    )
    if revoked:
        raise VavError(
            "SKILL_SIGNATURE_REVOKED", "The package signing key was revoked.", status_code=409
        )
    release = await asyncio.to_thread(
        validate_release,
        package_base64=payload.package_base64,
        package_checksum=payload.package_checksum,
        manifest=payload.manifest,
        signature_envelope=payload.signature_envelope,
        sbom=payload.sbom,
        provenance=payload.provenance,
        schemas={
            "input": payload.input_schema,
            "output": payload.output_schema,
            "error": payload.error_schema,
        },
        signing_key_manifest=publisher["signing_key_manifest"],
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:name,0))"),
        {"name": release.manifest["metadata"]["name"]},
    )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT s.publisher_id,v.id AS version_id FROM registered_skills s "
                    "LEFT JOIN registered_skill_versions v ON v.registered_skill_id=s.id "
                    "AND v.semantic_version=:version WHERE s.skill_name=:name"
                ),
                {
                    "name": release.manifest["metadata"]["name"],
                    "version": release.manifest["metadata"]["version"],
                },
            )
        )
        .mappings()
        .first()
    )
    if existing and existing["publisher_id"] != payload.publisher_id:
        raise VavError(
            "SKILL_NAME_OWNED_BY_ANOTHER_PUBLISHER",
            "Skill name is already owned by another publisher.",
            status_code=409,
        )
    if existing and existing["version_id"] is not None:
        raise VavError(
            "SKILL_VERSION_EXISTS",
            "This immutable Skill version is already registered.",
            status_code=409,
        )
    artifact_reference = await artifact_store.put(release)
    trust_level = {
        "official": "official_signed",
        "organization": "verified_publisher",
        "verified_partner": "verified_publisher",
        "community": "community_reviewed",
    }[publisher["publisher_type"]]
    skill = (
        await session.execute(
            text(
                "INSERT INTO registered_skills (skill_name,publisher_id,display_name,description,skill_type,"
                "visibility,trust_level,lifecycle_status) VALUES (:name,:publisher,:display,:description,:type,"
                "'organization_private',:trust,'active') ON CONFLICT (skill_name) DO UPDATE SET "
                "display_name=EXCLUDED.display_name,description=EXCLUDED.description,updated_at=now() "
                "WHERE registered_skills.publisher_id=EXCLUDED.publisher_id RETURNING id"
            ),
            {
                "name": metadata["name"],
                "publisher": payload.publisher_id,
                "display": metadata["displayName"],
                "description": metadata["description"],
                "type": payload.manifest["spec"]["type"],
                "trust": trust_level,
            },
        )
    ).first()
    if skill is None:
        raise VavError(
            "SKILL_NAME_OWNED_BY_ANOTHER_PUBLISHER",
            "Skill name is already owned by another publisher.",
            status_code=409,
        )
    version = (
        await session.execute(
            text(
                "INSERT INTO registered_skill_versions (registered_skill_id,semantic_version,manifest_version,"
                "runtime_api_version,manifest,manifest_checksum,package_reference_encrypted,package_checksum,"
                "sbom_reference_encrypted,provenance_reference_encrypted,signature_status,security_status,"
                "review_status,compatibility_status,input_schema,output_schema,error_schema,submitted_by,"
                "signature_key_id) VALUES (:skill,:version,:manifest_version,:runtime_version,CAST(:manifest AS jsonb),"
                ":manifest_checksum,:package_ref,:package_checksum,:sbom_ref,:provenance_ref,'verified','pending',"
                "'automated_review','pending',CAST(:input_schema AS jsonb),CAST(:output_schema AS jsonb),"
                "CAST(:error_schema AS jsonb),:actor,:key_id) RETURNING id,registered_skill_id,semantic_version,"
                "signature_status,security_status,review_status,compatibility_status,created_at"
            ),
            {
                "skill": skill.id,
                "version": metadata["version"],
                "manifest_version": payload.manifest["spec"]["manifestVersion"],
                "runtime_version": payload.manifest["spec"]["runtimeApiVersion"],
                "manifest": _json(release.manifest),
                "manifest_checksum": _checksum(release.manifest),
                "package_ref": encrypt_private(artifact_reference),
                "package_checksum": release.checksum,
                "sbom_ref": encrypt_private({"sha256": _checksum(payload.sbom)}),
                "provenance_ref": encrypt_private({"sha256": _checksum(payload.provenance)}),
                "input_schema": _json(payload.input_schema),
                "output_schema": _json(payload.output_schema),
                "error_schema": _json(payload.error_schema),
                "actor": actor_id,
                "key_id": release.key_id,
            },
        )
    ).first()
    assert version is not None
    for dependency_type in ("skills", "modules", "providers"):
        for dependency in payload.manifest["spec"]["dependencies"].get(dependency_type, []):
            name, constraint = next(iter(dependency.items()))
            await session.execute(
                text(
                    "INSERT INTO skill_dependencies (skill_version_id,dependency_type,dependency_name,"
                    "version_constraint,resolution_status) VALUES (:version,:type,:name,:constraint,'pending')"
                ),
                {
                    "version": version.id,
                    "type": dependency_type[:-1] if dependency_type != "skills" else "skill",
                    "name": name,
                    "constraint": constraint,
                },
            )
    await session.execute(
        text("UPDATE registered_skills SET latest_version_id=:version WHERE id=:skill"),
        {"version": version.id, "skill": skill.id},
    )
    await _audit(
        session,
        actor_id,
        "skill.version.submitted",
        "registered_skill_version",
        version.id,
        {"package_checksum": release.checksum, "signature_key_id": release.key_id},
    )
    await session.commit()
    return _mapping(version)


async def review_skill_version_security(
    session: AsyncSession,
    version_id: UUID,
    actor_id: UUID,
    payload: SecurityReviewRequest,
) -> dict[str, Any]:
    review_status = (
        "approved" if payload.decision in {"passed", "passed_with_warnings"} else "rejected"
    )
    compatibility_status = "compatible" if payload.compatible else "incompatible"
    row = (
        await session.execute(
            text(
                "UPDATE registered_skill_versions SET security_status=CAST(:decision AS varchar),"
                "review_status=CAST(:review_status AS varchar),"
                "compatibility_status=CAST(:compatibility AS varchar),security_reviewed_by=:actor,"
                "security_report=CAST(:report AS jsonb),published_at=CASE WHEN "
                "CAST(:review_status AS varchar)='approved' AND CAST(:compatibility AS varchar)='compatible' "
                "THEN now() ELSE NULL END,quarantined_at=CASE WHEN CAST(:decision AS varchar)='failed' "
                "THEN now() ELSE quarantined_at END,quarantine_reason_code=CASE WHEN "
                "CAST(:decision AS varchar)='failed' THEN CAST(:reason AS varchar) "
                "ELSE quarantine_reason_code END "
                "WHERE id=:id AND security_status='pending' AND signature_status='verified' "
                "AND COALESCE(submitted_by,:actor)<>:actor RETURNING *"
            ),
            {
                "decision": payload.decision,
                "review_status": review_status,
                "compatibility": compatibility_status,
                "actor": actor_id,
                "report": _json(payload.report),
                "reason": payload.reason_code,
                "id": version_id,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "SKILL_SECURITY_REVIEW_REJECTED",
            "Security review requires an independently submitted pending version.",
            status_code=409,
        )
    if review_status == "approved" and compatibility_status == "compatible":
        await session.execute(
            text(
                "UPDATE registered_skills SET current_stable_version_id=:version,latest_version_id=:version,"
                "updated_at=now() WHERE id=:skill"
            ),
            {"version": version_id, "skill": row.registered_skill_id},
        )
    await _audit(
        session,
        actor_id,
        "skill.version.security_reviewed",
        "registered_skill_version",
        version_id,
        {"decision": payload.decision, "reason_code": payload.reason_code},
    )
    await session.commit()
    return _mapping(row)


async def submit_listing(
    session: AsyncSession, actor_id: UUID, payload: MarketplaceListingRequest
) -> dict[str, Any]:
    if not get_settings().skill_marketplace_enabled:
        raise VavError(
            "SKILL_MARKETPLACE_DISABLED", "The Skill Marketplace is disabled.", status_code=503
        )
    version = await version_detail(session, payload.version_id)
    if version["skill_name"] != payload.skill_name:
        raise VavError(
            "MARKETPLACE_VERSION_MISMATCH",
            "Reviewed version does not belong to the Skill.",
            status_code=422,
        )
    report = automated_review(
        manifest=version["manifest"],
        signature_verified=version["signature_status"] == "verified",
        security_passed=version["security_status"] in {"passed", "passed_with_warnings"},
        compatible=version["compatibility_status"] == "compatible",
        sbom_present=bool(version.get("sbom_present")),
        provenance_present=bool(version.get("provenance_present")),
        privacy_disclosure=payload.privacy_disclosure,
        support_policy=payload.support_policy,
    )
    if not report.passed:
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
            "report": _json(report.canonical()),
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


async def _contain_version(
    session: AsyncSession,
    version_id: UUID,
    actor_id: UUID,
    reason_code: str,
    *,
    signature_revoked: bool,
) -> None:
    await session.execute(
        text(
            "UPDATE registered_skill_versions SET security_status='quarantined',quarantined_at=now(),"
            "quarantine_reason_code=:reason,signature_status=CASE WHEN :revoked THEN 'revoked' "
            "ELSE signature_status END,revoked_at=CASE WHEN :revoked THEN now() ELSE revoked_at END WHERE id=:id"
        ),
        {"reason": reason_code, "revoked": signature_revoked, "id": version_id},
    )
    await session.execute(
        text(
            "UPDATE skill_installations SET status='quarantined',disabled_at=now(),updated_at=now() "
            "WHERE installed_version_id=:id AND status NOT IN ('uninstalled','quarantined')"
        ),
        {"id": version_id},
    )
    await session.execute(
        text(
            "UPDATE skill_executions SET status=CASE WHEN status='running' THEN 'cancel_requested' ELSE 'cancelled' END,"
            "error_code='SKILL_VERSION_QUARANTINED',error_message_safe='Skill version was quarantined.',"
            "updated_at=now() WHERE skill_version_id=:id AND status IN "
            "('created','validating','authorizing','queued','running','waiting_for_dependency')"
        ),
        {"id": version_id},
    )
    await session.execute(
        text(
            "UPDATE marketplace_listings SET listing_status='removed',visibility='unlisted',suspended_at=now(),"
            "updated_at=now() WHERE reviewed_version_id=:id AND listing_status<>'removed'"
        ),
        {"id": version_id},
    )
    await session.execute(
        text(
            "UPDATE registered_skills SET lifecycle_status='quarantined',trust_level='quarantined',updated_at=now() "
            "WHERE id=(SELECT registered_skill_id FROM registered_skill_versions WHERE id=:id)"
        ),
        {"id": version_id},
    )
    await session.execute(
        text(
            "INSERT INTO skill_security_incidents (skill_version_id,severity,reason_code,evidence,created_by) "
            "SELECT id,'critical',:reason,jsonb_build_object('package_checksum',package_checksum,"
            "'signature_key_id',signature_key_id),:actor FROM registered_skill_versions WHERE id=:id"
        ),
        {"reason": reason_code, "actor": actor_id, "id": version_id},
    )


async def quarantine_skill_version(
    session: AsyncSession, version_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    exists = await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM registered_skill_versions WHERE id=:id)"),
        {"id": version_id},
    )
    if not exists:
        raise VavError("SKILL_VERSION_NOT_FOUND", "Skill version was not found.", status_code=404)
    await _contain_version(session, version_id, actor_id, reason_code, signature_revoked=False)
    await _audit(
        session,
        actor_id,
        "skill.security.quarantined",
        "registered_skill_version",
        version_id,
        {"reason_code": reason_code},
    )
    await session.commit()
    return await version_detail(session, version_id)


async def revoke_signature(
    session: AsyncSession,
    actor_id: UUID,
    payload: SignatureRevocationRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO skill_signature_revocations (publisher_id,key_id,package_checksum,reason_code,"
                "reason_encrypted,revoked_by) SELECT :publisher,:key,:checksum,:reason,:detail,:actor "
                "WHERE EXISTS (SELECT 1 FROM skill_publishers WHERE id=:publisher) RETURNING *"
            ),
            {
                "publisher": payload.publisher_id,
                "key": payload.key_id,
                "checksum": payload.package_checksum,
                "reason": payload.reason_code,
                "detail": encrypt_private(payload.reason),
                "actor": actor_id,
            },
        )
    ).first()
    if row is None:
        raise VavError("SKILL_PUBLISHER_NOT_FOUND", "Publisher was not found.", status_code=404)
    versions = (
        await session.execute(
            text(
                "SELECT v.id FROM registered_skill_versions v JOIN registered_skills s "
                "ON s.id=v.registered_skill_id WHERE s.publisher_id=:publisher AND v.signature_key_id=:key "
                "AND (CAST(:checksum AS varchar) IS NULL "
                "OR v.package_checksum=CAST(:checksum AS varchar))"
            ),
            {
                "publisher": payload.publisher_id,
                "key": payload.key_id,
                "checksum": payload.package_checksum,
            },
        )
    ).all()
    for version in versions:
        await _contain_version(
            session, version.id, actor_id, payload.reason_code, signature_revoked=True
        )
    await _audit(
        session,
        actor_id,
        "skill.signature.revoked",
        "skill_publisher",
        payload.publisher_id,
        {
            "key_id": payload.key_id,
            "package_checksum": payload.package_checksum,
            "affected_versions": len(versions),
        },
    )
    await session.commit()
    result = _mapping(row)
    result["affected_versions"] = len(versions)
    return result


async def list_security_incidents(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT i.id,i.skill_version_id,i.listing_id,i.severity,i.status,i.reason_code,i.evidence,"
                "i.created_at,i.resolved_at,s.skill_name,v.semantic_version FROM skill_security_incidents i "
                "LEFT JOIN registered_skill_versions v ON v.id=i.skill_version_id "
                "LEFT JOIN registered_skills s ON s.id=v.registered_skill_id ORDER BY i.created_at DESC"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def remove_listing(
    session: AsyncSession, listing_id: UUID, actor_id: UUID, reason_code: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE marketplace_listings SET listing_status='removed',visibility='unlisted',"
                "suspended_at=now(),updated_at=now() WHERE id=:id AND listing_status<>'removed' RETURNING *"
            ),
            {"id": listing_id},
        )
    ).first()
    if row is None:
        raise VavError("MARKETPLACE_STATE_CONFLICT", "Listing cannot be removed.", status_code=409)
    await _audit(
        session,
        actor_id,
        "skill.marketplace.removed",
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
    payload: AppealRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO marketplace_appeals (listing_id,publisher_id,reason_code,statement_encrypted,submitted_by) "
                "SELECT l.id,s.publisher_id,:reason,:statement,:actor FROM marketplace_listings l "
                "JOIN registered_skills s ON s.id=l.registered_skill_id "
                "JOIN skill_publisher_members m ON m.publisher_id=s.publisher_id AND m.user_id=:actor "
                "WHERE l.id=:listing AND l.listing_status IN ('changes_required','suspended','removed') "
                "AND m.status='active' RETURNING *"
            ),
            {
                "listing": listing_id,
                "reason": payload.reason_code,
                "statement": encrypt_private(payload.statement),
                "actor": actor_id,
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


async def decide_appeal(
    session: AsyncSession,
    appeal_id: UUID,
    actor_id: UUID,
    payload: AppealDecisionRequest,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE marketplace_appeals a SET status=:decision,decided_by=:actor,"
                "decision_reason_encrypted=:reason,decided_at=now() WHERE a.id=:id AND a.status='pending' "
                "AND COALESCE(a.submitted_by,:actor)<>:actor AND NOT EXISTS "
                "(SELECT 1 FROM skill_publisher_members m WHERE m.publisher_id=a.publisher_id "
                "AND m.user_id=:actor AND m.status='active') RETURNING *"
            ),
            {
                "decision": payload.decision,
                "actor": actor_id,
                "reason": encrypt_private(payload.reason),
                "id": appeal_id,
            },
        )
    ).first()
    if row is None:
        raise VavError(
            "MARKETPLACE_APPEAL_REVIEW_REJECTED",
            "Appeal decision requires an independent pending review.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE marketplace_listings SET listing_status=CASE WHEN :decision='accepted' "
            "THEN 'human_review' ELSE 'suspended' END,updated_at=now() WHERE id=:listing"
        ),
        {"decision": payload.decision, "listing": row.listing_id},
    )
    await _audit(
        session,
        actor_id,
        f"skill.marketplace.appeal_{payload.decision}",
        "marketplace_listing",
        row.listing_id,
    )
    await session.commit()
    return _mapping(row)
