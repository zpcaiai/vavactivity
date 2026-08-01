# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.privacy.crypto import (
    decrypt_private,
    encrypt_private,
    searchable_hmac,
)
from vav.modules.privacy.providers import provider_registry
from vav.modules.privacy.schemas import (
    AiMemoryCandidateRequest,
    PrivacySettingsUpdateRequest,
    ProfileUpdateRequest,
)

ACTIVE_REQUEST_STATUSES = {
    "submitted",
    "identity_verification_required",
    "verified",
    "in_review",
    "approved",
    "processing",
    "partially_completed",
}
FORBIDDEN_MEMORY_TERMS = {
    "password",
    "密码",
    "credit card",
    "银行卡",
    "cvv",
    "身份证",
    "passport",
    "private key",
    "安全转介",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def audit(
    session: AsyncSession,
    event_type: str,
    subject_type: str,
    subject_id: UUID | None,
    *,
    actor_id: UUID | None = None,
    reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO privacy_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,safe_context) "
            "VALUES (:event_type,:actor_id,:subject_type,:subject_id,:reason,CAST(:context AS jsonb))"
        ),
        {
            "event_type": event_type,
            "actor_id": actor_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "reason": reason,
            "context": json_value(context or {}),
        },
    )


async def ensure_privacy_defaults(session: AsyncSession, user: User) -> None:
    await session.execute(
        text(
            "INSERT INTO user_profiles "
            "(user_id,display_name,preferred_locale,timezone,profile_status) "
            "VALUES (:user_id,:display_name,:locale,:timezone,'incomplete') ON CONFLICT (user_id) DO NOTHING"
        ),
        {
            "user_id": user.id,
            "display_name": user.display_email,
            "locale": user.preferred_locale,
            "timezone": user.timezone,
        },
    )
    await session.execute(
        text(
            "INSERT INTO user_privacy_settings (user_id,privacy_mode) "
            "VALUES (:user_id,'strict') ON CONFLICT (user_id) DO NOTHING"
        ),
        {"user_id": user.id},
    )
    await session.execute(
        text(
            "INSERT INTO ai_memory_preferences (user_id) VALUES (:user_id) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"user_id": user.id},
    )
    await session.commit()


def age_range(date_of_birth: date | None) -> str | None:
    if date_of_birth is None:
        return None
    today = utcnow().date()
    age = (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )
    lower = max((age // 5) * 5, 18)
    return f"{lower}-{lower + 4}"


async def profile_view(
    session: AsyncSession, user: User, *, include_sensitive: bool = True
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, user)
    row = (
        (
            await session.execute(
                text("SELECT * FROM user_profiles WHERE user_id=:user_id"), {"user_id": user.id}
            )
        )
        .mappings()
        .one()
    )
    result = {
        "user_id": str(user.id),
        "display_name": row["display_name"],
        "avatar_media_id": row["avatar_media_id"],
        "gender_code": row["gender_code"],
        "country_code": row["country_code"],
        "region": row["region"],
        "city": row["city"],
        "preferred_locale": row["preferred_locale"],
        "timezone": row["timezone"],
        "public_bio": row["public_bio"],
        "profile_status": row["profile_status"],
        "completeness_basis_points": row["completeness_basis_points"],
        "version": row["version"],
    }
    if include_sensitive:
        result["legal_name"] = (
            decrypt_private(row["legal_name_encrypted"]) if row["legal_name_encrypted"] else None
        )
        birth_date = (
            date.fromisoformat(str(decrypt_private(row["date_of_birth_encrypted"])))
            if row["date_of_birth_encrypted"]
            else None
        )
        result["date_of_birth"] = birth_date
        result["age_range"] = age_range(birth_date)
    return result


def profile_completeness(payload: dict[str, Any]) -> int:
    tracked = [
        "display_name",
        "country_code",
        "region",
        "city",
        "preferred_locale",
        "timezone",
        "public_bio",
    ]
    present = sum(1 for field in tracked if payload.get(field))
    return int(present / len(tracked) * 10000)


async def update_profile(
    session: AsyncSession, user: User, payload: ProfileUpdateRequest
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, user)
    current = (
        (
            await session.execute(
                text("SELECT * FROM user_profiles WHERE user_id=:user_id FOR UPDATE"),
                {"user_id": user.id},
            )
        )
        .mappings()
        .one()
    )
    if int(current["version"]) != payload.version:
        raise VavError(
            "PRIVACY_PROFILE_VERSION_CONFLICT", "Profile was updated elsewhere.", status_code=409
        )
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("version", None)
    merged = {**dict(current), **changes}
    try:
        ZoneInfo(str(merged["timezone"]))
    except ZoneInfoNotFoundError as exc:
        raise VavError("PRIVACY_TIMEZONE_INVALID", "Timezone is invalid.", status_code=422) from exc
    legal_name = changes.pop("legal_name", None) if "legal_name" in changes else None
    date_of_birth = changes.pop("date_of_birth", None) if "date_of_birth" in changes else None
    if date_of_birth and date_of_birth > utcnow().date() - timedelta(days=18 * 365):
        raise VavError(
            "PRIVACY_AGE_POLICY",
            "The general profile requires an adult date of birth.",
            status_code=422,
        )
    completeness = profile_completeness(merged)
    await session.execute(
        text(
            "UPDATE user_profiles SET display_name=COALESCE(:display_name,display_name),"
            "legal_name_encrypted=CASE WHEN :legal_name_set THEN :legal_name ELSE legal_name_encrypted END,"
            "date_of_birth_encrypted=CASE WHEN :dob_set THEN :dob ELSE date_of_birth_encrypted END,"
            "gender_code=COALESCE(:gender_code,gender_code),country_code=COALESCE(:country_code,country_code),"
            "region=COALESCE(:region,region),city=COALESCE(:city,city),"
            "preferred_locale=COALESCE(:locale,preferred_locale),timezone=COALESCE(:timezone,timezone),"
            "public_bio=COALESCE(:public_bio,public_bio),completeness_basis_points=:completeness,"
            "profile_status=CASE WHEN :completeness>=6000 THEN 'active' ELSE 'incomplete' END,"
            "version=version+1,updated_at=now() WHERE user_id=:user_id AND version=:version"
        ),
        {
            "display_name": changes.get("display_name"),
            "legal_name_set": "legal_name" in payload.model_fields_set,
            "legal_name": encrypt_private(legal_name) if legal_name else None,
            "dob_set": "date_of_birth" in payload.model_fields_set,
            "dob": encrypt_private(date_of_birth.isoformat()) if date_of_birth else None,
            "gender_code": changes.get("gender_code"),
            "country_code": changes.get("country_code"),
            "region": changes.get("region"),
            "city": changes.get("city"),
            "locale": changes.get("preferred_locale"),
            "timezone": changes.get("timezone"),
            "public_bio": changes.get("public_bio"),
            "completeness": completeness,
            "user_id": user.id,
            "version": payload.version,
        },
    )
    if changes.get("preferred_locale") or changes.get("timezone"):
        await session.execute(
            text(
                "UPDATE users SET preferred_locale=COALESCE(:locale,preferred_locale),"
                "timezone=COALESCE(:timezone,timezone),updated_at=now() WHERE id=:user_id"
            ),
            {
                "locale": changes.get("preferred_locale"),
                "timezone": changes.get("timezone"),
                "user_id": user.id,
            },
        )
    await audit(
        session,
        "privacy.profile.updated",
        "user",
        user.id,
        actor_id=user.id,
        context={"fields": sorted(payload.model_fields_set - {"version"})},
    )
    await session.commit()
    return await profile_view(session, user)


async def update_privacy_settings(
    session: AsyncSession, user: User, payload: PrivacySettingsUpdateRequest
) -> dict[str, Any]:
    await ensure_privacy_defaults(session, user)
    updated = await session.scalar(
        text(
            "UPDATE user_privacy_settings SET searchable_by_platform_users=:searchable,"
            "visible_in_activity_directory=:activity,visible_in_matchmaking=:matchmaking,"
            "allow_contact_exchange_after_mutual_confirmation=:contact_exchange,"
            "allow_profile_use_by_ai=:profile_ai,allow_service_history_use_by_ai=:history_ai,"
            "privacy_mode=:mode,settings_version=settings_version+1,updated_at=now() "
            "WHERE user_id=:user_id AND settings_version=:version RETURNING settings_version"
        ),
        {
            "searchable": payload.searchable_by_platform_users,
            "activity": payload.visible_in_activity_directory,
            "matchmaking": payload.visible_in_matchmaking,
            "contact_exchange": payload.allow_contact_exchange_after_mutual_confirmation,
            "profile_ai": payload.allow_profile_use_by_ai,
            "history_ai": payload.allow_service_history_use_by_ai,
            "mode": payload.privacy_mode.value,
            "user_id": user.id,
            "version": payload.settings_version,
        },
    )
    if updated is None:
        raise VavError(
            "PRIVACY_SETTINGS_VERSION_CONFLICT",
            "Privacy settings were updated elsewhere.",
            status_code=409,
        )
    for rule in payload.field_rules:
        await session.execute(
            text(
                "INSERT INTO user_field_visibility_rules "
                "(user_id,data_domain,field_code,visibility,allowed_purposes,allowed_recipient_types,valid_until) "
                "VALUES (:user_id,:domain,:field,:visibility,CAST(:purposes AS jsonb),CAST(:recipients AS jsonb),:valid_until) "
                "ON CONFLICT (user_id,data_domain,field_code) DO UPDATE SET visibility=EXCLUDED.visibility,"
                "allowed_purposes=EXCLUDED.allowed_purposes,allowed_recipient_types=EXCLUDED.allowed_recipient_types,"
                "valid_until=EXCLUDED.valid_until,updated_at=now()"
            ),
            {
                "user_id": user.id,
                "domain": rule.data_domain,
                "field": rule.field_code,
                "visibility": rule.visibility.value,
                "purposes": json_value(rule.allowed_purposes),
                "recipients": json_value(rule.allowed_recipient_types),
                "valid_until": rule.valid_until,
            },
        )
    await audit(
        session,
        "privacy.visibility.updated",
        "user",
        user.id,
        actor_id=user.id,
        context={"mode": payload.privacy_mode.value, "cache_invalidated": True},
    )
    await session.commit()
    return {"settings_version": int(updated), "cache_invalidated": True}


async def grant_consent(
    session: AsyncSession,
    user_id: UUID,
    consent_code: str,
    release_id: UUID,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    release = (
        (
            await session.execute(
                text(
                    "SELECT r.*,d.consent_code,d.scope_definition FROM consent_releases r "
                    "JOIN consent_definitions d ON d.id=r.consent_definition_id "
                    "WHERE r.id=:id AND d.consent_code=:code AND r.status='active' "
                    "AND r.valid_from<=now() AND (r.valid_until IS NULL OR r.valid_until>now())"
                ),
                {"id": release_id, "code": consent_code},
            )
        )
        .mappings()
        .first()
    )
    if release is None:
        raise VavError(
            "PRIVACY_CONSENT_RELEASE_INVALID", "Consent release is not active.", status_code=409
        )
    await session.execute(
        text(
            "UPDATE user_consents SET status='superseded',updated_at=now() WHERE user_id=:user_id "
            "AND consent_definition_id=:definition_id AND status='granted'"
        ),
        {"user_id": user_id, "definition_id": release["consent_definition_id"]},
    )
    consent_id = await session.scalar(
        text(
            "INSERT INTO user_consents "
            "(user_id,consent_definition_id,consent_release_id,status,scope_snapshot,source,evidence,granted_at) "
            "VALUES (:user_id,:definition_id,:release_id,'granted',CAST(:scope AS jsonb),'account',"
            "CAST(:evidence AS jsonb),now()) RETURNING id"
        ),
        {
            "user_id": user_id,
            "definition_id": release["consent_definition_id"],
            "release_id": release_id,
            "scope": json_value(release["scope_definition"]),
            "evidence": json_value(evidence),
        },
    )
    if consent_code == "marketing_email":
        await session.execute(
            text(
                "INSERT INTO notification_consents (user_id,consent_type,consent_version,status,granted_at,source,evidence) "
                "VALUES (:user_id,'marketing_email',:version,'granted',now(),'privacy_control_plane',CAST(:evidence AS jsonb)) "
                "ON CONFLICT (user_id,consent_type,consent_version) DO UPDATE SET status='granted',"
                "granted_at=now(),withdrawn_at=NULL,updated_at=now()"
            ),
            {
                "user_id": user_id,
                "version": release["semantic_version"],
                "evidence": json_value(evidence),
            },
        )
    await audit(
        session,
        "privacy.consent.granted",
        "consent",
        UUID(str(consent_id)),
        actor_id=user_id,
        context={"consent_code": consent_code, "release_id": str(release_id)},
    )
    await session.commit()
    return {"id": str(consent_id), "status": "granted", "consent_code": consent_code}


async def withdraw_consent(
    session: AsyncSession, user_id: UUID, consent_code: str
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT c.id,c.withdrawable,u.id AS user_consent_id FROM consent_definitions c "
                    "JOIN user_consents u ON u.consent_definition_id=c.id "
                    "WHERE c.consent_code=:code AND u.user_id=:user_id AND u.status='granted' "
                    "ORDER BY u.created_at DESC LIMIT 1 FOR UPDATE OF u"
                ),
                {"code": consent_code, "user_id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "PRIVACY_CONSENT_NOT_GRANTED", "Consent is not currently granted.", status_code=409
        )
    if not row["withdrawable"]:
        raise VavError(
            "PRIVACY_CONSENT_NOT_WITHDRAWABLE",
            "This service consent cannot be withdrawn here.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE user_consents SET status='withdrawn',withdrawn_at=now(),updated_at=now() WHERE id=:id"
        ),
        {"id": row["user_consent_id"]},
    )
    propagation: list[str] = []
    if consent_code == "marketing_email":
        await session.execute(
            text(
                "UPDATE notification_consents SET status='withdrawn',withdrawn_at=now(),updated_at=now() WHERE user_id=:user_id AND consent_type='marketing_email' AND status='granted'"
            ),
            {"user_id": user_id},
        )
        propagation.append("notifications.marketing_stopped")
    if consent_code in {
        "ai_long_term_memory",
        "ai_profile_context_access",
        "ai_service_history_access",
    }:
        await session.execute(
            text(
                "UPDATE ai_memory_preferences SET long_term_memory_enabled=false,allow_profile_facts=false,"
                "allow_service_history=false,allow_relationship_context=false,allow_cross_conversation_use=false,"
                "consent_id=NULL,settings_version=settings_version+1,updated_at=now() WHERE user_id=:user_id"
            ),
            {"user_id": user_id},
        )
        await session.execute(
            text(
                "UPDATE ai_memory_items SET status='rejected',updated_at=now() WHERE user_id=:user_id AND status IN ('candidate','user_approval_required')"
            ),
            {"user_id": user_id},
        )
        propagation.extend(
            ["ai_memory.reads_stopped", "ai_memory.writes_stopped", "ai_memory.cache_invalidated"]
        )
    if consent_code == "activity_directory_visibility":
        await session.execute(
            text(
                "UPDATE user_privacy_settings SET visible_in_activity_directory=false,settings_version=settings_version+1,updated_at=now() WHERE user_id=:user_id"
            ),
            {"user_id": user_id},
        )
        propagation.append("activity_directory.cache_invalidated")
    await audit(
        session,
        "privacy.consent.withdrawn",
        "consent",
        UUID(str(row["user_consent_id"])),
        actor_id=user_id,
        context={"consent_code": consent_code, "propagation": propagation},
    )
    await session.commit()
    return {"status": "withdrawn", "consent_code": consent_code, "propagation": propagation}


def verify_password(user: User, password: str) -> None:
    if not PasswordHasher().verify(user.password_hash, password):
        raise VavError(
            "PRIVACY_REAUTHENTICATION_FAILED", "Password verification failed.", status_code=401
        )


def request_number(prefix: str) -> str:
    return f"{prefix}-{utcnow():%Y%m%d}-{secrets.token_hex(5).upper()}"


async def create_request(
    session: AsyncSession,
    *,
    user: User,
    request_type: str,
    requested_scope: dict[str, Any],
    requested_format: str | None = None,
    password: str | None = None,
) -> UUID:
    if password is not None:
        verify_password(user, password)
    active_count = await session.scalar(
        text(
            "SELECT count(*) FROM data_subject_requests WHERE user_id=:user_id AND status=ANY(:statuses)"
        ),
        {"user_id": user.id, "statuses": list(ACTIVE_REQUEST_STATUSES)},
    )
    if int(active_count or 0) >= get_settings().privacy_request_max_active_per_user:
        raise VavError(
            "PRIVACY_REQUEST_LIMIT", "Too many active privacy requests.", status_code=429
        )
    prefix = {"inventory": "PRI", "export": "PRE", "correction": "PRC", "erasure": "PRD"}.get(
        request_type, "PRQ"
    )
    status = "verified" if password is not None else "submitted"
    try:
        value = await session.scalar(
            text(
                "INSERT INTO data_subject_requests "
                "(request_number,user_id,request_type,status,requested_scope,requested_format,"
                "identity_verification_level,identity_verified_at,reauthenticated_at,submitted_at,due_at) "
                "VALUES (:number,:user_id,:type,:status,CAST(:scope AS jsonb),:format,:verification,"
                ":verified_at,:verified_at,now(),now()+:due_interval) RETURNING id"
            ),
            {
                "number": request_number(prefix),
                "user_id": user.id,
                "type": request_type,
                "status": status,
                "scope": json_value(requested_scope),
                "format": requested_format,
                "verification": "password" if password is not None else "session",
                "verified_at": utcnow() if password is not None else None,
                "due_interval": timedelta(days=get_settings().privacy_request_default_due_days),
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "PRIVACY_REQUEST_ALREADY_ACTIVE",
            "An active request of this type already exists.",
            status_code=409,
        ) from exc
    request_id = UUID(str(value))
    await session.execute(
        text(
            "INSERT INTO privacy_request_events (data_subject_request_id,event_type,actor_id) VALUES (:id,'submitted',:actor)"
        ),
        {"id": request_id, "actor": user.id},
    )
    await audit(
        session,
        "privacy.request.submitted",
        "data_subject_request",
        request_id,
        actor_id=user.id,
        context={"request_type": request_type},
    )
    await session.commit()
    return request_id


async def inventory_for_user(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    results = []
    for provider in provider_registry().values():
        result = await provider.inventory(session, user_id)
        results.append(
            {
                "module_code": result.module_code,
                "schema_version": result.schema_version,
                "assets": result.assets,
            }
        )
    return results


async def process_inventory_request(session: AsyncSession, request_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM data_subject_requests WHERE id=:id FOR UPDATE"),
                {"id": request_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["request_type"] != "inventory":
        raise VavError(
            "PRIVACY_REQUEST_NOT_FOUND", "Inventory request was not found.", status_code=404
        )
    inventory = await inventory_for_user(session, UUID(str(row["user_id"])))
    for module in inventory:
        await session.execute(
            text(
                "INSERT INTO privacy_module_request_results "
                "(data_subject_request_id,module_code,operation,status,schema_version,result_manifest,attempts,completed_at) "
                "VALUES (:request_id,:module,'inventory','completed',:version,CAST(:manifest AS jsonb),1,now()) "
                "ON CONFLICT (data_subject_request_id,module_code,operation) DO UPDATE SET status='completed',"
                "result_manifest=EXCLUDED.result_manifest,attempts=privacy_module_request_results.attempts+1,completed_at=now(),updated_at=now()"
            ),
            {
                "request_id": request_id,
                "module": module["module_code"],
                "version": module["schema_version"],
                "manifest": json_value(module),
            },
        )
    await session.execute(
        text(
            "UPDATE data_subject_requests SET status='completed',completed_at=now(),updated_at=now() WHERE id=:id"
        ),
        {"id": request_id},
    )
    await audit(
        session,
        "privacy.request.completed",
        "data_subject_request",
        request_id,
        actor_id=UUID(str(row["user_id"])),
        context={"modules": [item["module_code"] for item in inventory]},
    )
    await session.commit()
    return {"request_id": str(request_id), "status": "completed", "inventory": inventory}


async def process_export_request(session: AsyncSession, request_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM data_subject_requests WHERE id=:id FOR UPDATE"),
                {"id": request_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["request_type"] != "export":
        raise VavError(
            "PRIVACY_REQUEST_NOT_FOUND", "Export request was not found.", status_code=404
        )
    if row["identity_verified_at"] is None:
        raise VavError(
            "PRIVACY_IDENTITY_VERIFICATION_REQUIRED",
            "Export requires recent identity verification.",
            status_code=409,
        )
    requested_modules = set(row["requested_scope"].get("modules") or provider_registry())
    unknown = requested_modules - set(provider_registry())
    if unknown:
        raise VavError(
            "PRIVACY_EXPORT_MODULE_INVALID",
            "Export includes an unsupported module.",
            details=[{"unknown": sorted(unknown)}],
            status_code=422,
        )
    await session.execute(
        text("UPDATE data_subject_requests SET status='processing',updated_at=now() WHERE id=:id"),
        {"id": request_id},
    )
    exports: dict[str, Any] = {}
    completed: list[str] = []
    failed: list[dict[str, str]] = []
    for module in sorted(requested_modules):
        provider = provider_registry()[module]
        try:
            async with session.begin_nested():
                exports[module] = await provider.export(session, UUID(str(row["user_id"])))
            completed.append(module)
            module_status = "completed"
            error_code = None
        except Exception:
            module_status = "failed"
            error_code = "PRIVACY_MODULE_EXPORT_FAILED"
            failed.append({"module_code": module, "error_code": error_code})
        await session.execute(
            text(
                "INSERT INTO privacy_module_request_results "
                "(data_subject_request_id,module_code,operation,status,schema_version,result_manifest,error_code,attempts,completed_at) "
                "VALUES (:request_id,:module,'export',:status,:version,CAST(:manifest AS jsonb),:error,1,"
                ":completed_at) "
                "ON CONFLICT (data_subject_request_id,module_code,operation) DO UPDATE SET status=EXCLUDED.status,"
                "result_manifest=EXCLUDED.result_manifest,error_code=EXCLUDED.error_code,"
                "attempts=privacy_module_request_results.attempts+1,completed_at=EXCLUDED.completed_at,updated_at=now()"
            ),
            {
                "request_id": request_id,
                "module": module,
                "status": module_status,
                "version": provider.schema_version,
                "manifest": json_value({"included": module_status == "completed"}),
                "error": error_code,
                "completed_at": utcnow() if module_status == "completed" else None,
            },
        )
    manifest = {
        "schema_version": "1.0",
        "generated_at": utcnow().isoformat(),
        "subject_request_id": str(request_id),
        "modules": completed,
        "failed_modules": failed,
    }
    status = "partially_completed" if failed else "completed"
    archive = encrypt_private({"manifest": manifest, "data": exports}).encode()
    checksum = hashlib.sha256(archive).hexdigest()
    await session.execute(
        text(
            "INSERT INTO privacy_export_jobs "
            "(data_subject_request_id,status,export_format,module_manifest,completed_modules,failed_modules,"
            "archive_encrypted,archive_checksum_sha256,encryption_mode,archive_expires_at,started_at,completed_at) "
            "VALUES (:request_id,:status,:format,CAST(:manifest AS jsonb),CAST(:completed AS jsonb),"
            "CAST(:failed AS jsonb),:archive,:checksum,'fernet',:expires,now(),now()) "
            "ON CONFLICT (data_subject_request_id) DO UPDATE SET status=EXCLUDED.status,module_manifest=EXCLUDED.module_manifest,"
            "completed_modules=EXCLUDED.completed_modules,failed_modules=EXCLUDED.failed_modules,archive_encrypted=EXCLUDED.archive_encrypted,"
            "archive_checksum_sha256=EXCLUDED.archive_checksum_sha256,archive_expires_at=EXCLUDED.archive_expires_at,completed_at=now(),updated_at=now()"
        ),
        {
            "request_id": request_id,
            "status": status,
            "format": row["requested_format"] or "json",
            "manifest": json_value(manifest),
            "completed": json_value(completed),
            "failed": json_value(failed),
            "archive": archive,
            "checksum": checksum,
            "expires": utcnow()
            + timedelta(days=get_settings().privacy_export_archive_retention_days),
        },
    )
    await session.execute(
        text(
            "UPDATE data_subject_requests SET status=:status,completed_at=:completed_at,updated_at=now() WHERE id=:id"
        ),
        {
            "status": status,
            "completed_at": utcnow() if status == "completed" else None,
            "id": request_id,
        },
    )
    await audit(
        session,
        "privacy.export.completed" if not failed else "privacy.export.failed",
        "data_subject_request",
        request_id,
        context={
            "completed_modules": completed,
            "failed_modules": [item["module_code"] for item in failed],
        },
    )
    await session.commit()
    return {
        "request_id": str(request_id),
        "status": status,
        "completed_modules": completed,
        "failed_modules": failed,
        "checksum_sha256": checksum,
    }


async def issue_export_download_token(
    session: AsyncSession, user_id: UUID, request_id: UUID
) -> str:
    token = secrets.token_urlsafe(32)
    value = await session.scalar(
        text(
            "UPDATE privacy_export_jobs e SET download_token_hash=:hash,download_expires_at=:expires,downloaded_at=NULL,updated_at=now() "
            "FROM data_subject_requests r WHERE e.data_subject_request_id=r.id AND r.id=:request_id "
            "AND r.user_id=:user_id AND e.status='completed' AND e.archive_expires_at>now() RETURNING e.id"
        ),
        {
            "hash": searchable_hmac(token),
            "expires": utcnow() + timedelta(hours=get_settings().privacy_export_download_ttl_hours),
            "request_id": request_id,
            "user_id": user_id,
        },
    )
    if value is None:
        raise VavError(
            "PRIVACY_EXPORT_NOT_READY", "Export is not ready for download.", status_code=409
        )
    await session.commit()
    return token


async def consume_export_download(session: AsyncSession, user_id: UUID, token: str) -> bytes:
    row = (
        (
            await session.execute(
                text(
                    "SELECT e.id,e.archive_encrypted,r.id AS request_id FROM privacy_export_jobs e "
                    "JOIN data_subject_requests r ON r.id=e.data_subject_request_id "
                    "WHERE r.user_id=:user_id AND e.download_token_hash=:hash AND e.downloaded_at IS NULL "
                    "AND e.download_expires_at>now() AND e.archive_expires_at>now() FOR UPDATE OF e"
                ),
                {"user_id": user_id, "hash": searchable_hmac(token)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "PRIVACY_EXPORT_TOKEN_INVALID", "Export token is invalid or expired.", status_code=404
        )
    await session.execute(
        text(
            "UPDATE privacy_export_jobs SET downloaded_at=now(),download_token_hash=NULL,updated_at=now() WHERE id=:id"
        ),
        {"id": row["id"]},
    )
    await audit(
        session,
        "privacy.export.downloaded",
        "data_subject_request",
        UUID(str(row["request_id"])),
        actor_id=user_id,
    )
    await session.commit()
    return bytes(row["archive_encrypted"])


async def erasure_blockers(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    checks = [
        (
            "unfinished_order",
            "SELECT count(*) FROM orders WHERE user_id=:user_id AND status IN ('draft','pending_payment','payment_processing')",
        ),
        (
            "future_activity",
            "SELECT count(*) FROM activity_registrations r JOIN activities a ON a.id=r.activity_id WHERE r.user_id=:user_id AND r.status NOT IN ('cancelled','rejected','refunded') AND a.starts_at>now()",
        ),
        (
            "future_appointment",
            "SELECT count(*) FROM counseling_appointments WHERE user_id=:user_id AND status IN ('requested','proposed','confirmed','reschedule_requested') AND scheduled_starts_at>now()",
        ),
        (
            "active_subscription",
            "SELECT count(*) FROM subscriptions WHERE user_id=:user_id AND status IN ('active','trialing','past_due')",
        ),
        (
            "open_ai_referral",
            "SELECT count(*) FROM ai_human_referrals WHERE user_id=:user_id AND status NOT IN ('resolved','cancelled')",
        ),
    ]
    for code, query in checks:
        count = int(await session.scalar(text(query), {"user_id": user_id}) or 0)
        if count:
            blockers.append(
                {
                    "code": code,
                    "count": count,
                    "resolution": "Complete or cancel the active service before reevaluation.",
                }
            )
    hold_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,scope_definition_encrypted,ends_at FROM privacy_legal_holds WHERE status='active' AND starts_at<=now() AND (ends_at IS NULL OR ends_at>now())"
                )
            )
        )
        .mappings()
        .all()
    )
    for hold in hold_rows:
        scope = decrypt_private(hold["scope_definition_encrypted"])
        if scope.get("subject_user_id") == str(user_id):
            blockers.append(
                {
                    "code": "active_hold",
                    "hold_id": str(hold["id"]),
                    "resolution": "The scoped hold must expire or be released by an authorized officer.",
                }
            )
    return blockers


async def create_erasure_plan(
    session: AsyncSession, request_id: UUID, user_id: UUID
) -> dict[str, Any]:
    plans = []
    for provider in provider_registry().values():
        plan = await provider.plan_erasure(session, user_id)
        plans.append(
            {
                "module_code": plan.module_code,
                "operation": plan.operation,
                "retained_assets": plan.retained_assets,
            }
        )
    blockers = await erasure_blockers(session, user_id)
    status = (
        "blocked_by_active_service"
        if any(item["code"] != "active_hold" for item in blockers)
        else "blocked_by_hold"
        if blockers
        else "planned"
    )
    plan_id = await session.scalar(
        text(
            "INSERT INTO privacy_erasure_plans "
            "(data_subject_request_id,user_id,status,module_plans,blocking_conditions,retention_exceptions,"
            "user_confirmation_required,planned_at) VALUES (:request_id,:user_id,:status,CAST(:plans AS jsonb),"
            "CAST(:blockers AS jsonb),CAST(:retained AS jsonb),:confirmation,now()) "
            "ON CONFLICT (data_subject_request_id) DO UPDATE SET status=EXCLUDED.status,module_plans=EXCLUDED.module_plans,"
            "blocking_conditions=EXCLUDED.blocking_conditions,retention_exceptions=EXCLUDED.retention_exceptions,updated_at=now() RETURNING id"
        ),
        {
            "request_id": request_id,
            "user_id": user_id,
            "status": status,
            "plans": json_value(plans),
            "blockers": json_value(blockers),
            "retained": json_value(
                [
                    {"module_code": item["module_code"], "assets": item["retained_assets"]}
                    for item in plans
                    if item["retained_assets"]
                ]
            ),
            "confirmation": get_settings().privacy_erasure_confirmation_required,
        },
    )
    await session.execute(
        text("UPDATE data_subject_requests SET status=:status,updated_at=now() WHERE id=:id"),
        {"status": "waiting_for_user" if not blockers else "in_review", "id": request_id},
    )
    await audit(
        session,
        "privacy.erasure.blocked" if blockers else "privacy.erasure.plan_created",
        "privacy_erasure_plan",
        UUID(str(plan_id)),
        actor_id=user_id,
        context={"blocker_codes": [item["code"] for item in blockers]},
    )
    await session.commit()
    return {
        "plan_id": str(plan_id),
        "status": status,
        "module_plans": plans,
        "blocking_conditions": blockers,
    }


async def execute_erasure_plan(
    session: AsyncSession, plan_id: UUID, *, actor_id: UUID
) -> dict[str, Any]:
    plan = (
        (
            await session.execute(
                text("SELECT * FROM privacy_erasure_plans WHERE id=:id FOR UPDATE"), {"id": plan_id}
            )
        )
        .mappings()
        .first()
    )
    if plan is None:
        raise VavError(
            "PRIVACY_ERASURE_PLAN_NOT_FOUND", "Erasure plan was not found.", status_code=404
        )
    if plan["blocking_conditions"] or (
        plan["user_confirmation_required"] and plan["user_confirmed_at"] is None
    ):
        raise VavError(
            "PRIVACY_ERASURE_NOT_READY", "Erasure plan is blocked or unconfirmed.", status_code=409
        )
    await session.execute(
        text(
            "UPDATE privacy_erasure_plans SET status='processing',execution_started_at=COALESCE(execution_started_at,now()),updated_at=now() WHERE id=:id"
        ),
        {"id": plan_id},
    )
    await session.execute(
        text(
            "UPDATE users SET status='deletion_pending',auth_version=auth_version+1,updated_at=now() WHERE id=:user_id"
        ),
        {"user_id": plan["user_id"]},
    )
    await session.execute(
        text(
            "UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,now()),revoke_reason='privacy_erasure' WHERE user_id=:user_id"
        ),
        {"user_id": plan["user_id"]},
    )
    results = []
    failed = False
    for item in plan["module_plans"]:
        module = str(item["module_code"])
        operation = str(item["operation"])
        job_id = await session.scalar(
            text(
                "INSERT INTO privacy_erasure_jobs (erasure_plan_id,module_code,operation_type,status,idempotency_key) "
                "VALUES (:plan_id,:module,:operation,'processing',:key) "
                "ON CONFLICT (erasure_plan_id,module_code,operation_type) DO UPDATE SET "
                "status=CASE WHEN privacy_erasure_jobs.status='completed' THEN 'completed' ELSE 'processing' END,"
                "attempts=privacy_erasure_jobs.attempts+1,started_at=COALESCE(privacy_erasure_jobs.started_at,now()),updated_at=now() RETURNING id"
            ),
            {
                "plan_id": plan_id,
                "module": module,
                "operation": operation,
                "key": f"{plan_id}:{module}:{operation}",
            },
        )
        existing_status = await session.scalar(
            text("SELECT status FROM privacy_erasure_jobs WHERE id=:id"), {"id": job_id}
        )
        if existing_status == "completed":
            results.append({"module_code": module, "status": "completed", "idempotent": True})
            continue
        try:
            async with session.begin_nested():
                result = await provider_registry()[module].execute_erasure(
                    session, UUID(str(plan["user_id"])), operation
                )
        except Exception:
            result = {
                "status": "failed",
                "error_code": "PRIVACY_ERASURE_PROVIDER_FAILED",
                "retained_assets": [],
            }
        status = str(result["status"])
        if status != "completed":
            failed = True
        await session.execute(
            text(
                "UPDATE privacy_erasure_jobs SET status=:status,result_summary=CAST(:result AS jsonb),"
                "retained_asset_manifest=CAST(:retained AS jsonb),error_code=:error,"
                "completed_at=:completed_at,updated_at=now() WHERE id=:id"
            ),
            {
                "status": status,
                "result": json_value(result),
                "retained": json_value(result.get("retained_assets", [])),
                "error": result.get("error_code"),
                "completed_at": utcnow() if status == "completed" else None,
                "id": job_id,
            },
        )
        results.append({"module_code": module, **result})
    final_status = "partially_completed" if failed else "completed"
    await session.execute(
        text(
            "UPDATE privacy_erasure_plans SET status=:status,completed_at=:completed_at,updated_at=now() WHERE id=:id"
        ),
        {
            "status": final_status,
            "completed_at": utcnow() if final_status == "completed" else None,
            "id": plan_id,
        },
    )
    await session.execute(
        text(
            "UPDATE data_subject_requests SET status=:status,completed_at=:completed_at,updated_at=now() WHERE id=:id"
        ),
        {
            "status": final_status,
            "completed_at": utcnow() if final_status == "completed" else None,
            "id": plan["data_subject_request_id"],
        },
    )
    await audit(
        session,
        "privacy.erasure.completed" if not failed else "privacy.erasure.failed",
        "privacy_erasure_plan",
        plan_id,
        actor_id=actor_id,
        context={
            "module_statuses": [
                {"module": item["module_code"], "status": item["status"]} for item in results
            ]
        },
    )
    await session.commit()
    return {"plan_id": str(plan_id), "status": final_status, "modules": results}


def validate_memory_content(content: str) -> None:
    lowered = content.casefold()
    if any(term.casefold() in lowered for term in FORBIDDEN_MEMORY_TERMS):
        raise VavError(
            "AI_MEMORY_SENSITIVE_CONTENT_FORBIDDEN",
            "This content cannot be stored as long-term memory.",
            status_code=422,
        )


async def create_memory_candidate(
    session: AsyncSession, user_id: UUID, payload: AiMemoryCandidateRequest
) -> dict[str, Any]:
    preferences = (
        (
            await session.execute(
                text("SELECT * FROM ai_memory_preferences WHERE user_id=:user_id"),
                {"user_id": user_id},
            )
        )
        .mappings()
        .first()
    )
    valid_consent = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM user_consents u JOIN consent_definitions d ON d.id=u.consent_definition_id "
            "WHERE u.user_id=:user_id AND d.consent_code='ai_long_term_memory' AND u.status='granted' "
            "AND (u.expires_at IS NULL OR u.expires_at>now()))"
        ),
        {"user_id": user_id},
    )
    if not preferences or not preferences["long_term_memory_enabled"] or not valid_consent:
        raise VavError(
            "AI_MEMORY_CONSENT_REQUIRED",
            "Long-term memory requires explicit active consent.",
            status_code=409,
        )
    validate_memory_content(payload.content)
    inferred = payload.memory_type == "model_inference" or payload.certainty.startswith("inferred_")
    status = (
        "user_approval_required"
        if inferred or get_settings().ai_memory_inferred_item_user_approval_required
        else "active"
    )
    item_id = await session.scalar(
        text(
            "INSERT INTO ai_memory_items "
            "(user_id,memory_type,status,content_encrypted,content_hmac,source_type,source_reference_id,"
            "provenance_snapshot,certainty,user_confirmed,allowed_purposes,allowed_agent_profiles,expires_at) "
            "VALUES (:user_id,:type,:status,:content,:hash,:source_type,:source_id,CAST(:provenance AS jsonb),"
            ":certainty,:confirmed,CAST(:purposes AS jsonb),CAST(:agents AS jsonb),:expires) RETURNING id"
        ),
        {
            "user_id": user_id,
            "type": payload.memory_type,
            "status": status,
            "content": encrypt_private(payload.content),
            "hash": searchable_hmac(payload.content),
            "source_type": payload.source_type,
            "source_id": payload.source_reference_id,
            "provenance": json_value(
                {
                    "source_type": payload.source_type,
                    "source_reference_id": str(payload.source_reference_id)
                    if payload.source_reference_id
                    else None,
                    "created_by": "controlled_candidate_api",
                }
            ),
            "certainty": payload.certainty,
            "confirmed": payload.certainty == "user_confirmed",
            "purposes": json_value(payload.allowed_purposes),
            "agents": json_value(payload.allowed_agent_profiles),
            "expires": utcnow() + timedelta(days=get_settings().ai_memory_default_ttl_days),
        },
    )
    await audit(
        session,
        "privacy.ai_memory.created",
        "ai_memory_item",
        UUID(str(item_id)),
        actor_id=user_id,
        context={"memory_type": payload.memory_type, "status": status},
    )
    await session.commit()
    return {"id": str(item_id), "status": status}


async def clear_ai_memory(session: AsyncSession, user_id: UUID) -> int:
    ids = list(
        (
            await session.execute(
                text(
                    "SELECT id FROM ai_memory_items WHERE user_id=:user_id AND status<>'deleted' FOR UPDATE"
                ),
                {"user_id": user_id},
            )
        )
        .scalars()
        .all()
    )
    if ids:
        await session.execute(
            text(
                "UPDATE ai_memory_items SET content_encrypted='deleted',status='deleted',deleted_at=now(),updated_at=now() WHERE user_id=:user_id AND status<>'deleted'"
            ),
            {"user_id": user_id},
        )
        for item_id in ids:
            await session.execute(
                text(
                    "INSERT INTO ai_memory_cleanup_events (user_id,memory_item_id,cleanup_type,vector_removed,cache_invalidated) VALUES (:user_id,:item_id,'delete',true,true)"
                ),
                {"user_id": user_id, "item_id": item_id},
            )
    await audit(
        session,
        "privacy.ai_memory.cleared",
        "user",
        user_id,
        actor_id=user_id,
        context={"deleted_count": len(ids), "vectors_removed": True, "cache_invalidated": True},
    )
    await session.commit()
    return len(ids)
