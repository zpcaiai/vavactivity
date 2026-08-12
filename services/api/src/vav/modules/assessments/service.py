"""Transactional paid-assessment service (B17).

The invariants this file exists to hold:

1. Publication is gated twice — by :func:`vav.modules.assessments.domain.ensure_version_publishable`
   here and by a CHECK constraint in migration ``20260812_0101``. A version
   without a verified licence reference cannot become ``published`` through any
   path, including a direct SQL update.
2. A purchase writes ``version_id`` onto the purchase, the entitlement and every
   attempt. No query in this file resolves "the product's current version" when
   serving an entitled member, so publishing v2 cannot move a v1 buyer.
3. Refund and revocation run through one planner, so the answer to "what happens
   to my half-finished attempt" is the same everywhere.
4. Answers and AI advice are encrypted at rest; deterministic scores are not
   (they are the thing that must stay queryable and re-derivable).
5. All rules live in :mod:`vav.modules.assessments.domain`.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.assessments.domain import (
    AdviceBlock,
    AssessmentQuestionSpec,
    AssessmentRuleError,
    AssessmentVersionSpec,
    AttemptAction,
    AttemptStatus,
    ContentSource,
    EntitlementState,
    EntitlementStatus,
    LicenseRecord,
    ProductStatus,
    ReportAction,
    VersionStatus,
    assemble_report_payload,
    attempt_idempotency_key,
    build_purchase_intent,
    catalogue_view,
    ensure_entitlement_usable,
    ensure_refund_window_open,
    ensure_report_readable,
    ensure_version_matches_entitlement,
    ensure_version_publishable,
    plan_revocation,
    report_idempotency_key,
    score_attempt,
    scores_fingerprint,
    validate_attempt_answers,
    validate_attempt_transition,
    validate_purchase_transition,
    validate_version_transition,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: AssessmentRuleError, status_code: int = 422) -> VavError:
    """``VavError.details`` is a list in this codebase, so wrap the mapping."""

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def enabled() -> None:
    """DEC-001 safe default: paid assessments ship switched off."""

    if not get_settings().paid_assessments_enabled:
        raise VavError(
            "PAID_ASSESSMENTS_DISABLED", "Paid assessments are not enabled.", status_code=503
        )


async def _publish(session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'assessment',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


# ---------------------------------------------------------------------------
# ASSESS-001 catalogue
# ---------------------------------------------------------------------------


async def create_product(session: AsyncSession, *, actor_id: UUID, payload: dict) -> dict:
    enabled()
    product_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO assessment_products "
                "(id,product_code,title_code,category_code,status,refund_window_hours,created_by) "
                "VALUES (:id,:code,:title,:category,'draft',:window,:actor)"
            ),
            {
                "id": str(product_id),
                "code": payload["product_code"],
                "title": payload["title_code"],
                "category": payload["category_code"],
                "window": int(payload.get("refund_window_hours", 72)),
                "actor": str(actor_id),
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "ASSESSMENT_PRODUCT_DUPLICATE", "That product code already exists.", status_code=409
        ) from exc
    await session.commit()
    return {"product_id": str(product_id), "status": ProductStatus.DRAFT.value}


async def activate_product(session: AsyncSession, *, product_id: UUID, actor_id: UUID) -> dict:
    """A product goes on sale only once it has a published version.

    Otherwise the catalogue would advertise something nobody could buy, and the
    first purchase attempt would fail against ``ASSESSMENT_VERSION_NOT_PURCHASABLE``.
    """

    enabled()
    published = await session.scalar(
        text(
            "SELECT count(*) FROM assessment_versions WHERE product_id=:id AND status='published'"
        ),
        {"id": str(product_id)},
    )
    if not published:
        raise VavError(
            "ASSESSMENT_PRODUCT_HAS_NO_PUBLISHED_VERSION",
            "A product needs at least one published version before it can be sold.",
            status_code=409,
        )
    result = await session.execute(
        text(
            "UPDATE assessment_products SET status='active',updated_at=now() "
            "WHERE id=:id AND status IN ('draft','retired')"
        ),
        {"id": str(product_id)},
    )
    if result.rowcount == 0:
        raise VavError(
            "ASSESSMENT_PRODUCT_NOT_FOUND", "Product not found or already active.", status_code=409
        )
    await session.commit()
    return {"product_id": str(product_id), "status": ProductStatus.ACTIVE.value}


async def create_version(
    session: AsyncSession, *, product_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    enabled()
    version_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO assessment_versions "
                "(id,product_id,semantic_version,algorithm_version,status,content_source,license_reference,"
                "licensor_name,price_minor_units,currency,created_by) "
                "VALUES (:id,:product_id,:semver,:algorithm,'draft',:source,:reference,:licensor,:price,:currency,:actor)"
            ),
            {
                "id": str(version_id),
                "product_id": str(product_id),
                "semver": payload["semantic_version"],
                "algorithm": payload["algorithm_version"],
                "source": ContentSource(payload["content_source"]).value,
                "reference": payload.get("license_reference"),
                "licensor": payload.get("licensor_name"),
                "price": int(payload["price_minor_units"]),
                "currency": payload.get("currency", "CNY"),
                "actor": str(actor_id),
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "ASSESSMENT_VERSION_DUPLICATE",
            "That semantic version already exists for this product.",
            status_code=409,
        ) from exc
    await session.commit()
    return {"version_id": str(version_id), "status": VersionStatus.DRAFT.value}


async def verify_license(
    session: AsyncSession, *, version_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    """Record who checked the licence and when.

    Split from version creation deliberately: the person authoring content and
    the person who confirms the platform is allowed to sell it are usually not
    the same, and the audit answer to "who signed this off" must name a human.
    """

    enabled()
    result = await session.execute(
        text(
            "UPDATE assessment_versions SET license_reference=:reference,licensor_name=:licensor,"
            "license_verified_at=now(),license_verified_by=:actor,license_note=:note,updated_at=now() "
            "WHERE id=:id AND status='draft'"
        ),
        {
            "reference": payload["license_reference"],
            "licensor": payload.get("licensor_name"),
            "actor": str(actor_id),
            "note": payload.get("note"),
            "id": str(version_id),
        },
    )
    if result.rowcount == 0:
        raise VavError(
            "ASSESSMENT_VERSION_NOT_DRAFT",
            "A licence can only be recorded against a draft version.",
            status_code=409,
        )
    await session.commit()
    return {"version_id": str(version_id), "license_verified": True}


async def add_version_question(
    session: AsyncSession, *, version_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    enabled()
    status = await session.scalar(
        text("SELECT status FROM assessment_versions WHERE id=:id FOR UPDATE"),
        {"id": str(version_id)},
    )
    if status is None:
        raise VavError("ASSESSMENT_VERSION_NOT_FOUND", "Version not found.", status_code=404)
    if status != VersionStatus.DRAFT:
        raise VavError(
            "ASSESSMENT_VERSION_NOT_DRAFT",
            "A published version is immutable; publish a new semantic version instead.",
            status_code=409,
        )
    try:
        spec = AssessmentQuestionSpec(
            question_id=uuid4(),
            question_code=payload["question_code"],
            dimension_code=payload["dimension_code"],
            weight=int(payload.get("weight", 1)),
            scale_min=int(payload.get("scale_min", 1)),
            scale_max=int(payload.get("scale_max", 5)),
            reverse_scored=bool(payload.get("reverse_scored", False)),
            position=int(payload.get("position", 0)),
        )
    except AssessmentRuleError as error:
        raise _fail(error) from error
    try:
        await session.execute(
            text(
                "INSERT INTO assessment_version_questions "
                "(id,version_id,question_code,dimension_code,prompt_text,weight,scale_min,scale_max,reverse_scored,position) "
                "VALUES (:id,:version_id,:code,:dimension,:prompt,:weight,:scale_min,:scale_max,:reverse,:position)"
            ),
            {
                "id": str(spec.question_id),
                "version_id": str(version_id),
                "code": spec.question_code,
                "dimension": spec.dimension_code,
                "prompt": payload["prompt_text"],
                "weight": spec.weight,
                "scale_min": spec.scale_min,
                "scale_max": spec.scale_max,
                "reverse": spec.reverse_scored,
                "position": spec.position,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "ASSESSMENT_QUESTION_CODE_DUPLICATE",
            "That question code already exists in this version.",
            status_code=409,
        ) from exc
    await session.execute(
        text(
            "UPDATE assessment_versions SET question_count=question_count+1,updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(version_id)},
    )
    await session.commit()
    return {"question_id": str(spec.question_id), "version_id": str(version_id)}


async def _load_version_spec(session: AsyncSession, version_id: UUID) -> AssessmentVersionSpec:
    header = (
        (
            await session.execute(
                text(
                    "SELECT id,product_id,semantic_version,algorithm_version,status,content_source,"
                    "license_reference,license_verified_at,license_verified_by,licensor_name,"
                    "price_minor_units,currency FROM assessment_versions WHERE id=:id"
                ),
                {"id": str(version_id)},
            )
        )
        .mappings()
        .first()
    )
    if header is None:
        raise VavError("ASSESSMENT_VERSION_NOT_FOUND", "Version not found.", status_code=404)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,question_code,dimension_code,weight,scale_min,scale_max,reverse_scored,position "
                    "FROM assessment_version_questions WHERE version_id=:id ORDER BY position,question_code"
                ),
                {"id": str(version_id)},
            )
        )
        .mappings()
        .all()
    )
    return AssessmentVersionSpec(
        version_id=UUID(str(header["id"])),
        product_id=UUID(str(header["product_id"])),
        semantic_version=header["semantic_version"],
        algorithm_version=header["algorithm_version"],
        license=LicenseRecord(
            content_source=ContentSource(header["content_source"]),
            license_reference=header["license_reference"],
            license_verified_at=header["license_verified_at"],
            license_verified_by=(
                UUID(str(header["license_verified_by"])) if header["license_verified_by"] else None
            ),
            licensor_name=header["licensor_name"],
        ),
        price_minor_units=int(header["price_minor_units"]),
        currency=header["currency"],
        questions=tuple(
            AssessmentQuestionSpec(
                question_id=UUID(str(row["id"])),
                question_code=row["question_code"],
                dimension_code=row["dimension_code"],
                weight=int(row["weight"]),
                scale_min=int(row["scale_min"]),
                scale_max=int(row["scale_max"]),
                reverse_scored=bool(row["reverse_scored"]),
                position=int(row["position"]),
            )
            for row in rows
        ),
    )


async def publish_version(session: AsyncSession, *, version_id: UUID, actor_id: UUID) -> dict:
    """The publication gate (ASSESS-001).

    Refuses without a recorded, verified licence reference. The same rule is
    also a CHECK constraint on ``assessment_versions``, so an operator with SQL
    access cannot flip the status either.
    """

    enabled()
    current_status = await session.scalar(
        text("SELECT status FROM assessment_versions WHERE id=:id FOR UPDATE"),
        {"id": str(version_id)},
    )
    if current_status is None:
        raise VavError("ASSESSMENT_VERSION_NOT_FOUND", "Version not found.", status_code=404)
    spec = await _load_version_spec(session, version_id)
    try:
        validate_version_transition(current_status, VersionStatus.PUBLISHED)
        ensure_version_publishable(spec, now=_now())
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE assessment_versions SET status='published',published_by=:actor,published_at=now(),"
            "updated_at=now() WHERE id=:id AND status='draft'"
        ),
        {"actor": str(actor_id), "id": str(version_id)},
    )
    await _publish(
        session,
        "assessment.version.published.v1",
        version_id,
        {
            "version_id": str(version_id),
            "product_id": str(spec.product_id),
            "semantic_version": spec.semantic_version,
            "content_source": spec.license.content_source.value,
        },
    )
    await session.commit()
    return {"version_id": str(version_id), "status": VersionStatus.PUBLISHED.value}


async def retire_version(session: AsyncSession, *, version_id: UUID, actor_id: UUID) -> dict:
    """Stop new purchases without disturbing anybody who already bought it."""

    enabled()
    current_status = await session.scalar(
        text("SELECT status FROM assessment_versions WHERE id=:id FOR UPDATE"),
        {"id": str(version_id)},
    )
    if current_status is None:
        raise VavError("ASSESSMENT_VERSION_NOT_FOUND", "Version not found.", status_code=404)
    try:
        validate_version_transition(current_status, VersionStatus.RETIRED)
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE assessment_versions SET status='retired',retired_at=now(),updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(version_id)},
    )
    await session.commit()
    return {"version_id": str(version_id), "status": VersionStatus.RETIRED.value}


async def list_catalogue(session: AsyncSession, *, include_unpublished: bool = False) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT v.id,v.product_id,p.product_code,p.title_code,p.category_code,v.semantic_version,"
                    "v.status,v.price_minor_units,v.currency,v.question_count,v.content_source "
                    "FROM assessment_versions v JOIN assessment_products p ON p.id=v.product_id "
                    "WHERE (CAST(:include_all AS BOOLEAN) OR (v.status='published' AND p.status='active')) "
                    "ORDER BY p.product_code, v.semantic_version"
                ),
                {"include_all": include_unpublished},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in catalogue_view(rows, include_unpublished=include_unpublished)]


# ---------------------------------------------------------------------------
# ASSESS-001 purchase and entitlement
# ---------------------------------------------------------------------------


async def purchase(session: AsyncSession, *, user_id: UUID, payload: dict) -> dict:
    """Record a purchase and mint the entitlement bound to that exact version."""

    enabled()
    version_id = UUID(str(payload["version_id"]))
    spec = await _load_version_spec(session, version_id)
    header = (
        (
            await session.execute(
                text(
                    "SELECT v.status AS version_status, p.status AS product_status "
                    "FROM assessment_versions v JOIN assessment_products p ON p.id=v.product_id "
                    "WHERE v.id=:id"
                ),
                {"id": str(version_id)},
            )
        )
        .mappings()
        .first()
    )
    try:
        intent = build_purchase_intent(
            spec,
            user_id=user_id,
            order_id=str(payload["order_id"]),
            version_status=header["version_status"],
            product_status=header["product_status"],
            quoted_price_minor_units=int(payload["quoted_price_minor_units"]),
        )
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error

    purchase_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO assessment_purchases "
                "(id,user_id,product_id,version_id,order_id,status,price_minor_units,currency,idempotency_key,purchased_at) "
                "VALUES (:id,:user_id,:product_id,:version_id,:order_id,'paid',:price,:currency,:key,now())"
            ),
            {
                "id": str(purchase_id),
                "user_id": str(user_id),
                "product_id": str(intent.product_id),
                "version_id": str(intent.version_id),
                "order_id": intent.idempotency_key.rsplit(":", 1)[-1],
                "price": intent.price_minor_units,
                "currency": intent.currency,
                "key": intent.idempotency_key,
            },
        )
    except IntegrityError:
        # A replayed payment callback: return the purchase that already exists
        # rather than charging or entitling twice.
        await session.rollback()
        existing = (
            (
                await session.execute(
                    text(
                        "SELECT p.id,p.version_id,e.id AS entitlement_id FROM assessment_purchases p "
                        "LEFT JOIN assessment_entitlements e ON e.purchase_id=p.id "
                        "WHERE p.idempotency_key=:key"
                    ),
                    {"key": intent.idempotency_key},
                )
            )
            .mappings()
            .first()
        )
        if existing is None:  # pragma: no cover - defensive
            raise
        return {
            "purchase_id": str(existing["id"]),
            "version_id": str(existing["version_id"]),
            "entitlement_id": (
                str(existing["entitlement_id"]) if existing["entitlement_id"] else None
            ),
            "replayed": True,
        }

    entitlement_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO assessment_entitlements "
            "(id,user_id,purchase_id,product_id,version_id,status,attempts_granted,attempts_consumed) "
            "VALUES (:id,:user_id,:purchase_id,:product_id,:version_id,'active',:granted,0)"
        ),
        {
            "id": str(entitlement_id),
            "user_id": str(user_id),
            "purchase_id": str(purchase_id),
            "product_id": str(intent.product_id),
            # The pin. Everything downstream reads this column, never
            # "the product's current version".
            "version_id": str(intent.version_id),
            "granted": intent.attempts_granted,
        },
    )
    await _publish(
        session,
        "assessment.purchase.completed.v1",
        purchase_id,
        {
            "purchase_id": str(purchase_id),
            "user_id": str(user_id),
            "version_id": str(intent.version_id),
            "semantic_version": intent.semantic_version,
        },
    )
    await session.commit()
    return {
        "purchase_id": str(purchase_id),
        "entitlement_id": str(entitlement_id),
        "version_id": str(intent.version_id),
        "semantic_version": intent.semantic_version,
        "replayed": False,
    }


async def _load_entitlement(
    session: AsyncSession, entitlement_id: UUID, *, lock: bool
) -> EntitlementState:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,user_id,version_id,status,attempts_granted,attempts_consumed,expires_at "
                    "FROM assessment_entitlements WHERE id=:id" + suffix
                ),
                {"id": str(entitlement_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "ASSESSMENT_ENTITLEMENT_NOT_FOUND", "Entitlement not found.", status_code=404
        )
    return EntitlementState(
        entitlement_id=UUID(str(row["id"])),
        user_id=UUID(str(row["user_id"])),
        version_id=UUID(str(row["version_id"])),
        status=EntitlementStatus(row["status"]),
        attempts_granted=int(row["attempts_granted"]),
        attempts_consumed=int(row["attempts_consumed"]),
        expires_at=row["expires_at"],
    )


async def list_my_entitlements(session: AsyncSession, user_id: UUID) -> list[dict]:
    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT e.id,e.version_id,e.status,e.attempts_granted,e.attempts_consumed,e.expires_at,"
                    "v.semantic_version,v.algorithm_version,p.product_code FROM assessment_entitlements e "
                    "JOIN assessment_versions v ON v.id=e.version_id "
                    "JOIN assessment_products p ON p.id=e.product_id "
                    "WHERE e.user_id=:user_id ORDER BY e.created_at DESC"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# ASSESS-001 attempts
# ---------------------------------------------------------------------------


async def start_attempt(session: AsyncSession, *, entitlement_id: UUID, user_id: UUID) -> dict:
    enabled()
    state = await _load_entitlement(session, entitlement_id, lock=True)
    if state.user_id != user_id:
        raise VavError(
            "ASSESSMENT_ENTITLEMENT_NOT_FOUND", "Entitlement not found.", status_code=404
        )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT id,status,version_id FROM assessment_attempts "
                    "WHERE entitlement_id=:id AND status IN ('in_progress','submitted','scored') "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": str(entitlement_id)},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return {
            "attempt_id": str(existing["id"]),
            "status": existing["status"],
            "version_id": str(existing["version_id"]),
            "created": False,
        }
    try:
        ensure_entitlement_usable(state, now=_now())
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error
    attempt_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO assessment_attempts "
            "(id,entitlement_id,user_id,version_id,status,idempotency_key,started_at) "
            "VALUES (:id,:entitlement_id,:user_id,:version_id,'in_progress',:key,now())"
        ),
        {
            "id": str(attempt_id),
            "entitlement_id": str(entitlement_id),
            "user_id": str(user_id),
            # Pinned from the entitlement, not from any "current version" lookup.
            "version_id": str(state.version_id),
            "key": attempt_idempotency_key(entitlement_id, state.attempts_consumed + 1),
        },
    )
    await session.execute(
        text(
            "UPDATE assessment_entitlements SET attempts_consumed=attempts_consumed+1,"
            "status=CASE WHEN attempts_consumed+1 >= attempts_granted THEN 'consumed' ELSE status END,"
            "updated_at=now() WHERE id=:id"
        ),
        {"id": str(entitlement_id)},
    )
    await session.commit()
    return {
        "attempt_id": str(attempt_id),
        "status": AttemptStatus.IN_PROGRESS.value,
        "version_id": str(state.version_id),
        "created": True,
    }


async def _attempt_for_member(
    session: AsyncSession, attempt_id: UUID, user_id: UUID, *, lock: bool = False
) -> dict:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,entitlement_id,user_id,version_id,status,answers_encrypted "
                    "FROM assessment_attempts WHERE id=:id AND user_id=:user_id" + suffix
                ),
                {"id": str(attempt_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ASSESSMENT_ATTEMPT_NOT_FOUND", "Attempt not found.", status_code=404)
    return dict(row)


async def get_attempt(session: AsyncSession, *, attempt_id: UUID, user_id: UUID) -> dict:
    """Serve the questions of the version this attempt is pinned to."""

    enabled()
    attempt = await _attempt_for_member(session, attempt_id, user_id)
    entitlement = await _load_entitlement(
        session, UUID(str(attempt["entitlement_id"])), lock=False
    )
    try:
        ensure_version_matches_entitlement(
            entitlement_version_id=entitlement.version_id,
            requested_version_id=UUID(str(attempt["version_id"])),
        )
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error
    spec = await _load_version_spec(session, UUID(str(attempt["version_id"])))
    prompts = (
        (
            await session.execute(
                text(
                    "SELECT question_code,dimension_code,prompt_text,scale_min,scale_max,position "
                    "FROM assessment_version_questions WHERE version_id=:id ORDER BY position,question_code"
                ),
                {"id": str(attempt["version_id"])},
            )
        )
        .mappings()
        .all()
    )
    return {
        "attempt_id": str(attempt_id),
        "status": attempt["status"],
        "version_id": str(spec.version_id),
        "semantic_version": spec.semantic_version,
        "questions": [dict(row) for row in prompts],
        "answers": (
            json.loads(decrypt_private(attempt["answers_encrypted"]))
            if attempt["answers_encrypted"]
            else {}
        ),
    }


async def save_attempt_answers(
    session: AsyncSession, *, attempt_id: UUID, user_id: UUID, payload: dict
) -> dict:
    enabled()
    attempt = await _attempt_for_member(session, attempt_id, user_id, lock=True)
    submit = bool(payload.get("submit", False))
    if attempt["status"] != AttemptStatus.IN_PROGRESS:
        raise VavError(
            "ASSESSMENT_ATTEMPT_CLOSED",
            "This attempt is no longer accepting answers.",
            status_code=409,
        )
    if submit:
        try:
            validate_attempt_transition(attempt["status"], AttemptStatus.SUBMITTED)
        except AssessmentRuleError as error:
            raise _fail(error, status_code=409) from error
    spec = await _load_version_spec(session, UUID(str(attempt["version_id"])))
    try:
        cleaned = validate_attempt_answers(
            spec, dict(payload.get("answers") or {}), partial=not submit
        )
    except AssessmentRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "UPDATE assessment_attempts SET answers_encrypted=:answers,answer_count=:count,"
            "status=:status,submitted_at=CASE WHEN :submit THEN now() ELSE submitted_at END,"
            "updated_at=now() WHERE id=:id"
        ),
        {
            "answers": encrypt_private(_json(cleaned)),
            "count": len(cleaned),
            "status": (
                AttemptStatus.SUBMITTED.value if submit else AttemptStatus.IN_PROGRESS.value
            ),
            "submit": submit,
            "id": str(attempt_id),
        },
    )
    result: dict[str, Any] = {
        "attempt_id": str(attempt_id),
        "status": AttemptStatus.SUBMITTED.value if submit else AttemptStatus.IN_PROGRESS.value,
        "answer_count": len(cleaned),
    }
    if submit:
        result["report_id"] = await _score_and_report(
            session, attempt_id=attempt_id, spec=spec, answers=cleaned
        )
        await _publish(
            session,
            "assessment.attempt.submitted.v1",
            attempt_id,
            {"attempt_id": str(attempt_id), "user_id": str(user_id)},
        )
    await session.commit()
    return result


async def _score_and_report(
    session: AsyncSession, *, attempt_id: UUID, spec: AssessmentVersionSpec, answers: dict
) -> str:
    """Score the attempt under its pinned version and store the report."""

    scores = score_attempt(spec, answers)
    now = _now()
    payload = assemble_report_payload(scores=scores, advice=None, generated_at=now)
    report_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO assessment_reports "
            "(id,attempt_id,version_id,algorithm_version,scores,scores_fingerprint,idempotency_key,status,generated_at) "
            "VALUES (:id,:attempt_id,:version_id,:algorithm,CAST(:scores AS jsonb),:fingerprint,:key,'generated',now()) "
            "ON CONFLICT (idempotency_key) DO NOTHING"
        ),
        {
            "id": str(report_id),
            "attempt_id": str(attempt_id),
            "version_id": str(spec.version_id),
            "algorithm": spec.algorithm_version,
            "scores": _json(payload["scores"]),
            "fingerprint": scores_fingerprint(scores),
            "key": report_idempotency_key(attempt_id, spec.algorithm_version),
        },
    )
    await session.execute(
        text("UPDATE assessment_attempts SET status='scored',updated_at=now() WHERE id=:id"),
        {"id": str(attempt_id)},
    )
    await _publish(
        session,
        "assessment.report.generated.v1",
        attempt_id,
        {"attempt_id": str(attempt_id), "algorithm_version": spec.algorithm_version},
    )
    return str(report_id)


async def get_report(session: AsyncSession, *, attempt_id: UUID, user_id: UUID) -> dict:
    enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.id,r.scores,r.scores_fingerprint,r.algorithm_version,r.status,"
                    "r.advice_encrypted,r.advice_model,r.advice_prompt_version,r.advice_generated_at,"
                    "r.advice_disclaimer_code,r.generated_at,a.user_id,e.status AS entitlement_status "
                    "FROM assessment_reports r JOIN assessment_attempts a ON a.id=r.attempt_id "
                    "JOIN assessment_entitlements e ON e.id=a.entitlement_id WHERE r.attempt_id=:id"
                ),
                {"id": str(attempt_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ASSESSMENT_REPORT_NOT_FOUND", "Report not found.", status_code=404)
    try:
        ensure_report_readable(
            viewer_id=user_id,
            owner_id=UUID(str(row["user_id"])),
            report_status=row["status"],
            entitlement_status=row["entitlement_status"],
        )
    except AssessmentRuleError as error:
        raise _fail(error, status_code=403) from error
    advice = None
    if row["advice_encrypted"]:
        advice = {
            "is_ai_generated": True,
            "model_code": row["advice_model"],
            "prompt_version": row["advice_prompt_version"],
            "generated_at": row["advice_generated_at"],
            "disclaimer_code": row["advice_disclaimer_code"],
            "body": decrypt_private(row["advice_encrypted"]),
        }
    return {
        "report_id": str(row["id"]),
        "attempt_id": str(attempt_id),
        "algorithm_version": row["algorithm_version"],
        "scores": row["scores"],
        "scores_fingerprint": row["scores_fingerprint"],
        "advice": advice,
        "generated_at": row["generated_at"],
    }


async def attach_advice(
    session: AsyncSession, *, attempt_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    enabled()
    if not get_settings().paid_assessment_ai_advice_enabled:
        raise VavError(
            "ASSESSMENT_ADVICE_DISABLED", "AI advice generation is not enabled.", status_code=503
        )
    exists = await session.scalar(
        text("SELECT 1 FROM assessment_reports WHERE attempt_id=:id FOR UPDATE"),
        {"id": str(attempt_id)},
    )
    if not exists:
        raise VavError("ASSESSMENT_REPORT_NOT_FOUND", "Report not found.", status_code=404)
    try:
        advice = AdviceBlock(
            body=payload["body"],
            model_code=payload["model_code"],
            prompt_version=payload["prompt_version"],
            generated_at=_now(),
            disclaimer_code=str(payload.get("disclaimer_code") or "assessment_ai_advice"),
        )
    except AssessmentRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "UPDATE assessment_reports SET advice_encrypted=:body,advice_model=:model,"
            "advice_prompt_version=:prompt_version,advice_generated_at=now(),"
            "advice_disclaimer_code=:disclaimer,updated_at=now() WHERE attempt_id=:id"
        ),
        {
            "body": encrypt_private(advice.body),
            "model": advice.model_code,
            "prompt_version": advice.prompt_version,
            "disclaimer": advice.disclaimer_code,
            "id": str(attempt_id),
        },
    )
    await session.commit()
    return {"attempt_id": str(attempt_id), "advice_attached": True}


# ---------------------------------------------------------------------------
# ASSESS-001 refund and revocation
# ---------------------------------------------------------------------------


async def refund_purchase(
    session: AsyncSession,
    *,
    purchase_id: UUID,
    actor_id: UUID | None,
    actor_kind: str,
    payload: dict,
) -> dict:
    """Apply the refund/revocation policy defined in the domain planner.

    Every branch is audited in ``assessment_refund_events``, including a refused
    refund, so "we said no and here is why" is queryable later.
    """

    enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT p.id,p.user_id,p.status,p.purchased_at,e.id AS entitlement_id "
                    "FROM assessment_purchases p LEFT JOIN assessment_entitlements e ON e.purchase_id=p.id "
                    "WHERE p.id=:id FOR UPDATE OF p"
                ),
                {"id": str(purchase_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ASSESSMENT_PURCHASE_NOT_FOUND", "Purchase not found.", status_code=404)
    trigger = str(payload["trigger"])
    if actor_kind == "member":
        if UUID(str(row["user_id"])) != actor_id:
            raise VavError(
                "ASSESSMENT_PURCHASE_NOT_FOUND", "Purchase not found.", status_code=404
            )
        try:
            ensure_refund_window_open(
                purchased_at=row["purchased_at"],
                now=_now(),
                window_hours=get_settings().paid_assessment_refund_window_hours,
            )
        except AssessmentRuleError as error:
            raise _fail(error, status_code=409) from error

    attempt = (
        (
            await session.execute(
                text(
                    "SELECT a.id,a.status,r.status AS report_status FROM assessment_attempts a "
                    "LEFT JOIN assessment_reports r ON r.attempt_id=a.id "
                    "WHERE a.entitlement_id=:id ORDER BY a.created_at DESC LIMIT 1"
                ),
                {"id": str(row["entitlement_id"])},
            )
        )
        .mappings()
        .first()
    )
    try:
        plan = plan_revocation(
            trigger=trigger,
            attempt_status=attempt["status"] if attempt else None,
            report_status=attempt["report_status"] if attempt else None,
            admin_override=bool(payload.get("admin_override", False)) and actor_kind == "admin",
            reason=payload.get("reason"),
        )
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "INSERT INTO assessment_refund_events "
            "(id,purchase_id,entitlement_id,trigger,attempt_action,report_action,refund_allowed,reason_code,reason,actor_id,actor_kind) "
            "VALUES (:id,:purchase_id,:entitlement_id,:trigger,:attempt_action,:report_action,:allowed,:reason_code,:reason,:actor,:actor_kind)"
        ),
        {
            "id": str(uuid4()),
            "purchase_id": str(purchase_id),
            "entitlement_id": str(row["entitlement_id"]) if row["entitlement_id"] else None,
            "trigger": trigger,
            "attempt_action": plan.attempt_action.value,
            "report_action": plan.report_action.value,
            "allowed": plan.refund_allowed,
            "reason_code": plan.reason_code,
            "reason": payload.get("reason"),
            "actor": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
        },
    )
    if not plan.refund_allowed:
        await session.commit()
        raise VavError(
            "ASSESSMENT_REFUND_REFUSED",
            "This purchase cannot be refunded because the report was already delivered.",
            status_code=409,
            details=[{"reason_code": plan.reason_code}],
        )

    try:
        validate_purchase_transition(row["status"], "refunded")
    except AssessmentRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE assessment_purchases SET status='refunded',refunded_at=now(),"
            "refund_reason=:reason,updated_at=now() WHERE id=:id"
        ),
        {"reason": payload.get("reason"), "id": str(purchase_id)},
    )
    await session.execute(
        text(
            "UPDATE assessment_entitlements SET status='revoked',revoked_at=now(),"
            "revoke_reason=:reason,updated_at=now() WHERE id=:id"
        ),
        {"reason": plan.reason_code, "id": str(row["entitlement_id"])},
    )
    if attempt and plan.attempt_action is AttemptAction.VOID:
        # Unfinished work is terminated. The answers stay in the row: they are
        # the member's own data and may be needed for a dispute.
        await session.execute(
            text(
                "UPDATE assessment_attempts SET status='voided',voided_at=now(),"
                "void_reason=:reason,updated_at=now() WHERE id=:id"
            ),
            {"reason": plan.reason_code, "id": str(attempt["id"])},
        )
    if attempt and plan.report_action is ReportAction.REVOKE_ACCESS:
        # Access withdrawn, row retained: a generated report is evidence of what
        # the member was shown and is never hard-deleted.
        await session.execute(
            text(
                "UPDATE assessment_reports SET status='revoked',revoked_at=now(),"
                "revoke_reason=:reason,updated_at=now() WHERE attempt_id=:id"
            ),
            {"reason": plan.reason_code, "id": str(attempt["id"])},
        )
    await _publish(
        session,
        "assessment.entitlement.revoked.v1",
        purchase_id,
        {
            "purchase_id": str(purchase_id),
            "entitlement_id": str(row["entitlement_id"]) if row["entitlement_id"] else None,
            "trigger": trigger,
            "attempt_action": plan.attempt_action.value,
            "report_action": plan.report_action.value,
        },
    )
    await session.commit()
    return {
        "purchase_id": str(purchase_id),
        "refunded": True,
        "attempt_action": plan.attempt_action.value,
        "report_action": plan.report_action.value,
        "reason_code": plan.reason_code,
    }


async def admin_list_purchases(session: AsyncSession, *, user_id: UUID | None) -> list[dict]:
    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,user_id,product_id,version_id,order_id,status,price_minor_units,currency,"
                    "purchased_at,refunded_at FROM assessment_purchases "
                    "WHERE (CAST(:user_id AS UUID) IS NULL OR user_id=CAST(:user_id AS UUID)) "
                    "ORDER BY created_at DESC LIMIT 200"
                ),
                {"user_id": str(user_id) if user_id else None},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def admin_license_audit(session: AsyncSession) -> list[dict]:
    """Every published version and the licence reference behind it.

    Exposed as a route because "prove we are allowed to sell all of this" is a
    question that gets asked with a deadline attached.
    """

    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT v.id,p.product_code,v.semantic_version,v.status,v.content_source,"
                    "v.license_reference,v.license_verified_at,v.license_verified_by,v.licensor_name "
                    "FROM assessment_versions v JOIN assessment_products p ON p.id=v.product_id "
                    "ORDER BY p.product_code,v.semantic_version"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
