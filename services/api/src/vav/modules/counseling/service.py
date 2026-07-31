from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.catalog import Price
from vav.models.commerce import Entitlement
from vav.models.counseling import (
    CounselingAppointment,
    CounselingAppointmentHistory,
    CounselingAvailabilityOverride,
    CounselingAvailabilityRule,
    CounselingMentor,
    CounselingMentorLocalization,
    CounselingMentorService,
    CounselingServiceDefinition,
    CounselingServiceLocalization,
    CounselingSession,
    CounselingSlotHold,
)
from vav.models.system import OutboxEvent
from vav.modules.commerce.service import entitlement_service
from vav.modules.counseling.domain import ensure_appointment_transition
from vav.modules.courses.crypto import (
    encrypt_sensitive,
)
from vav.modules.identity.audit import record_security_event


def now() -> datetime:
    return datetime.now(UTC)


async def transaction_lock(session: AsyncSession, key: str) -> None:
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


def appointment_number() -> str:
    return f"APT-{now():%Y%m%d}-{secrets.token_hex(5).upper()}"


async def public_service_payload(
    session: AsyncSession, service: CounselingServiceDefinition, locale: str
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CounselingServiceLocalization)
        .where(
            CounselingServiceLocalization.service_id == service.id,
            CounselingServiceLocalization.locale.in_((locale, "zh-CN")),
        )
        .order_by((CounselingServiceLocalization.locale == locale).desc())
        .limit(1)
    )
    prices: list[Price] = []
    if service.catalog_sku_id:
        current = now()
        prices = list(
            (
                await session.scalars(
                    select(Price).where(
                        Price.sku_id == service.catalog_sku_id,
                        Price.status == "active",
                        Price.valid_from <= current,
                        or_(Price.valid_until.is_(None), Price.valid_until > current),
                    )
                )
            ).all()
        )
    mentor_links = list(
        (
            await session.scalars(
                select(CounselingMentorService).where(
                    CounselingMentorService.service_id == service.id,
                    CounselingMentorService.status == "active",
                )
            )
        ).all()
    )
    return {
        "id": str(service.id),
        "service_code": service.service_code,
        "name": localization.name if localization else service.internal_name,
        "slug": localization.slug if localization else service.service_code,
        "summary": localization.summary if localization else None,
        "description_blocks": localization.description_blocks if localization else [],
        "scope_notice": localization.scope_notice
        if localization
        else "This service is educational support, not emergency or medical care.",
        "delivery_mode": service.delivery_mode,
        "participant_mode": service.participant_mode,
        "duration_minutes": service.duration_minutes,
        "booking_mode": service.booking_mode,
        "payment_policy": service.payment_policy,
        "free_access": service.free_access,
        "catalog_product_id": str(service.catalog_product_id)
        if service.catalog_product_id
        else None,
        "catalog_sku_id": str(service.catalog_sku_id) if service.catalog_sku_id else None,
        "prices": [
            {"currency": item.currency_code, "unit_amount_minor": item.unit_amount_minor}
            for item in prices
        ],
        "mentor_ids": [str(item.mentor_id) for item in mentor_links],
    }


async def public_mentor_payload(
    session: AsyncSession, mentor: CounselingMentor, locale: str
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CounselingMentorLocalization)
        .where(
            CounselingMentorLocalization.mentor_id == mentor.id,
            CounselingMentorLocalization.locale.in_((locale, "zh-CN")),
        )
        .order_by((CounselingMentorLocalization.locale == locale).desc())
        .limit(1)
    )
    return {
        "id": str(mentor.id),
        "mentor_code": mentor.mentor_code,
        "slug": localization.slug if localization else mentor.mentor_code,
        "name": localization.public_name if localization else mentor.display_name,
        "headline": localization.headline if localization else None,
        "biography_blocks": localization.biography_blocks if localization else [],
        "scope_statement": localization.scope_statement if localization else None,
        "timezone": mentor.timezone,
        "service_languages": mentor.service_languages,
        "specialty_topics": mentor.specialty_topics,
    }


class AvailabilityService:
    async def slots(
        self,
        session: AsyncSession,
        *,
        mentor_id: UUID,
        service_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, str]]:
        if (end_date - start_date).days > get_settings().counseling_availability_max_range_days:
            raise VavError(
                "COUNSELING_AVAILABILITY_RANGE_TOO_LARGE",
                "Availability range exceeds the configured maximum.",
                status_code=422,
            )
        mentor = await session.get(CounselingMentor, mentor_id)
        service = await session.get(CounselingServiceDefinition, service_id)
        if (
            mentor is None
            or mentor.status != "active"
            or service is None
            or service.status != "published"
        ):
            raise VavError(
                "COUNSELING_AVAILABILITY_NOT_FOUND", "Availability was not found.", status_code=404
            )
        rules = list(
            (
                await session.scalars(
                    select(CounselingAvailabilityRule).where(
                        CounselingAvailabilityRule.mentor_id == mentor_id,
                        CounselingAvailabilityRule.status == "active",
                        or_(
                            CounselingAvailabilityRule.service_id.is_(None),
                            CounselingAvailabilityRule.service_id == service_id,
                        ),
                    )
                )
            ).all()
        )
        overrides = list(
            (
                await session.scalars(
                    select(CounselingAvailabilityOverride).where(
                        CounselingAvailabilityOverride.mentor_id == mentor_id,
                        CounselingAvailabilityOverride.ends_at
                        > datetime.combine(start_date, time.min, tzinfo=UTC),
                        CounselingAvailabilityOverride.starts_at
                        < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC),
                    )
                )
            ).all()
        )
        blocking_statuses = ("confirmed", "reschedule_requested")
        appointments = list(
            (
                await session.scalars(
                    select(CounselingAppointment).where(
                        CounselingAppointment.mentor_id == mentor_id,
                        CounselingAppointment.status.in_(blocking_statuses),
                        CounselingAppointment.scheduled_starts_at.is_not(None),
                    )
                )
            ).all()
        )
        holds = list(
            (
                await session.scalars(
                    select(CounselingSlotHold).where(
                        CounselingSlotHold.mentor_id == mentor_id,
                        CounselingSlotHold.status == "active",
                        CounselingSlotHold.expires_at > now(),
                    )
                )
            ).all()
        )
        result: list[dict[str, str]] = []
        cursor = start_date
        while cursor <= end_date:
            for rule in rules:
                if (
                    cursor.weekday() != rule.weekday
                    or cursor < rule.valid_from
                    or (rule.valid_until and cursor > rule.valid_until)
                ):
                    continue
                try:
                    zone = ZoneInfo(rule.timezone)
                except ZoneInfoNotFoundError as error:
                    raise VavError(
                        "COUNSELING_TIMEZONE_INVALID",
                        "Mentor timezone is invalid.",
                        status_code=422,
                    ) from error
                local_start = datetime.combine(cursor, rule.local_start_time, tzinfo=zone)
                local_end = datetime.combine(cursor, rule.local_end_time, tzinfo=zone)
                slot = local_start
                while slot + timedelta(minutes=service.duration_minutes) <= local_end:
                    starts_at = slot.astimezone(UTC)
                    ends_at = (slot + timedelta(minutes=service.duration_minutes)).astimezone(UTC)
                    blocked = any(
                        item.override_type in {"blocked", "leave"}
                        and item.starts_at < ends_at
                        and item.ends_at > starts_at
                        for item in overrides
                    )
                    blocked = blocked or any(
                        item.scheduled_starts_at
                        and item.scheduled_ends_at
                        and item.scheduled_starts_at
                        - timedelta(minutes=service.buffer_before_minutes)
                        < ends_at
                        and item.scheduled_ends_at + timedelta(minutes=service.buffer_after_minutes)
                        > starts_at
                        for item in appointments
                    )
                    blocked = blocked or any(
                        item.starts_at < ends_at and item.ends_at > starts_at for item in holds
                    )
                    if (
                        not blocked
                        and starts_at >= now() + timedelta(minutes=service.min_notice_minutes)
                        and starts_at <= now() + timedelta(days=service.max_advance_days)
                    ):
                        result.append(
                            {
                                "starts_at": starts_at.isoformat(),
                                "ends_at": ends_at.isoformat(),
                                "mentor_timezone": rule.timezone,
                            }
                        )
                    slot += timedelta(minutes=service.duration_minutes)
            cursor += timedelta(days=1)
        return result

    async def hold(
        self,
        session: AsyncSession,
        *,
        mentor_id: UUID,
        service_id: UUID,
        user_id: UUID,
        starts_at: datetime,
        idempotency_key: str,
    ) -> CounselingSlotHold:
        await transaction_lock(session, f"counseling-slot:{mentor_id}:{starts_at.isoformat()}")
        existing = await session.scalar(
            select(CounselingSlotHold).where(CounselingSlotHold.idempotency_key == idempotency_key)
        )
        if existing:
            if existing.user_id != user_id:
                raise VavError(
                    "COUNSELING_HOLD_CONFLICT", "Hold key was already used.", status_code=409
                )
            return existing
        service = await session.get(CounselingServiceDefinition, service_id)
        if service is None:
            raise VavError(
                "COUNSELING_SERVICE_NOT_FOUND", "Service was not found.", status_code=404
            )
        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        overlap_hold = await session.scalar(
            select(CounselingSlotHold).where(
                CounselingSlotHold.mentor_id == mentor_id,
                CounselingSlotHold.status == "active",
                CounselingSlotHold.expires_at > now(),
                CounselingSlotHold.starts_at < ends_at,
                CounselingSlotHold.ends_at > starts_at,
            )
        )
        overlap_appointment = await session.scalar(
            select(CounselingAppointment).where(
                CounselingAppointment.mentor_id == mentor_id,
                CounselingAppointment.status.in_(("confirmed", "reschedule_requested")),
                CounselingAppointment.scheduled_starts_at < ends_at,
                CounselingAppointment.scheduled_ends_at > starts_at,
            )
        )
        if overlap_hold or overlap_appointment:
            raise VavError(
                "COUNSELING_SLOT_UNAVAILABLE", "The slot is no longer available.", status_code=409
            )
        values = await self.slots(
            session,
            mentor_id=mentor_id,
            service_id=service_id,
            start_date=starts_at.date(),
            end_date=starts_at.date(),
        )
        if starts_at.astimezone(UTC).isoformat() not in {item["starts_at"] for item in values}:
            raise VavError(
                "COUNSELING_SLOT_UNAVAILABLE", "The slot is not offered.", status_code=409
            )
        hold = CounselingSlotHold(
            mentor_id=mentor_id,
            service_id=service_id,
            user_id=user_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="active",
            idempotency_key=idempotency_key,
            expires_at=now() + timedelta(minutes=get_settings().counseling_slot_hold_ttl_minutes),
        )
        session.add(hold)
        await session.commit()
        await session.refresh(hold)
        return hold

    async def expire(self, session: AsyncSession) -> int:
        values = list(
            (
                await session.scalars(
                    select(CounselingSlotHold)
                    .where(
                        CounselingSlotHold.status == "active",
                        CounselingSlotHold.expires_at <= now(),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for item in values:
            item.status = "expired"
        await session.commit()
        return len(values)


class AppointmentService:
    async def project_entitlement(
        self, session: AsyncSession, entitlement: Entitlement
    ) -> CounselingAppointment | None:
        if str(entitlement.entitlement_type) != "counseling_credits":
            return None
        await transaction_lock(session, f"counseling-entitlement-projection:{entitlement.id}")
        criteria = [
            CounselingAppointment.user_id == entitlement.user_id,
            CounselingAppointment.status == "approved_pending_payment",
            CounselingAppointment.entitlement_id.is_(None),
        ]
        if entitlement.resource_id is not None:
            criteria.append(CounselingAppointment.service_id == entitlement.resource_id)
        appointment = await session.scalar(
            select(CounselingAppointment)
            .where(*criteria)
            .order_by(CounselingAppointment.created_at)
            .with_for_update()
        )
        if appointment is None:
            return None
        appointment.entitlement_id = entitlement.id
        appointment.credit_reservation_status = "reserved"
        appointment.payment_status = "paid"
        before = appointment.status
        appointment.status = "confirmed"
        appointment.version += 1
        session.add(
            CounselingAppointmentHistory(
                appointment_id=appointment.id,
                from_status=before,
                to_status="confirmed",
                actor_id=None,
                reason="Server-verified counseling entitlement activated.",
            )
        )
        session.add(
            OutboxEvent(
                topic="counseling.appointment.confirmed",
                aggregate_type="counseling_appointment",
                aggregate_id=str(appointment.id),
                payload={
                    "appointment_id": str(appointment.id),
                    "entitlement_id": str(entitlement.id),
                },
            )
        )
        return appointment

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        mentor_id: UUID | None,
        service_id: UUID,
        slot_hold_id: UUID | None,
        user_timezone: str,
        intake_schema_version: int,
        intake_response: dict[str, Any],
        idempotency_key: str,
    ) -> CounselingAppointment:
        await transaction_lock(session, f"counseling-request:{user_id}:{idempotency_key}")
        existing = await session.scalar(
            select(CounselingAppointment).where(
                CounselingAppointment.user_id == user_id,
                CounselingAppointment.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
        service = await session.get(CounselingServiceDefinition, service_id)
        if service is None or service.status != "published":
            raise VavError(
                "COUNSELING_SERVICE_NOT_FOUND", "Service was not found.", status_code=404
            )
        active_count = (
            await session.scalar(
                select(func.count(CounselingAppointment.id)).where(
                    CounselingAppointment.user_id == user_id,
                    CounselingAppointment.status.in_(
                        (
                            "pending_review",
                            "time_proposed",
                            "approved_pending_payment",
                            "confirmed",
                            "reschedule_requested",
                        )
                    ),
                )
            )
            or 0
        )
        if active_count >= get_settings().counseling_max_active_appointments_per_user:
            raise VavError(
                "COUNSELING_ACTIVE_APPOINTMENT_LIMIT",
                "The active appointment limit has been reached.",
                status_code=409,
            )
        hold = (
            await session.get(CounselingSlotHold, slot_hold_id, with_for_update=True)
            if slot_hold_id
            else None
        )
        if hold and (
            hold.user_id != user_id
            or hold.service_id != service_id
            or hold.status != "active"
            or hold.expires_at <= now()
        ):
            raise VavError("COUNSELING_HOLD_INVALID", "Slot hold is invalid.", status_code=409)
        assigned_mentor = hold.mentor_id if hold else mentor_id
        status = "pending_review"
        if service.booking_mode == "direct_booking" and hold:
            status = "confirmed" if service.payment_policy == "free" else "approved_pending_payment"
        entitlement_id = None
        reservation_status = None
        if service.payment_policy == "credit":
            entitlement = await session.scalar(
                select(Entitlement)
                .where(
                    Entitlement.user_id == user_id,
                    Entitlement.entitlement_type == "counseling_credits",
                    Entitlement.status == "active",
                    or_(Entitlement.resource_id.is_(None), Entitlement.resource_id == service_id),
                )
                .order_by(Entitlement.expires_at.asc().nullslast())
                .with_for_update()
            )
            if entitlement is None or entitlement.quantity_granted is None:
                raise VavError(
                    "COUNSELING_CREDIT_REQUIRED",
                    "An active counseling credit is required.",
                    status_code=409,
                )
            reserved = (
                await session.scalar(
                    select(func.count(CounselingAppointment.id)).where(
                        CounselingAppointment.entitlement_id == entitlement.id,
                        CounselingAppointment.credit_reservation_status == "reserved",
                    )
                )
                or 0
            )
            if entitlement.quantity_granted - entitlement.quantity_consumed - reserved < 1:
                raise VavError(
                    "COUNSELING_CREDIT_UNAVAILABLE",
                    "No counseling credit is available.",
                    status_code=409,
                )
            entitlement_id = entitlement.id
            reservation_status = "reserved"
            if service.booking_mode == "direct_booking" and hold:
                status = "confirmed"
        value = CounselingAppointment(
            appointment_number=appointment_number(),
            user_id=user_id,
            mentor_id=assigned_mentor,
            service_id=service_id,
            slot_hold_id=hold.id if hold else None,
            status=status,
            scheduled_starts_at=hold.starts_at if hold else None,
            scheduled_ends_at=hold.ends_at if hold else None,
            user_timezone=user_timezone,
            intake_schema_version=intake_schema_version,
            intake_response_encrypted=encrypt_sensitive(intake_response),
            payment_status="not_required"
            if service.payment_policy in {"free", "credit"}
            else "pending",
            entitlement_id=entitlement_id,
            credit_reservation_status=reservation_status,
            cancellation_policy_snapshot=service.cancellation_policy,
            no_show_policy_snapshot=service.no_show_policy,
            idempotency_key=idempotency_key,
        )
        session.add(value)
        await session.flush()
        if hold:
            hold.status = "converted"
        session.add(
            CounselingAppointmentHistory(
                appointment_id=value.id,
                from_status=None,
                to_status=status,
                actor_id=user_id,
                reason="Appointment requested.",
            )
        )
        session.add(
            OutboxEvent(
                topic="counseling.appointment.requested",
                aggregate_type="counseling_appointment",
                aggregate_id=str(value.id),
                payload={
                    "appointment_id": str(value.id),
                    "user_id": str(user_id),
                    "status": status,
                },
            )
        )
        await session.commit()
        await session.refresh(value)
        return value

    async def transition(
        self,
        session: AsyncSession,
        appointment: CounselingAppointment,
        *,
        target: str,
        actor_id: UUID,
        reason: str,
    ) -> None:
        await transaction_lock(session, f"counseling-appointment:{appointment.id}")
        locked_appointment = await session.scalar(
            select(CounselingAppointment)
            .where(CounselingAppointment.id == appointment.id)
            .with_for_update()
        )
        if locked_appointment is None:
            raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
        appointment = locked_appointment
        ensure_appointment_transition(appointment.status, target)
        before = appointment.status
        appointment.status = target
        appointment.version += 1
        if (
            target in {"cancelled", "rejected", "expired"}
            and appointment.credit_reservation_status == "reserved"
        ):
            appointment.credit_reservation_status = "released"
        session.add(
            CounselingAppointmentHistory(
                appointment_id=appointment.id,
                from_status=before,
                to_status=target,
                actor_id=actor_id,
                reason=reason,
            )
        )
        record_security_event(
            session,
            event_type=f"counseling.appointment.{target}",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="counseling_appointment",
            target_id=appointment.id,
            reason=reason,
        )
        await session.commit()

    async def complete(
        self,
        session: AsyncSession,
        appointment: CounselingAppointment,
        *,
        actor_id: UUID,
        idempotency_key: str,
    ) -> CounselingSession:
        await transaction_lock(session, f"counseling-complete:{appointment.id}")
        locked_appointment = await session.scalar(
            select(CounselingAppointment)
            .where(CounselingAppointment.id == appointment.id)
            .with_for_update()
        )
        if locked_appointment is None:
            raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
        appointment = locked_appointment
        session_record = await session.scalar(
            select(CounselingSession).where(CounselingSession.appointment_id == appointment.id)
        )
        if session_record and session_record.completion_key == idempotency_key:
            return session_record
        if appointment.status != "confirmed":
            raise VavError(
                "APPOINTMENT_NOT_CONFIRMABLE",
                "Only confirmed appointments can complete.",
                status_code=409,
            )
        if session_record is None:
            session_record = CounselingSession(
                appointment_id=appointment.id,
                status="scheduled",
                recording_enabled=False,
                transcription_enabled=False,
            )
            session.add(session_record)
            await session.flush()
        if appointment.entitlement_id and appointment.credit_reservation_status == "reserved":
            entitlement = await session.get(Entitlement, appointment.entitlement_id)
            if entitlement is None:
                raise VavError(
                    "COUNSELING_CREDIT_REQUIRED",
                    "Counseling credit is unavailable.",
                    status_code=409,
                )
            await entitlement_service.consume(
                session,
                entitlement_id=entitlement.id,
                user_id=appointment.user_id,
                quantity=1,
                expected_version=entitlement.version,
                idempotency_key=f"counseling:{appointment.id}:complete",
                commit=False,
            )
            appointment.credit_reservation_status = "consumed"
        appointment.status = "completed"
        session_record.status = "completed"
        session_record.completed_at = now()
        session_record.completion_key = idempotency_key
        await session.commit()
        return session_record


def appointment_payload(value: CounselingAppointment) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "appointment_number": value.appointment_number,
        "service_id": str(value.service_id),
        "mentor_id": str(value.mentor_id) if value.mentor_id else None,
        "status": value.status,
        "scheduled_starts_at": value.scheduled_starts_at.isoformat()
        if value.scheduled_starts_at
        else None,
        "scheduled_ends_at": value.scheduled_ends_at.isoformat()
        if value.scheduled_ends_at
        else None,
        "user_timezone": value.user_timezone,
        "payment_status": value.payment_status,
        "credit_reservation_status": value.credit_reservation_status,
        "proposal_version": value.proposal_version,
        "version": value.version,
    }


availability_service = AvailabilityService()
appointment_service = AppointmentService()
