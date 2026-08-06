"""Dating-profile application service.

All profile reads, writes, versioning, completeness and projection rebuilds
flow through this module so that eligibility, privacy and review invariants
are enforced in exactly one place.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import User
from vav.modules.matchmaking_profiles import completeness as completeness_engine
from vav.modules.matchmaking_profiles import content_safety, preferences, projections
from vav.modules.matchmaking_profiles.domain import (
    EDITABLE_STATUSES,
    DatingPhotoRole,
    DatingPhotoStatus,
    DatingProfileStatus,
    DatingProfileViewContext,
    ProfileReviewStatus,
    can_transition,
    can_transition_photo,
)
from vav.modules.matchmaking_profiles.privacy_view import (
    ProfileNotVisibleError,
    build_projection,
)
from vav.modules.matchmaking_profiles.taxonomies import (
    SCHEMA_CODE,
    field_definition,
    taxonomy_value_codes,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private

# --------------------------------------------------------------------------
# Section <-> table mapping
# --------------------------------------------------------------------------

SECTION_TABLES: dict[str, str] = {
    "core": "dating_profile_core_details",
    "faith": "dating_profile_faith_details",
    "relationship_history": "dating_profile_relationship_history",
    "family": "dating_profile_family_details",
    "lifestyle": "dating_profile_lifestyle_details",
}

#: Fields stored directly on the ``dating_profiles`` row.
PROFILE_FIELD_COLUMNS: dict[str, str] = {
    "basic.relationship_intent": "relationship_intent",
}

#: field_code -> (table key, column, json?, encrypted?)
FIELD_STORAGE: dict[str, tuple[str, str, bool, bool]] = {
    "basic.gender_code": ("core", "gender_code", False, False),
    "basic.eligible_partner_gender_codes": ("core", "eligible_partner_gender_codes", True, False),
    "basic.age_display_mode": ("core", "age_display_mode", False, False),
    "basic.height_cm": ("core", "height_cm", False, False),
    "location.country_code": ("core", "country_code", False, False),
    "location.region_code": ("core", "region_code", False, False),
    "location.city_code": ("core", "city_code", False, False),
    "location.citizenship_codes": ("core", "citizenship_codes", True, False),
    "location.residence_status_code": ("core", "residence_status_code", False, False),
    "location.relocation_willingness": ("core", "relocation_willingness", False, False),
    "location.primary_language_codes": ("core", "primary_language_codes", True, False),
    "location.additional_language_codes": ("core", "additional_language_codes", True, False),
    "education_and_work.education_level_code": ("core", "education_level_code", False, False),
    "education_and_work.occupation_category_code": (
        "core",
        "occupation_category_code",
        False,
        False,
    ),
    "faith.faith_status_code": ("faith", "faith_status_code", False, False),
    "faith.faith_started_year": ("faith", "faith_started_year", False, False),
    "faith.church_tradition_codes": ("faith", "church_tradition_codes", True, False),
    "faith.current_church_participation_code": (
        "faith",
        "current_church_participation_code",
        False,
        False,
    ),
    "faith.devotional_life_code": ("faith", "devotional_life_code", False, False),
    "faith.small_group_participation_code": (
        "faith",
        "small_group_participation_code",
        False,
        False,
    ),
    "faith.ministry_participation_codes": ("faith", "ministry_participation_codes", True, False),
    "faith.marriage_faith_importance": ("faith", "marriage_faith_importance", False, False),
    "faith.future_church_expectation_codes": (
        "faith",
        "future_church_expectation_codes",
        True,
        False,
    ),
    "faith.faith_journey_summary": ("faith", "faith_journey_summary_encrypted", False, True),
    "relationship_history.marital_status_code": (
        "relationship_history",
        "marital_status_code",
        False,
        False,
    ),
    "relationship_history.prior_marriage_count": (
        "relationship_history",
        "prior_marriage_count",
        False,
        False,
    ),
    "relationship_history.relationship_history_disclosure_level": (
        "relationship_history",
        "relationship_history_disclosure_level",
        False,
        False,
    ),
    "relationship_history.has_children": ("relationship_history", "has_children", False, False),
    "relationship_history.children_count_range": (
        "relationship_history",
        "children_count_range",
        False,
        False,
    ),
    "relationship_history.children_living_arrangement_code": (
        "relationship_history",
        "children_living_arrangement_code",
        False,
        False,
    ),
    "relationship_history.open_to_partner_with_children": (
        "relationship_history",
        "open_to_partner_with_children",
        False,
        False,
    ),
    "relationship_history.history_summary": (
        "relationship_history",
        "history_summary_encrypted",
        False,
        True,
    ),
    "family.current_living_arrangement_code": (
        "family",
        "current_living_arrangement_code",
        False,
        False,
    ),
    "family.family_closeness_code": ("family", "family_closeness_code", False, False),
    "family.family_culture_codes": ("family", "family_culture_codes", True, False),
    "family.parental_care_expectation_codes": (
        "family",
        "parental_care_expectation_codes",
        True,
        False,
    ),
    "family.desire_children_code": ("family", "desire_children_code", False, False),
    "family.parenting_expectation_codes": ("family", "parenting_expectation_codes", True, False),
    "family.preferred_future_household_codes": (
        "family",
        "preferred_future_household_codes",
        True,
        False,
    ),
    "family.family_summary": ("family", "family_summary_encrypted", False, True),
    "lifestyle.daily_schedule_code": ("lifestyle", "daily_schedule_code", False, False),
    "lifestyle.diet_codes": ("lifestyle", "diet_codes", True, False),
    "lifestyle.exercise_frequency_code": ("lifestyle", "exercise_frequency_code", False, False),
    "lifestyle.smoking_status_code": ("lifestyle", "smoking_status_code", False, False),
    "lifestyle.alcohol_use_code": ("lifestyle", "alcohol_use_code", False, False),
    "lifestyle.social_style_codes": ("lifestyle", "social_style_codes", True, False),
    "lifestyle.leisure_interest_codes": ("lifestyle", "leisure_interest_codes", True, False),
    "lifestyle.pet_preference_codes": ("lifestyle", "pet_preference_codes", True, False),
    "lifestyle.travel_frequency_code": ("lifestyle", "travel_frequency_code", False, False),
    "lifestyle.financial_attitude_codes": ("lifestyle", "financial_attitude_codes", True, False),
    "lifestyle.conflict_style_codes": ("lifestyle", "conflict_style_codes", True, False),
    "lifestyle.communication_preference_codes": (
        "lifestyle",
        "communication_preference_codes",
        True,
        False,
    ),
}

NARRATIVE_FIELD_CODES: dict[str, str] = {
    "self_introduction.self_introduction": "self_introduction",
    "self_introduction.faith_journey": "faith_journey",
    "relationship_values.relationship_values": "relationship_values",
    "future_vision.marriage_vision": "marriage_vision",
    "future_vision.family_vision": "family_vision",
    "self_introduction.strengths_and_growth": "strengths_and_growth",
    "interests.interests_and_lifestyle": "interests_and_lifestyle",
    "communication.hoped_for_relationship": "hoped_for_relationship",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def enabled() -> None:
    if not get_settings().dating_profile_enabled:
        raise VavError("DATING_PROFILE_DISABLED", "Dating profiles are disabled.", status_code=503)


# --------------------------------------------------------------------------
# Audit and events
# --------------------------------------------------------------------------


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
    """Record a matchmaking audit event.

    Only identifiers, field codes, versions and decisions are stored — never
    narrative text, photo bytes or full preference criteria.
    """
    await session.execute(
        text(
            "INSERT INTO matchmaking_audit_events "
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


async def emit_event(
    session: AsyncSession, topic: str, profile_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'dating_profile',:aggregate_id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "aggregate_id": str(profile_id), "payload": json_value(payload)},
    )


async def queue_projection_rebuild(
    session: AsyncSession, profile_id: UUID, trigger_event: str
) -> None:
    """Idempotently queue a projection rebuild; duplicate events collapse."""
    await session.execute(
        text(
            "INSERT INTO dating_profile_projection_jobs (dating_profile_id,trigger_event,dedupe_key) "
            "VALUES (:profile_id,:trigger,:dedupe) ON CONFLICT DO NOTHING"
        ),
        {
            "profile_id": profile_id,
            "trigger": trigger_event,
            "dedupe": f"{profile_id}:{trigger_event}",
        },
    )


# --------------------------------------------------------------------------
# Schema releases and taxonomies
# --------------------------------------------------------------------------


async def active_schema_release(session: AsyncSession) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,schema_code,semantic_version,field_manifest,completeness_policy,submission_policy "
                    "FROM dating_profile_schema_releases WHERE schema_code=:code AND status='active'"
                ),
                {"code": SCHEMA_CODE},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "DATING_SCHEMA_NOT_ACTIVE",
            "No active dating-profile schema release is configured.",
            status_code=503,
        )
    return dict(row)


async def schema_release_by_id(session: AsyncSession, release_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,schema_code,semantic_version,field_manifest,completeness_policy,submission_policy "
                    "FROM dating_profile_schema_releases WHERE id=:id"
                ),
                {"id": release_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("DATING_SCHEMA_NOT_FOUND", "Schema release not found.", status_code=404)
    return dict(row)


async def active_taxonomies(session: AsyncSession, locale: str) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT t.taxonomy_code,t.semantic_version,t.values_manifest,"
                    "COALESCE(jsonb_object_agg(l.value_code,l.label) FILTER (WHERE l.value_code IS NOT NULL),'{}'::jsonb) AS labels "
                    "FROM dating_taxonomies t "
                    "LEFT JOIN dating_taxonomy_localizations l ON l.taxonomy_id=t.id AND l.locale=:locale "
                    "WHERE t.status='active' GROUP BY t.id,t.taxonomy_code,t.semantic_version,t.values_manifest "
                    "ORDER BY t.taxonomy_code"
                ),
                {"locale": locale},
            )
        )
        .mappings()
        .all()
    )
    return {
        row["taxonomy_code"]: {
            "semantic_version": row["semantic_version"],
            "values": [
                {
                    "code": value["code"],
                    "enabled": value.get("enabled", True),
                    "label": row["labels"].get(value["code"], value["code"]),
                }
                for value in row["values_manifest"]
            ],
        }
        for row in rows
    }


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


async def protected_date_of_birth(session: AsyncSession, user_id: UUID) -> date | None:
    """Read the date of birth from the Batch 12 protected profile only.

    The matchmaking domain never stores a second copy of the birth date.
    """
    value = await session.scalar(
        text("SELECT date_of_birth_encrypted FROM user_profiles WHERE user_id=:user_id"),
        {"user_id": user_id},
    )
    if not value:
        return None
    return date.fromisoformat(str(decrypt_private(str(value))))


def age_from(date_of_birth: date | None, *, today: date | None = None) -> int | None:
    if date_of_birth is None:
        return None
    reference = today or utcnow().date()
    return (
        reference.year
        - date_of_birth.year
        - ((reference.month, reference.day) < (date_of_birth.month, date_of_birth.day))
    )


async def require_adult(session: AsyncSession, user_id: UUID) -> int:
    """Backend-authoritative adult check; a client-supplied age is ignored."""
    settings = get_settings()
    age = age_from(await protected_date_of_birth(session, user_id))
    if age is None:
        raise VavError(
            "DATING_DATE_OF_BIRTH_REQUIRED",
            "Add your date of birth to your protected profile before creating a dating profile.",
            status_code=409,
        )
    if age < settings.dating_minimum_age:
        raise VavError(
            "DATING_MINIMUM_AGE_NOT_MET",
            f"Dating profiles are available from age {settings.dating_minimum_age}.",
            status_code=403,
        )
    return age


# --------------------------------------------------------------------------
# Profile lifecycle
# --------------------------------------------------------------------------


def _profile_number() -> str:
    return f"VAV-{secrets.token_hex(6).upper()}"


async def get_profile_row(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text("SELECT * FROM dating_profiles WHERE user_id=:user_id"), {"user_id": user_id}
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def require_profile(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    profile = await get_profile_row(session, user_id)
    if profile is None:
        raise VavError(
            "DATING_PROFILE_NOT_FOUND", "You do not have a dating profile yet.", status_code=404
        )
    return profile


async def create_profile(
    session: AsyncSession, user: User, locale: str | None = None
) -> dict[str, Any]:
    """Create the member's single dating profile."""
    enabled()
    await require_adult(session, user.id)
    existing = await get_profile_row(session, user.id)
    if existing is not None:
        raise VavError(
            "DATING_PROFILE_ALREADY_EXISTS",
            "You already have a dating profile.",
            status_code=409,
        )
    release = await active_schema_release(session)
    settings = get_settings()
    try:
        profile_id = await session.scalar(
            text(
                "INSERT INTO dating_profiles (user_id,profile_number,status,review_status,schema_release_id,default_locale) "
                "VALUES (:user_id,:number,'draft','not_required',:release,:locale) RETURNING id"
            ),
            {
                "user_id": user.id,
                "number": _profile_number(),
                "release": release["id"],
                "locale": locale or user.preferred_locale or settings.dating_profile_default_locale,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "DATING_PROFILE_ALREADY_EXISTS",
            "You already have a dating profile.",
            status_code=409,
        ) from exc
    profile_uuid = UUID(str(profile_id))
    for table in SECTION_TABLES.values():
        await session.execute(
            text(f"INSERT INTO {table} (dating_profile_id) VALUES (:id) ON CONFLICT DO NOTHING"),
            {"id": profile_uuid},
        )
    await session.execute(
        text(
            "INSERT INTO partner_preference_profiles (user_id,dating_profile_id,schema_release_id,allow_recommendation_relaxation) "
            "VALUES (:user_id,:profile_id,:release,:relax) ON CONFLICT DO NOTHING"
        ),
        {
            "user_id": user.id,
            "profile_id": profile_uuid,
            "release": release["id"],
            "relax": settings.dating_allow_automatic_relaxation_default,
        },
    )
    await _apply_strict_privacy_defaults(session, user.id, release)
    await audit(
        session,
        "matchmaking.profile.created",
        "dating_profile",
        profile_uuid,
        actor_id=user.id,
        context={"schema_release": str(release["id"])},
    )
    await emit_event(session, "dating_profile.created", profile_uuid, {"user_id": str(user.id)})
    await session.commit()
    return await require_profile(session, user.id)


async def _apply_strict_privacy_defaults(
    session: AsyncSession, user_id: UUID, release: dict[str, Any]
) -> None:
    """Register every dating field with the privacy control plane as strict."""
    for definition in release["field_manifest"]:
        domain = f"dating_profile.{definition['section_code']}"
        await session.execute(
            text(
                "INSERT INTO user_field_visibility_rules (user_id,data_domain,field_code,visibility,allowed_purposes,allowed_recipient_types) "
                "VALUES (:user_id,:domain,:field,:visibility,'[]'::jsonb,'[]'::jsonb) "
                "ON CONFLICT (user_id,data_domain,field_code) DO NOTHING"
            ),
            {
                "user_id": user_id,
                "domain": domain,
                "field": definition["field_code"],
                # Strict mode: the schema default is the ceiling, never wider.
                "visibility": definition["default_visibility"],
            },
        )


async def _transition(
    session: AsyncSession,
    profile: dict[str, Any],
    target: DatingProfileStatus,
    *,
    actor_id: UUID | None = None,
    reason: str | None = None,
    extra_sql: str = "",
    params: dict[str, Any] | None = None,
) -> None:
    if profile["status"] == target.value:
        return
    if not can_transition(profile["status"], target.value):
        raise VavError(
            "DATING_PROFILE_TRANSITION_INVALID",
            f"A profile cannot move from {profile['status']} to {target.value}.",
            status_code=409,
        )
    await session.execute(
        text(
            f"UPDATE dating_profiles SET status=:status,version=version+1,updated_at=now(){extra_sql} "
            "WHERE id=:id AND version=:version"
        ),
        {
            "status": target.value,
            "id": profile["id"],
            "version": profile["version"],
            **(params or {}),
        },
    )
    profile["status"] = target.value
    profile["version"] += 1
    await audit(
        session,
        f"matchmaking.profile.{target.value}",
        "dating_profile",
        profile["id"],
        actor_id=actor_id,
        reason=reason,
    )


# --------------------------------------------------------------------------
# Field values
# --------------------------------------------------------------------------


async def load_payload(session: AsyncSession, profile_id: UUID) -> dict[str, Any]:
    """Flatten every stored detail row into ``field_code -> value``."""
    payload: dict[str, Any] = {}
    rows: dict[str, dict[str, Any]] = {}
    for key, table in SECTION_TABLES.items():
        row = (
            (
                await session.execute(
                    text(f"SELECT * FROM {table} WHERE dating_profile_id=:id"), {"id": profile_id}
                )
            )
            .mappings()
            .first()
        )
        rows[key] = dict(row) if row else {}
    for field_code, (table_key, column, _is_json, encrypted) in FIELD_STORAGE.items():
        value = rows.get(table_key, {}).get(column)
        if value is None:
            continue
        payload[field_code] = decrypt_private(str(value)) if encrypted else value

    narrative = (
        (
            await session.execute(
                text(
                    "SELECT * FROM dating_profile_narratives WHERE dating_profile_id=:id "
                    "ORDER BY (locale = (SELECT default_locale FROM dating_profiles WHERE id=:id)) DESC LIMIT 1"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if narrative:
        for field_code, column in NARRATIVE_FIELD_CODES.items():
            if narrative[column]:
                payload[field_code] = narrative[column]

    # A pending photo satisfies the submission requirement; the recommendation
    # projection separately insists on an approved one.
    primary_photo = (
        await session.execute(
            text(
                "SELECT id FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND photo_role='primary' AND status IN ('approved','review_required') "
                "AND deleted_at IS NULL"
            ),
            {"id": profile_id},
        )
    ).scalar()
    if primary_photo:
        payload["photos.primary_photo"] = str(primary_photo)

    confirmations = (
        await session.execute(
            text("SELECT status FROM partner_preference_profiles WHERE dating_profile_id=:id"),
            {"id": profile_id},
        )
    ).scalar()
    if confirmations in {"confirmed", "active"}:
        payload["privacy.partner_preferences_confirmed"] = True
    privacy_confirmed = await session.scalar(
        text(
            "SELECT visible_in_matchmaking FROM user_privacy_settings s "
            "JOIN dating_profiles p ON p.user_id=s.user_id WHERE p.id=:id"
        ),
        {"id": profile_id},
    )
    if privacy_confirmed is not None:
        payload["privacy.privacy_settings_confirmed"] = bool(privacy_confirmed)

    profile_row = (
        (
            await session.execute(
                text("SELECT relationship_intent FROM dating_profiles WHERE id=:id"),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if profile_row:
        for field_code, column in PROFILE_FIELD_COLUMNS.items():
            if profile_row[column] is not None:
                payload[field_code] = profile_row[column]
    return payload


def _validate_field(field_code: str, value: Any) -> Any:
    definition = field_definition(field_code)
    if definition is None:
        raise VavError(
            "DATING_FIELD_UNKNOWN",
            f"'{field_code}' is not part of the active profile schema.",
            status_code=422,
        )
    if value is None:
        return None
    schema = definition["value_schema"]
    taxonomy = schema.get("taxonomy")
    field_type = definition["field_type"]

    if field_type in {"enum", "string"}:
        if not isinstance(value, str):
            raise _field_error(field_code, "expects a single text value")
        if taxonomy and value not in taxonomy_value_codes(taxonomy):
            raise _field_error(field_code, "uses a value that is not active in its taxonomy")
        if "values" in schema and value not in schema["values"]:
            raise _field_error(field_code, "uses a value outside the allowed set")
        return value
    if field_type in {"enum_set", "string_set"}:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise _field_error(field_code, "expects a list of text values")
        if taxonomy:
            allowed = taxonomy_value_codes(taxonomy)
            unknown = [item for item in value if item not in allowed]
            if unknown:
                raise _field_error(
                    field_code, f"uses inactive taxonomy values: {', '.join(sorted(unknown))}"
                )
        return sorted(set(value))
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise _field_error(field_code, "expects true or false")
        return value
    if field_type in {"integer", "scale"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _field_error(field_code, "expects a whole number")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise _field_error(field_code, f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise _field_error(field_code, f"must be at most {maximum}")
        return value
    if field_type == "encrypted_text":
        if not isinstance(value, str):
            raise _field_error(field_code, "expects text")
        findings = content_safety.scan_text(value)
        if content_safety.blocking_findings(findings):
            raise VavError(
                "DATING_FIELD_CONTACT_INFORMATION",
                "Contact details cannot be placed in profile text.",
                status_code=422,
                details=[{"field_code": field_code}],
            )
        return value
    raise _field_error(field_code, "cannot be written directly")


def _field_error(field_code: str, message: str) -> VavError:
    return VavError(
        "DATING_FIELD_INVALID",
        f"'{field_code}' {message}.",
        status_code=422,
        details=[{"field_code": field_code}],
    )


async def update_fields(
    session: AsyncSession,
    user: User,
    values: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Apply a partial field update with optimistic concurrency."""
    enabled()
    profile = await require_profile(session, user.id)
    if profile["status"] not in {status.value for status in EDITABLE_STATUSES}:
        raise VavError(
            "DATING_PROFILE_NOT_EDITABLE",
            f"A profile in state {profile['status']} cannot be edited.",
            status_code=409,
        )
    if expected_version is not None and expected_version != profile["version"]:
        raise VavError(
            "DATING_PROFILE_VERSION_CONFLICT",
            "This profile changed since you loaded it. Reload and try again.",
            status_code=409,
        )

    updates: dict[str, dict[str, Any]] = {key: {} for key in SECTION_TABLES}
    profile_updates: dict[str, Any] = {}
    for field_code, raw in values.items():
        if field_code in PROFILE_FIELD_COLUMNS:
            profile_updates[PROFILE_FIELD_COLUMNS[field_code]] = _validate_field(field_code, raw)
            continue
        storage = FIELD_STORAGE.get(field_code)
        if storage is None:
            raise VavError(
                "DATING_FIELD_NOT_WRITABLE",
                f"'{field_code}' cannot be written through this endpoint.",
                status_code=422,
            )
        validated = _validate_field(field_code, raw)
        table_key, column, is_json, encrypted = storage
        if encrypted:
            stored: Any = encrypt_private(validated) if validated is not None else None
        elif is_json:
            stored = json_value(validated if validated is not None else [])
        else:
            stored = validated
        updates[table_key][column] = (stored, is_json)

    for table_key, columns in updates.items():
        if not columns:
            continue
        assignments = ", ".join(
            f"{column}=CAST(:{column} AS jsonb)" if is_json else f"{column}=:{column}"
            for column, (_value, is_json) in columns.items()
        )
        await session.execute(
            text(
                f"UPDATE {SECTION_TABLES[table_key]} SET {assignments}, updated_at=now() "
                "WHERE dating_profile_id=:profile_id"
            ),
            {column: value for column, (value, _json) in columns.items()}
            | {"profile_id": profile["id"]},
        )

    profile_assignments = "".join(f",{column}=:{column}" for column in profile_updates)
    await session.execute(
        text(
            "UPDATE dating_profiles SET version=version+1,updated_at=now(),"
            f"current_city_code=COALESCE(:city,current_city_code){profile_assignments} "
            "WHERE id=:id AND version=:version"
        ),
        {
            "id": profile["id"],
            "version": profile["version"],
            "city": values.get("location.city_code"),
            **profile_updates,
        },
    )
    await audit(
        session,
        "matchmaking.profile.updated",
        "dating_profile",
        profile["id"],
        actor_id=user.id,
        context={"field_codes": sorted(values)},
    )
    await emit_event(
        session,
        "dating_profile.updated",
        profile["id"],
        {"field_codes": sorted(values)},
    )
    result = await refresh_completeness(session, profile["id"])
    await session.commit()
    return result


async def update_narratives(
    session: AsyncSession,
    user: User,
    locale: str,
    values: dict[str, Any],
    *,
    ai_assisted: bool = False,
) -> dict[str, Any]:
    """Write localized narratives after length and content screening."""
    enabled()
    settings = get_settings()
    profile = await require_profile(session, user.id)
    if profile["status"] not in {status.value for status in EDITABLE_STATUSES}:
        raise VavError(
            "DATING_PROFILE_NOT_EDITABLE",
            f"A profile in state {profile['status']} cannot be edited.",
            status_code=409,
        )

    cleaned: dict[str, str | None] = {}
    for column in content_safety.NARRATIVE_FIELDS:
        if column not in values:
            continue
        value = values[column]
        if value is None:
            cleaned[column] = None
            continue
        if not isinstance(value, str):
            raise _field_error(column, "expects text")
        stripped = value.strip()
        limit = (
            settings.dating_self_intro_max_chars
            if column == "self_introduction"
            else settings.dating_narrative_max_chars
        )
        if len(stripped) > limit:
            raise _field_error(column, f"must be at most {limit} characters")
        if (
            column == "self_introduction"
            and stripped
            and len(stripped) < settings.dating_self_intro_min_chars
        ):
            raise _field_error(
                column, f"must be at least {settings.dating_self_intro_min_chars} characters"
            )
        cleaned[column] = stripped or None

    findings = content_safety.scan_narratives(
        {column: value for column, value in cleaned.items() if value}
    )
    blocking = content_safety.blocking_findings(findings)
    if blocking:
        raise VavError(
            "DATING_NARRATIVE_CONTACT_INFORMATION",
            "Contact details and external links cannot appear in profile text.",
            status_code=422,
            details=[
                {"field_code": finding.get("field_code"), "code": finding["code"]}
                for finding in blocking
            ],
        )

    columns = ",".join(cleaned)
    placeholders = ",".join(f":{column}" for column in cleaned)
    conflict = ",".join(f"{column}=EXCLUDED.{column}" for column in cleaned)
    await session.execute(
        text(
            f"INSERT INTO dating_profile_narratives (dating_profile_id,locale,{columns},moderation_status,moderation_findings,ai_assisted,ai_assistance_confirmed_at) "
            f"VALUES (:profile_id,:locale,{placeholders},:status,CAST(:findings AS jsonb),:ai,:ai_at) "
            f"ON CONFLICT (dating_profile_id,locale) DO UPDATE SET {conflict},"
            "moderation_status=EXCLUDED.moderation_status,moderation_findings=EXCLUDED.moderation_findings,"
            "ai_assisted=EXCLUDED.ai_assisted,ai_assistance_confirmed_at=EXCLUDED.ai_assistance_confirmed_at,updated_at=now()"
        )
        if cleaned
        else text("SELECT 1"),
        {
            "profile_id": profile["id"],
            "locale": locale,
            "status": content_safety.moderation_status_for(findings),
            "findings": json_value(findings),
            # AI may polish wording, but the member confirms the result before
            # it is stored as their own statement.
            "ai": ai_assisted,
            "ai_at": utcnow() if ai_assisted else None,
            **cleaned,
        },
    )
    await audit(
        session,
        "matchmaking.profile.updated",
        "dating_profile",
        profile["id"],
        actor_id=user.id,
        context={"section": "narratives", "locale": locale, "finding_count": len(findings)},
    )
    result = await refresh_completeness(session, profile["id"])
    await session.commit()
    return result


# --------------------------------------------------------------------------
# Completeness
# --------------------------------------------------------------------------


async def refresh_completeness(session: AsyncSession, profile_id: UUID) -> dict[str, Any]:
    profile = (
        (
            await session.execute(
                text("SELECT * FROM dating_profiles WHERE id=:id"), {"id": profile_id}
            )
        )
        .mappings()
        .first()
    )
    if profile is None:
        raise VavError("DATING_PROFILE_NOT_FOUND", "Profile not found.", status_code=404)
    release = await schema_release_by_id(session, profile["schema_release_id"])
    payload = await load_payload(session, profile_id)
    result = completeness_engine.evaluate(
        payload, release["field_manifest"], release["completeness_policy"]
    )
    await session.execute(
        text(
            "INSERT INTO dating_profile_completeness_snapshots "
            "(dating_profile_id,profile_version_number,policy_version,total_basis_points,section_scores,"
            "missing_required_fields,missing_recommended_fields,submission_eligible,recommendation_eligible) "
            "VALUES (:profile_id,:version,:policy,:total,CAST(:sections AS jsonb),CAST(:required AS jsonb),"
            "CAST(:recommended AS jsonb),:submission,:recommendation) "
            "ON CONFLICT (dating_profile_id,profile_version_number) DO UPDATE SET "
            "policy_version=EXCLUDED.policy_version,total_basis_points=EXCLUDED.total_basis_points,"
            "section_scores=EXCLUDED.section_scores,missing_required_fields=EXCLUDED.missing_required_fields,"
            "missing_recommended_fields=EXCLUDED.missing_recommended_fields,"
            "submission_eligible=EXCLUDED.submission_eligible,recommendation_eligible=EXCLUDED.recommendation_eligible,"
            "evaluated_at=now()"
        ),
        {
            "profile_id": profile_id,
            "version": profile["current_version_number"],
            "policy": result["policy_version"],
            "total": result["total_basis_points"],
            "sections": json_value(result["section_scores"]),
            "required": json_value(result["missing_required_fields"]),
            "recommended": json_value(result["missing_recommended_fields"]),
            "submission": result["submission_eligible"],
            "recommendation": result["recommendation_eligible"],
        },
    )
    next_status = profile["status"]
    if profile["status"] in {
        DatingProfileStatus.DRAFT.value,
        DatingProfileStatus.INCOMPLETE.value,
        DatingProfileStatus.READY_TO_SUBMIT.value,
        DatingProfileStatus.CHANGES_REQUESTED.value,
    }:
        next_status = (
            DatingProfileStatus.READY_TO_SUBMIT.value
            if result["submission_eligible"]
            else DatingProfileStatus.INCOMPLETE.value
        )
        if (
            profile["status"] == DatingProfileStatus.CHANGES_REQUESTED.value
            and not result["submission_eligible"]
        ):
            next_status = DatingProfileStatus.INCOMPLETE.value
    await session.execute(
        text(
            "UPDATE dating_profiles SET completeness_basis_points=:total,status=:status,updated_at=now() WHERE id=:id"
        ),
        {"total": result["total_basis_points"], "status": next_status, "id": profile_id},
    )
    await emit_event(
        session,
        "dating_profile.completeness_updated",
        profile_id,
        {
            "total_basis_points": result["total_basis_points"],
            "submission_eligible": result["submission_eligible"],
        },
    )
    return {**result, "status": next_status, "profile_id": str(profile_id)}


async def completeness_view(session: AsyncSession, profile_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM dating_profile_completeness_snapshots WHERE dating_profile_id=:id "
                    "ORDER BY profile_version_number DESC LIMIT 1"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return await refresh_completeness(session, profile_id)
    return {
        "policy_version": row["policy_version"],
        "total_basis_points": row["total_basis_points"],
        "section_scores": row["section_scores"],
        "missing_required_fields": row["missing_required_fields"],
        "missing_recommended_fields": row["missing_recommended_fields"],
        "submission_eligible": row["submission_eligible"],
        "recommendation_eligible": row["recommendation_eligible"],
        "measures": "form_completion_only",
        "profile_id": str(profile_id),
    }


# --------------------------------------------------------------------------
# Versions and submission
# --------------------------------------------------------------------------


async def _snapshot(session: AsyncSession, profile_id: UUID) -> tuple[dict[str, Any], str]:
    payload = await load_payload(session, profile_id)
    criteria = await preference_criteria(session, profile_id)
    snapshot = {"fields": payload, "preference_criteria": criteria}
    material = json_value(snapshot)
    return snapshot, hashlib.sha256(material.encode()).hexdigest()


async def submit_profile(session: AsyncSession, user: User, change_summary: str) -> dict[str, Any]:
    """Freeze the current draft into an immutable version and open a review."""
    enabled()
    profile = await require_profile(session, user.id)
    await require_adult(session, user.id)
    scores = await refresh_completeness(session, profile["id"])
    if not scores["submission_eligible"]:
        raise VavError(
            "DATING_PROFILE_NOT_SUBMITTABLE",
            "Complete every required field before submitting your profile.",
            status_code=409,
            details=[{"missing_required_fields": scores["missing_required_fields"]}],
        )
    settings = get_settings()
    if settings.dating_profile_require_primary_photo:
        approved_photos = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND status IN ('approved','review_required') AND deleted_at IS NULL"
            ),
            {"id": profile["id"]},
        )
        if int(approved_photos or 0) < settings.dating_photo_min_count_for_submission:
            raise VavError(
                "DATING_PROFILE_PHOTO_REQUIRED",
                "Upload at least one profile photo before submitting.",
                status_code=409,
            )

    profile = await require_profile(session, user.id)
    snapshot, checksum = await _snapshot(session, profile["id"])
    version_number = int(profile["current_version_number"])
    existing = await session.scalar(
        text(
            "SELECT submitted_at FROM dating_profile_versions "
            "WHERE dating_profile_id=:id AND version_number=:version"
        ),
        {"id": profile["id"], "version": version_number},
    )
    if existing is not None:
        raise VavError(
            "DATING_PROFILE_ALREADY_SUBMITTED",
            "This profile version is already under review.",
            status_code=409,
        )
    version_id = await session.scalar(
        text(
            "INSERT INTO dating_profile_versions "
            "(dating_profile_id,version_number,schema_release_id,snapshot_encrypted,snapshot_checksum_sha256,"
            "change_summary,created_by,review_status,submitted_at) "
            "VALUES (:profile_id,:version,:release,:snapshot,:checksum,:summary,:user_id,'pending',now()) RETURNING id"
        ),
        {
            "profile_id": profile["id"],
            "version": version_number,
            "release": profile["schema_release_id"],
            "snapshot": encrypt_private(snapshot),
            "checksum": checksum,
            "summary": change_summary.strip() or "Profile submitted for review.",
            "user_id": user.id,
        },
    )
    await session.execute(
        text(
            "INSERT INTO dating_profile_review_cases "
            "(dating_profile_id,profile_version_id,review_type,status,priority) "
            "VALUES (:profile_id,:version_id,'full_profile','pending','normal')"
        ),
        {"profile_id": profile["id"], "version_id": version_id},
    )
    await _transition(
        session,
        profile,
        DatingProfileStatus.SUBMITTED,
        actor_id=user.id,
        extra_sql=",submitted_at=now(),review_status='pending'",
    )
    await audit(
        session,
        "matchmaking.profile.submitted",
        "dating_profile",
        profile["id"],
        actor_id=user.id,
        context={"version_number": version_number, "checksum": checksum},
    )
    await emit_event(
        session,
        "dating_profile.submitted",
        profile["id"],
        {"version_number": version_number},
    )
    await session.commit()
    return {
        "profile_id": str(profile["id"]),
        "version_number": version_number,
        "review_status": ProfileReviewStatus.PENDING.value,
        "status": DatingProfileStatus.SUBMITTED.value,
    }


async def start_draft_revision(session: AsyncSession, profile: dict[str, Any]) -> int:
    """Open the next draft version while an earlier one is under review."""
    next_version = int(profile["current_version_number"]) + 1
    await session.execute(
        text(
            "UPDATE dating_profiles SET current_version_number=:next,updated_at=now() WHERE id=:id"
        ),
        {"next": next_version, "id": profile["id"]},
    )
    await emit_event(
        session, "dating_profile.version_created", profile["id"], {"version_number": next_version}
    )
    return next_version


async def version_diff(
    session: AsyncSession, profile_id: UUID, left: int, right: int
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT version_number,snapshot_encrypted,review_status,created_at FROM dating_profile_versions "
                    "WHERE dating_profile_id=:id AND version_number IN (:left,:right)"
                ),
                {"id": profile_id, "left": left, "right": right},
            )
        )
        .mappings()
        .all()
    )
    snapshots = {
        row["version_number"]: decrypt_private(str(row["snapshot_encrypted"])) for row in rows
    }
    if left not in snapshots or right not in snapshots:
        raise VavError(
            "DATING_PROFILE_VERSION_NOT_FOUND",
            "One of the requested profile versions does not exist.",
            status_code=404,
        )
    before = snapshots[left]["fields"]
    after = snapshots[right]["fields"]
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(code for code in set(before) & set(after) if before[code] != after[code])
    preference_changed = (
        snapshots[left]["preference_criteria"] != snapshots[right]["preference_criteria"]
    )
    return {
        "left_version": left,
        "right_version": right,
        "added_fields": added,
        "removed_fields": removed,
        "changed_fields": changed,
        "photo_changed": "photos.primary_photo" in set(added) | set(removed) | set(changed),
        "privacy_changed": any(code.startswith("privacy.") for code in added + removed + changed),
        "preference_criteria_changed": preference_changed,
        "requires_full_review": len(changed) + len(added) + len(removed) > 10,
    }


# --------------------------------------------------------------------------
# Preferences
# --------------------------------------------------------------------------


async def preference_profile(session: AsyncSession, profile_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM partner_preference_profiles WHERE dating_profile_id=:id"),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "DATING_PREFERENCE_PROFILE_NOT_FOUND",
            "Partner preferences have not been initialised.",
            status_code=404,
        )
    return dict(row)


async def preference_criteria(session: AsyncSession, profile_id: UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT c.criterion_code,c.operator,c.desired_value,c.importance,c.hard_constraint,"
                    "c.allow_unknown,c.allow_system_relaxation,c.user_explanation "
                    "FROM partner_preference_criteria c "
                    "JOIN partner_preference_profiles p ON p.id=c.partner_preference_profile_id "
                    "WHERE p.dating_profile_id=:id ORDER BY c.criterion_code"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def replace_preferences(
    session: AsyncSession,
    user: User,
    criteria: list[dict[str, Any]],
    *,
    allow_relaxation: bool,
) -> dict[str, Any]:
    enabled()
    profile = await require_profile(session, user.id)
    preference = await preference_profile(session, profile["id"])
    normalised = preferences.validate_criteria(criteria)
    if not allow_relaxation:
        for criterion in normalised:
            criterion["allow_system_relaxation"] = False

    await session.execute(
        text("DELETE FROM partner_preference_criteria WHERE partner_preference_profile_id=:id"),
        {"id": preference["id"]},
    )
    for criterion in normalised:
        await session.execute(
            text(
                "INSERT INTO partner_preference_criteria "
                "(partner_preference_profile_id,criterion_code,operator,desired_value,importance,"
                "hard_constraint,allow_unknown,allow_system_relaxation,user_explanation) "
                "VALUES (:profile_id,:code,:operator,CAST(:value AS jsonb),:importance,:hard,:unknown,:relax,:explanation)"
            ),
            {
                "profile_id": preference["id"],
                "code": criterion["criterion_code"],
                "operator": criterion["operator"],
                "value": json_value(criterion["desired_value"]),
                "importance": criterion["importance"],
                "hard": criterion["hard_constraint"],
                "unknown": criterion["allow_unknown"],
                "relax": criterion["allow_system_relaxation"],
                "explanation": criterion["user_explanation"],
            },
        )
    await session.execute(
        text(
            "UPDATE partner_preference_profiles SET preference_version=preference_version+1,"
            "status='confirmed',allow_recommendation_relaxation=:relax,updated_at=now() WHERE id=:id"
        ),
        {"id": preference["id"], "relax": allow_relaxation},
    )
    await audit(
        session,
        "matchmaking.preference.updated",
        "partner_preference_profile",
        preference["id"],
        actor_id=user.id,
        context={"criterion_codes": sorted(c["criterion_code"] for c in normalised)},
    )
    await emit_event(
        session,
        "dating_profile.preference.updated",
        profile["id"],
        {"criteria_count": len(normalised)},
    )
    await queue_projection_rebuild(session, profile["id"], "dating_profile.preference_updated")
    await refresh_completeness(session, profile["id"])
    await session.commit()
    return {
        "criteria": normalised,
        "hard_constraints": preferences.hard_constraint_summary(normalised),
        "allow_recommendation_relaxation": allow_relaxation,
        "preference_version": int(preference["preference_version"]) + 1,
        "visibility": "private_to_owner_and_recommendation_engine",
    }


# --------------------------------------------------------------------------
# Photos
# --------------------------------------------------------------------------


async def _lock_profile(session: AsyncSession, profile_id: UUID) -> None:
    """Serialise operations that must keep a single-primary-photo invariant."""
    await session.execute(
        text("SELECT id FROM dating_profiles WHERE id=:id FOR UPDATE"), {"id": profile_id}
    )


async def photo_rows(
    session: AsyncSession, profile_id: UUID, *, include_deleted: bool = False
) -> list[dict[str, Any]]:
    clause = "" if include_deleted else " AND deleted_at IS NULL"
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,photo_role,status,visibility,sort_order,content_checksum_sha256,"
                    "processing_report,rejection_reason_code,rejection_message_safe,created_at,updated_at "
                    f"FROM dating_profile_photos WHERE dating_profile_id=:id{clause} ORDER BY sort_order,created_at"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def register_photo(
    session: AsyncSession,
    user: User,
    *,
    media_asset_id: UUID,
    role: str,
    checksum: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Attach a processed image to the profile and queue it for review."""
    enabled()
    settings = get_settings()
    profile = await require_profile(session, user.id)
    try:
        photo_role = DatingPhotoRole(role)
    except ValueError as exc:
        raise VavError("DATING_PHOTO_ROLE_INVALID", "Unknown photo role.", status_code=422) from exc

    await _lock_profile(session, profile["id"])
    live = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
            "AND deleted_at IS NULL AND status <> 'deleted'"
        ),
        {"id": profile["id"]},
    )
    if int(live or 0) >= settings.dating_photo_max_count:
        raise VavError(
            "DATING_PHOTO_LIMIT_REACHED",
            f"A profile may hold at most {settings.dating_photo_max_count} photos.",
            status_code=409,
        )
    duplicate = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
            "AND content_checksum_sha256=:checksum AND deleted_at IS NULL"
        ),
        {"id": profile["id"], "checksum": checksum},
    )
    if int(duplicate or 0):
        raise VavError(
            "DATING_PHOTO_DUPLICATE", "This photo was already uploaded.", status_code=409
        )

    if photo_role is DatingPhotoRole.PRIMARY:
        # The partial unique index guarantees a single primary photo; demote
        # any existing one inside the same transaction so concurrent uploads
        # cannot both win.
        await session.execute(
            text(
                "UPDATE dating_profile_photos SET photo_role='gallery',updated_at=now() "
                "WHERE dating_profile_id=:id AND photo_role='primary' AND deleted_at IS NULL"
            ),
            {"id": profile["id"]},
        )

    try:
        photo_id = await session.scalar(
            text(
                "INSERT INTO dating_profile_photos "
                "(dating_profile_id,media_asset_id,photo_role,status,visibility,sort_order,"
                "content_checksum_sha256,processing_report) "
                "VALUES (:profile_id,:media_id,:role,'review_required','verified_members',:sort,"
                ":checksum,CAST(:report AS jsonb)) RETURNING id"
            ),
            {
                "profile_id": profile["id"],
                "media_id": media_asset_id,
                "role": photo_role.value,
                "sort": int(live or 0),
                "checksum": checksum,
                "report": json_value(report),
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "DATING_PRIMARY_PHOTO_CONFLICT",
            "Another primary photo was set at the same time. Reload and try again.",
            status_code=409,
        ) from exc

    photo_uuid = UUID(str(photo_id))
    await audit(
        session,
        "matchmaking.photo.uploaded",
        "dating_profile_photo",
        photo_uuid,
        actor_id=user.id,
        context={"role": photo_role.value, "exif_removed": report.get("exif_removed", True)},
    )
    await emit_event(
        session,
        "dating_profile.photo.uploaded",
        profile["id"],
        {"photo_id": str(photo_uuid), "role": photo_role.value},
    )
    await refresh_completeness(session, profile["id"])
    await session.commit()
    return {
        "photo_id": str(photo_uuid),
        "status": DatingPhotoStatus.REVIEW_REQUIRED.value,
        "photo_role": photo_role.value,
        "quality_flags": report.get("quality_flags", []),
        "exif_removed": report.get("exif_removed", True),
    }


async def set_primary_photo(session: AsyncSession, user: User, photo_id: UUID) -> dict[str, Any]:
    profile = await require_profile(session, user.id)
    await _lock_profile(session, profile["id"])
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,status FROM dating_profile_photos WHERE id=:id AND dating_profile_id=:profile_id "
                    "AND deleted_at IS NULL FOR UPDATE"
                ),
                {"id": photo_id, "profile_id": profile["id"]},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("DATING_PHOTO_NOT_FOUND", "Photo not found.", status_code=404)
    if row["status"] not in {
        DatingPhotoStatus.APPROVED.value,
        DatingPhotoStatus.REVIEW_REQUIRED.value,
    }:
        raise VavError(
            "DATING_PHOTO_NOT_ELIGIBLE",
            "Only an approved or pending photo can become the primary photo.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE dating_profile_photos SET photo_role='gallery',updated_at=now() "
            "WHERE dating_profile_id=:profile_id AND photo_role='primary' AND deleted_at IS NULL AND id<>:id"
        ),
        {"profile_id": profile["id"], "id": photo_id},
    )
    await session.execute(
        text("UPDATE dating_profile_photos SET photo_role='primary',updated_at=now() WHERE id=:id"),
        {"id": photo_id},
    )
    await audit(
        session,
        "matchmaking.photo.approved",
        "dating_profile_photo",
        photo_id,
        actor_id=user.id,
        context={"action": "primary_photo_changed"},
    )
    await emit_event(
        session,
        "dating_profile.primary_photo_changed",
        profile["id"],
        {"photo_id": str(photo_id)},
    )
    await queue_projection_rebuild(session, profile["id"], "dating_profile.photo_approved")
    await session.commit()
    return {"photo_id": str(photo_id), "photo_role": DatingPhotoRole.PRIMARY.value}


async def delete_photo(session: AsyncSession, user: User, photo_id: UUID) -> dict[str, Any]:
    profile = await require_profile(session, user.id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,status FROM dating_profile_photos WHERE id=:id AND dating_profile_id=:profile_id "
                    "AND deleted_at IS NULL"
                ),
                {"id": photo_id, "profile_id": profile["id"]},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("DATING_PHOTO_NOT_FOUND", "Photo not found.", status_code=404)
    if not can_transition_photo(row["status"], DatingPhotoStatus.DELETED.value):
        raise VavError(
            "DATING_PHOTO_TRANSITION_INVALID", "This photo cannot be deleted.", status_code=409
        )
    await session.execute(
        text(
            "UPDATE dating_profile_photos SET status='deleted',deleted_at=now(),updated_at=now() WHERE id=:id"
        ),
        {"id": photo_id},
    )
    # Outstanding view tokens must stop working the moment a photo is removed.
    await session.execute(
        text(
            "UPDATE dating_profile_photo_view_tokens SET revoked_at=now() "
            "WHERE photo_id=:id AND revoked_at IS NULL"
        ),
        {"id": photo_id},
    )
    await audit(
        session,
        "matchmaking.photo.deleted",
        "dating_profile_photo",
        photo_id,
        actor_id=user.id,
    )
    await emit_event(
        session, "dating_profile.photo.deleted", profile["id"], {"photo_id": str(photo_id)}
    )
    await queue_projection_rebuild(session, profile["id"], "dating_profile.photo_approved")
    await refresh_completeness(session, profile["id"])
    await session.commit()
    return {"photo_id": str(photo_id), "status": DatingPhotoStatus.DELETED.value}


async def issue_photo_view_token(
    session: AsyncSession,
    viewer: User,
    photo_id: UUID,
    *,
    context: DatingProfileViewContext,
) -> dict[str, Any]:
    """Mint a short-lived token after re-checking every access condition."""
    settings = get_settings()
    row = (
        (
            await session.execute(
                text(
                    "SELECT p.id,p.status,p.dating_profile_id,d.status AS profile_status,d.user_id AS owner_id "
                    "FROM dating_profile_photos p JOIN dating_profiles d ON d.id=p.dating_profile_id "
                    "WHERE p.id=:id AND p.deleted_at IS NULL"
                ),
                {"id": photo_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("DATING_PHOTO_NOT_FOUND", "Photo not found.", status_code=404)

    is_owner = row["owner_id"] == viewer.id
    if not is_owner:
        if row["status"] != DatingPhotoStatus.APPROVED.value:
            raise VavError(
                "DATING_PHOTO_NOT_AVAILABLE", "This photo is not available.", status_code=404
            )
        if row["profile_status"] != DatingProfileStatus.ACTIVE.value:
            raise VavError(
                "DATING_PHOTO_NOT_AVAILABLE", "This photo is not available.", status_code=404
            )
        if await is_blocked(session, viewer.id, row["owner_id"]):
            raise VavError(
                "DATING_PHOTO_NOT_AVAILABLE", "This photo is not available.", status_code=404
            )

    token = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO dating_profile_photo_view_tokens (photo_id,viewer_user_id,token_hash,view_context,expires_at) "
            "VALUES (:photo_id,:viewer,:hash,:context,now() + make_interval(secs => :ttl))"
        ),
        {
            "photo_id": photo_id,
            "viewer": viewer.id,
            "hash": hashlib.sha256(token.encode()).hexdigest(),
            "context": context.value,
            "ttl": settings.dating_photo_view_token_ttl_seconds,
        },
    )
    await session.commit()
    # The storage object key never leaves the backend.
    return {
        "photo_id": str(photo_id),
        "view_url": f"/api/v1/dating-profiles/photos/{photo_id}/content?token={token}",
        "expires_in_seconds": settings.dating_photo_view_token_ttl_seconds,
    }


async def is_blocked(session: AsyncSession, viewer_id: UUID, owner_id: UUID) -> bool:
    """Consume the Batch 18 safe-output gateway, not raw reports or evidence."""
    from vav.modules.trust_safety.service import evaluate_gate

    decision = await evaluate_gate(
        session,
        decision_context="profile-view",
        subject_user_id=viewer_id,
        counterpart_user_id=owner_id,
    )
    return not decision.allowed


# --------------------------------------------------------------------------
# Viewer projections
# --------------------------------------------------------------------------


async def field_visibility_overrides(session: AsyncSession, user_id: UUID) -> dict[str, str]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT field_code,visibility FROM user_field_visibility_rules "
                    "WHERE user_id=:user_id AND data_domain LIKE 'dating_profile.%' "
                    "AND (valid_until IS NULL OR valid_until > now())"
                ),
                {"user_id": user_id},
            )
        )
        .mappings()
        .all()
    )
    return {row["field_code"]: row["visibility"] for row in rows}


async def ai_consent_granted(session: AsyncSession, user_id: UUID) -> bool:
    value = await session.scalar(
        text("SELECT allow_profile_use_by_ai FROM user_privacy_settings WHERE user_id=:user_id"),
        {"user_id": user_id},
    )
    return bool(value)


async def viewer_projection(
    session: AsyncSession,
    *,
    profile_id: UUID,
    viewer: User | None,
    context: DatingProfileViewContext,
) -> dict[str, Any]:
    """Build the DTO this viewer is allowed to receive."""
    profile = (
        (
            await session.execute(
                text("SELECT * FROM dating_profiles WHERE id=:id"), {"id": profile_id}
            )
        )
        .mappings()
        .first()
    )
    if profile is None:
        raise VavError("DATING_PROFILE_NOT_FOUND", "Profile not found.", status_code=404)

    owner_id = profile["user_id"]
    is_self = viewer is not None and viewer.id == owner_id
    is_admin_context = context is DatingProfileViewContext.ADMIN_REVIEW

    if not is_self and not is_admin_context:
        if profile["status"] != DatingProfileStatus.ACTIVE.value:
            raise VavError(
                "DATING_PROFILE_NOT_AVAILABLE", "This profile is not available.", status_code=404
            )
        if profile["approved_version_number"] is None:
            raise VavError(
                "DATING_PROFILE_NOT_AVAILABLE", "This profile is not available.", status_code=404
            )

    release = await schema_release_by_id(session, profile["schema_release_id"])

    if is_self or is_admin_context:
        payload = await load_payload(session, profile_id)
    else:
        # Other members only ever see the approved version, never the draft.
        approved = (
            await session.execute(
                text(
                    "SELECT snapshot_encrypted FROM dating_profile_versions "
                    "WHERE dating_profile_id=:id AND version_number=:version AND approved_at IS NOT NULL"
                ),
                {"id": profile_id, "version": profile["approved_version_number"]},
            )
        ).scalar()
        if approved is None:
            raise VavError(
                "DATING_PROFILE_NOT_AVAILABLE", "This profile is not available.", status_code=404
            )
        payload = dict(decrypt_private(str(approved))["fields"])

    display_name = await session.scalar(
        text("SELECT display_name FROM user_profiles WHERE user_id=:user_id"),
        {"user_id": owner_id},
    )
    age = age_from(await protected_date_of_birth(session, owner_id))
    primary_photo = await _primary_photo_view(
        session, profile_id, allow_pending=is_self or is_admin_context
    )

    blocked = (
        viewer is not None
        and not is_self
        and not is_admin_context
        and await is_blocked(session, viewer.id, owner_id)
    )
    try:
        projection = build_projection(
            profile=dict(profile),
            payload=payload,
            field_manifest=release["field_manifest"],
            context=context,
            display_name=str(display_name or "VAV Member"),
            age_years=age,
            age_display_mode=str(payload.get("basic.age_display_mode") or "exact_age"),
            primary_photo=primary_photo,
            field_overrides=await field_visibility_overrides(session, owner_id),
            moderation_badges=_moderation_badges(dict(profile)),
            blocked=bool(blocked),
            ai_consent_granted=await ai_consent_granted(session, owner_id),
        )
    except ProfileNotVisibleError as exc:
        raise VavError(
            "DATING_PROFILE_NOT_AVAILABLE", "This profile is not available.", status_code=404
        ) from exc

    if viewer is not None and not is_self:
        await audit(
            session,
            "matchmaking.profile.viewed",
            "dating_profile",
            profile_id,
            actor_id=viewer.id,
            context={"view_context": context.value},
        )
        await session.commit()
    return projection


def _moderation_badges(profile: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    if profile["review_status"] == ProfileReviewStatus.APPROVED.value:
        badges.append("profile_reviewed")
    if profile["status"] == DatingProfileStatus.SUSPENDED.value:
        badges.append("profile_suspended")
    return badges


async def _primary_photo_view(
    session: AsyncSession, profile_id: UUID, *, allow_pending: bool
) -> dict[str, Any] | None:
    statuses = "('approved','review_required')" if allow_pending else "('approved')"
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,status,processing_report FROM dating_profile_photos "
                    f"WHERE dating_profile_id=:id AND photo_role='primary' AND status IN {statuses} "
                    "AND deleted_at IS NULL"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    report = row["processing_report"] or {}
    return {
        "photo_id": str(row["id"]),
        "status": row["status"],
        "width": report.get("width"),
        "height": report.get("height"),
        "requires_view_token": True,
    }


# --------------------------------------------------------------------------
# Recommendation projections
# --------------------------------------------------------------------------


async def rebuild_projection(session: AsyncSession, profile_id: UUID) -> dict[str, Any]:
    """Rebuild the recommendation projection idempotently."""
    settings = get_settings()
    profile = (
        (
            await session.execute(
                text("SELECT * FROM dating_profiles WHERE id=:id"), {"id": profile_id}
            )
        )
        .mappings()
        .first()
    )
    if profile is None:
        raise VavError("DATING_PROFILE_NOT_FOUND", "Profile not found.", status_code=404)

    owner_id = profile["user_id"]
    account_status = await session.scalar(
        text("SELECT status FROM users WHERE id=:id"), {"id": owner_id}
    )
    privacy_row = (
        (
            await session.execute(
                text(
                    "SELECT visible_in_matchmaking,settings_version FROM user_privacy_settings WHERE user_id=:id"
                ),
                {"id": owner_id},
            )
        )
        .mappings()
        .first()
    )
    preference = (
        (
            await session.execute(
                text(
                    "SELECT id,preference_version,status FROM partner_preference_profiles WHERE dating_profile_id=:id"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )

    completeness_row = (
        (
            await session.execute(
                text(
                    "SELECT recommendation_eligible FROM dating_profile_completeness_snapshots "
                    "WHERE dating_profile_id=:id ORDER BY profile_version_number DESC LIMIT 1"
                ),
                {"id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    has_photo = bool(
        await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND photo_role='primary' AND status='approved' AND deleted_at IS NULL"
            ),
            {"id": profile_id},
        )
    )
    age = age_from(await protected_date_of_birth(session, owner_id))
    criteria = await preference_criteria(session, profile_id)

    eligible, reasons = projections.eligibility(
        profile_status=str(profile["status"]),
        approved_version_number=profile["approved_version_number"],
        account_active=account_status == "active",
        age_years=age,
        minimum_age=settings.dating_minimum_age,
        completeness_recommendation_eligible=bool(
            completeness_row and completeness_row["recommendation_eligible"]
        ),
        has_approved_primary_photo=has_photo,
        require_primary_photo=settings.dating_profile_require_primary_photo,
        privacy_allows_matchmaking=bool(privacy_row and privacy_row["visible_in_matchmaking"]),
        security_suspended=profile["suspended_at"] is not None,
        preferences_valid=bool(preference and preference["status"] in {"confirmed", "active"}),
    )

    if not eligible:
        removed = await session.execute(
            text(
                "DELETE FROM dating_profile_recommendation_projections WHERE dating_profile_id=:id"
            ),
            {"id": profile_id},
        )
        if int(getattr(removed, "rowcount", 0) or 0):
            await emit_event(
                session,
                "dating_profile.projection.removed",
                profile_id,
                {"reason_codes": reasons},
            )
        await session.commit()
        return {"eligible": False, "reason_codes": reasons, "profile_id": str(profile_id)}

    approved_snapshot = (
        await session.execute(
            text(
                "SELECT snapshot_encrypted FROM dating_profile_versions "
                "WHERE dating_profile_id=:id AND version_number=:version AND approved_at IS NOT NULL"
            ),
            {"id": profile_id, "version": profile["approved_version_number"]},
        )
    ).scalar()
    payload = dict(decrypt_private(str(approved_snapshot))["fields"])

    preference_version = int(preference["preference_version"]) if preference else 1
    privacy_version = int(privacy_row["settings_version"]) if privacy_row else 1
    built = projections.build_payload(payload, age_years=age, criteria=criteria)
    digest = projections.checksum(
        built,
        approved_version=int(profile["approved_version_number"]),
        preference_version=preference_version,
        privacy_version=privacy_version,
    )
    previous_checksum = await session.scalar(
        text(
            "SELECT projection_checksum FROM dating_profile_recommendation_projections "
            "WHERE dating_profile_id=:id"
        ),
        {"id": profile_id},
    )

    await session.execute(
        text(
            "INSERT INTO dating_profile_recommendation_projections "
            "(dating_profile_id,user_id,approved_profile_version,preference_version,privacy_settings_version,"
            "eligible,ineligible_reason_codes,age_bucket,age_years,country_code,region_code,city_code,gender_code,"
            "eligible_partner_gender_codes,faith_codes,relationship_intent,marital_status_code,children_status_code,"
            "relocation_willingness,language_codes,lifestyle_codes,indexed_preference_criteria,projection_checksum,"
            "projection_version,updated_at) "
            "VALUES (:profile_id,:user_id,:approved,:preference,:privacy,true,'[]'::jsonb,:age_bucket,:age_years,"
            ":country,:region,:city,:gender,CAST(:partner_genders AS jsonb),CAST(:faith AS jsonb),:intent,:marital,"
            ":children,:relocation,CAST(:languages AS jsonb),CAST(:lifestyle AS jsonb),CAST(:criteria AS jsonb),"
            ":checksum,1,now()) "
            "ON CONFLICT (dating_profile_id) DO UPDATE SET "
            "approved_profile_version=EXCLUDED.approved_profile_version,preference_version=EXCLUDED.preference_version,"
            "privacy_settings_version=EXCLUDED.privacy_settings_version,eligible=true,ineligible_reason_codes='[]'::jsonb,"
            "age_bucket=EXCLUDED.age_bucket,age_years=EXCLUDED.age_years,country_code=EXCLUDED.country_code,"
            "region_code=EXCLUDED.region_code,city_code=EXCLUDED.city_code,gender_code=EXCLUDED.gender_code,"
            "eligible_partner_gender_codes=EXCLUDED.eligible_partner_gender_codes,faith_codes=EXCLUDED.faith_codes,"
            "relationship_intent=EXCLUDED.relationship_intent,marital_status_code=EXCLUDED.marital_status_code,"
            "children_status_code=EXCLUDED.children_status_code,relocation_willingness=EXCLUDED.relocation_willingness,"
            "language_codes=EXCLUDED.language_codes,lifestyle_codes=EXCLUDED.lifestyle_codes,"
            "indexed_preference_criteria=EXCLUDED.indexed_preference_criteria,"
            "projection_version=dating_profile_recommendation_projections.projection_version + "
            "CASE WHEN dating_profile_recommendation_projections.projection_checksum <> EXCLUDED.projection_checksum THEN 1 ELSE 0 END,"
            "projection_checksum=EXCLUDED.projection_checksum,updated_at=now()"
        ),
        {
            "profile_id": profile_id,
            "user_id": owner_id,
            "approved": profile["approved_version_number"],
            "preference": preference_version,
            "privacy": privacy_version,
            "age_bucket": built["age_bucket"],
            "age_years": built["age_years"],
            "country": built["country_code"],
            "region": built["region_code"],
            "city": built["city_code"],
            "gender": built["gender_code"],
            "partner_genders": json_value(built["eligible_partner_gender_codes"]),
            "faith": json_value(built["faith_codes"]),
            "intent": built["relationship_intent"],
            "marital": built["marital_status_code"],
            "children": built["children_status_code"],
            "relocation": built["relocation_willingness"],
            "languages": json_value(built["language_codes"]),
            "lifestyle": json_value(built["lifestyle_codes"]),
            "criteria": json_value(built["indexed_preference_criteria"]),
            "checksum": digest,
        },
    )
    if previous_checksum != digest:
        await emit_event(
            session,
            "dating_profile.projection.updated",
            profile_id,
            {"checksum": digest, "approved_version": profile["approved_version_number"]},
        )
        await audit(
            session,
            "matchmaking.projection.updated",
            "dating_profile",
            profile_id,
            context={"checksum": digest},
        )
    await session.commit()
    return {"eligible": True, "checksum": digest, "profile_id": str(profile_id)}


async def process_projection_jobs(session: AsyncSession, limit: int = 50) -> dict[str, Any]:
    """Drain queued projection rebuilds; duplicates collapse to one rebuild."""
    settings = get_settings()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,dating_profile_id,attempts FROM dating_profile_projection_jobs "
                    "WHERE status='pending' ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {"limit": limit},
            )
        )
        .mappings()
        .all()
    )
    processed = 0
    failed = 0
    for row in rows:
        try:
            await rebuild_projection(session, row["dating_profile_id"])
            await session.execute(
                text(
                    "UPDATE dating_profile_projection_jobs SET status='completed',processed_at=now() WHERE id=:id"
                ),
                {"id": row["id"]},
            )
            processed += 1
        except VavError as exc:
            attempts = int(row["attempts"]) + 1
            await session.execute(
                text(
                    "UPDATE dating_profile_projection_jobs SET attempts=:attempts,last_error=:error,"
                    "status=CASE WHEN :attempts >= :max THEN 'failed' ELSE 'pending' END WHERE id=:id"
                ),
                {
                    "id": row["id"],
                    "attempts": attempts,
                    "error": exc.code,
                    "max": settings.dating_projection_job_max_attempts,
                },
            )
            failed += 1
    await session.commit()
    return {"processed": processed, "failed": failed}
