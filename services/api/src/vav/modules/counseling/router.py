# ruff: noqa: B008
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.models.catalog import Product, ProductSku
from vav.models.counseling import (
    CounselingAppointment,
    CounselingAvailabilityRule,
    CounselingFollowUp,
    CounselingMentor,
    CounselingMentorLocalization,
    CounselingMentorService,
    CounselingRecord,
    CounselingSafetyReferral,
    CounselingServiceDefinition,
    CounselingServiceLocalization,
    CounselingSession,
)
from vav.models.identity import User
from vav.modules.counseling.schemas import (
    AppointmentRequest,
    AvailabilityRuleRequest,
    FollowUpCreateRequest,
    MentorCreateRequest,
    MentorLocalizationRequest,
    ProposalRequest,
    ReasonRequest,
    RecordCreateRequest,
    SafetyReferralRequest,
    ServiceCreateRequest,
    ServiceLocalizationRequest,
    SlotHoldRequest,
    TransitionRequest,
)
from vav.modules.counseling.service import (
    appointment_payload,
    appointment_service,
    availability_service,
    now,
    public_mentor_payload,
    public_service_payload,
    transaction_lock,
)
from vav.modules.courses.crypto import (
    decrypt_sensitive,
    encrypt_sensitive,
    issue_playback_token,
    verify_playback_token,
)
from vav.modules.identity.dependencies import (
    AuthenticatedPrincipal,
    require_admin_principal,
    require_authenticated_user,
)
from vav.modules.identity.permissions import require_permission

router = APIRouter()


@router.get("/public/counseling/mentors")
async def public_mentors(
    request: Request, locale: str = "zh-CN", session: AsyncSession = Depends(get_database_session)
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingMentor)
                .where(CounselingMentor.status == "active")
                .order_by(CounselingMentor.display_name)
            )
        ).all()
    )
    return success(
        {"items": [await public_mentor_payload(session, item, locale) for item in values]},
        request_id_from_request(request),
    )


@router.get("/public/counseling/mentors/{slug}")
async def public_mentor(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CounselingMentorLocalization).where(
            CounselingMentorLocalization.locale == locale, CounselingMentorLocalization.slug == slug
        )
    )
    mentor = await session.get(CounselingMentor, localization.mentor_id) if localization else None
    if mentor is None or mentor.status != "active":
        raise VavError("COUNSELING_MENTOR_NOT_FOUND", "Mentor was not found.", status_code=404)
    return success(
        await public_mentor_payload(session, mentor, locale), request_id_from_request(request)
    )


@router.get("/public/counseling/services")
async def public_services(
    request: Request, locale: str = "zh-CN", session: AsyncSession = Depends(get_database_session)
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingServiceDefinition)
                .where(CounselingServiceDefinition.status == "published")
                .order_by(CounselingServiceDefinition.internal_name)
            )
        ).all()
    )
    return success(
        {"items": [await public_service_payload(session, item, locale) for item in values]},
        request_id_from_request(request),
    )


@router.get("/public/counseling/services/{slug}")
async def public_service(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CounselingServiceLocalization).where(
            CounselingServiceLocalization.locale == locale,
            CounselingServiceLocalization.slug == slug,
        )
    )
    service = (
        await session.get(CounselingServiceDefinition, localization.service_id)
        if localization
        else None
    )
    if service is None or service.status != "published":
        raise VavError("COUNSELING_SERVICE_NOT_FOUND", "Service was not found.", status_code=404)
    return success(
        await public_service_payload(session, service, locale), request_id_from_request(request)
    )


@router.get("/public/counseling/availability")
async def public_availability(
    request: Request,
    mentor_id: UUID,
    service_id: UUID,
    start_date: date = Query(),
    end_date: date = Query(),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if end_date < start_date or (end_date - start_date).days > 31:
        raise VavError(
            "COUNSELING_DATE_RANGE_INVALID", "Availability range is invalid.", status_code=422
        )
    return success(
        {
            "items": await availability_service.slots(
                session,
                mentor_id=mentor_id,
                service_id=service_id,
                start_date=start_date,
                end_date=end_date,
            )
        },
        request_id_from_request(request),
    )


@router.post("/account/counseling/slot-holds", status_code=201)
async def create_hold(
    payload: SlotHoldRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await availability_service.hold(
        session,
        mentor_id=payload.mentor_id,
        service_id=payload.service_id,
        user_id=principal.user.id,
        starts_at=payload.starts_at,
        idempotency_key=payload.idempotency_key,
    )
    return success(
        {"id": str(value.id), "status": value.status, "expires_at": value.expires_at.isoformat()},
        request_id_from_request(request),
    )


@router.post("/account/counseling/appointments", status_code=201)
async def create_appointment(
    payload: AppointmentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await appointment_service.create(
        session, user_id=principal.user.id, **payload.model_dump()
    )
    return success(appointment_payload(value), request_id_from_request(request))


@router.get("/account/counseling/appointments")
async def own_appointments(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingAppointment)
                .where(CounselingAppointment.user_id == principal.user.id)
                .order_by(CounselingAppointment.created_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [appointment_payload(item) for item in values]}, request_id_from_request(request)
    )


async def own_appointment(
    session: AsyncSession, appointment_id: UUID, user_id: UUID
) -> CounselingAppointment:
    value = await session.get(CounselingAppointment, appointment_id)
    if value is None or value.user_id != user_id:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    return value


@router.get("/account/counseling/appointments/{appointment_id}")
async def own_appointment_detail(
    appointment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await own_appointment(session, appointment_id, principal.user.id)
    result = appointment_payload(value)
    session_record = await session.scalar(
        select(CounselingSession).where(CounselingSession.appointment_id == value.id)
    )
    summaries = (
        list(
            (
                await session.scalars(
                    select(CounselingRecord).where(
                        CounselingRecord.session_id == session_record.id,
                        CounselingRecord.record_type == "client_summary",
                        CounselingRecord.status == "published",
                    )
                )
            ).all()
        )
        if session_record
        else []
    )
    result["summaries"] = [
        {
            "id": str(item.id),
            "version": item.version,
            "content": decrypt_sensitive(item.content_encrypted),
        }
        for item in summaries
    ]
    followups = list(
        (
            await session.scalars(
                select(CounselingFollowUp).where(
                    CounselingFollowUp.appointment_id == value.id,
                    CounselingFollowUp.user_id == principal.user.id,
                )
            )
        ).all()
    )
    result["follow_ups"] = [
        {
            "id": str(item.id),
            "type": item.follow_up_type,
            "status": item.status,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "content": decrypt_sensitive(item.content_encrypted),
        }
        for item in followups
    ]
    return success(result, request_id_from_request(request))


@router.post("/account/counseling/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await own_appointment(session, appointment_id, principal.user.id)
    await appointment_service.transition(
        session, value, target="cancelled", actor_id=principal.user.id, reason=payload.reason
    )
    return success(appointment_payload(value), request_id_from_request(request))


@router.post("/account/counseling/appointments/{appointment_id}/accept-proposal")
async def accept_proposal(
    appointment_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await own_appointment(session, appointment_id, principal.user.id)
    service = await session.get(CounselingServiceDefinition, value.service_id)
    target = (
        "approved_pending_payment"
        if service and service.payment_policy not in {"free", "credit"}
        else "confirmed"
    )
    await appointment_service.transition(
        session, value, target=target, actor_id=principal.user.id, reason=payload.reason
    )
    return success(appointment_payload(value), request_id_from_request(request))


@router.post("/account/counseling/appointments/{appointment_id}/join")
async def join_session(
    appointment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    appointment = await own_appointment(session, appointment_id, principal.user.id)
    if (
        appointment.status != "confirmed"
        or appointment.scheduled_starts_at is None
        or appointment.scheduled_ends_at is None
    ):
        raise VavError(
            "COUNSELING_SESSION_NOT_JOINABLE", "Session is not joinable.", status_code=409
        )
    current = now()
    settings = get_settings()
    if current < appointment.scheduled_starts_at - timedelta(
        minutes=settings.counseling_join_open_minutes_before
    ) or current > appointment.scheduled_ends_at + timedelta(
        minutes=settings.counseling_join_close_minutes_after
    ):
        raise VavError(
            "COUNSELING_JOIN_WINDOW_CLOSED", "Session join window is closed.", status_code=403
        )
    value = await session.scalar(
        select(CounselingSession).where(CounselingSession.appointment_id == appointment.id)
    )
    if value is None:
        value = CounselingSession(
            appointment_id=appointment.id,
            status="checkin_open",
            recording_enabled=False,
            transcription_enabled=False,
        )
        session.add(value)
        await session.commit()
        await session.refresh(value)
    token = issue_playback_token(
        f"counseling:{value.id}:{principal.user.id}",
        expires_at=int(
            (
                current + timedelta(seconds=settings.counseling_meeting_join_url_ttl_seconds)
            ).timestamp()
        ),
    )
    return success(
        {
            "session_id": str(value.id),
            "join_token": token,
            "expires_at": (
                current + timedelta(seconds=settings.counseling_meeting_join_url_ttl_seconds)
            ).isoformat(),
            "recording_enabled": False,
            "transcription_enabled": False,
        },
        request_id_from_request(request),
    )


@router.get("/account/counseling/session-access/{session_id}")
async def session_access(
    session_id: UUID,
    token: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CounselingSession, session_id)
    appointment = (
        await session.get(CounselingAppointment, value.appointment_id)
        if value is not None
        else None
    )
    if value is None or appointment is None or appointment.user_id != principal.user.id:
        raise VavError("COUNSELING_SESSION_NOT_FOUND", "Session was not found.", status_code=404)
    verify_playback_token(token, session_id=f"counseling:{value.id}:{principal.user.id}")
    return success(
        {
            "session_id": str(value.id),
            "meeting_url": f"https://sessions.invalid/counseling/{value.id}",
            "expires_with_token": True,
            "recording_enabled": False,
            "transcription_enabled": False,
        },
        request_id_from_request(request),
    )


@router.get("/admin/counseling/mentors")
async def admin_mentors(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.mentors.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingMentor).order_by(CounselingMentor.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "mentor_code": item.mentor_code,
                    "display_name": item.display_name,
                    "status": item.status,
                    "timezone": item.timezone,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/counseling/mentors", status_code=201)
async def create_mentor(
    payload: MentorCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("counseling.mentors.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.linked_user_id and await session.get(User, payload.linked_user_id) is None:
        raise VavError("USER_NOT_FOUND", "User was not found.", status_code=404)
    value = CounselingMentor(**payload.model_dump(), status="draft", created_by=principal.user.id)
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.put("/admin/counseling/mentors/{mentor_id}/localizations/{locale}")
async def localize_mentor(
    mentor_id: UUID,
    locale: str,
    payload: MentorLocalizationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.mentors.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(CounselingMentor, mentor_id) is None:
        raise VavError("COUNSELING_MENTOR_NOT_FOUND", "Mentor was not found.", status_code=404)
    value = await session.scalar(
        select(CounselingMentorLocalization).where(
            CounselingMentorLocalization.mentor_id == mentor_id,
            CounselingMentorLocalization.locale == locale,
        )
    )
    if value is None:
        value = CounselingMentorLocalization(
            mentor_id=mentor_id, locale=locale, **payload.model_dump()
        )
        session.add(value)
    else:
        for key, item in payload.model_dump().items():
            setattr(value, key, item)
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.get("/admin/counseling/services")
async def admin_services(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.services.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingServiceDefinition).order_by(
                    CounselingServiceDefinition.created_at.desc()
                )
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "service_code": item.service_code,
                    "internal_name": item.internal_name,
                    "status": item.status,
                    "booking_mode": item.booking_mode,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/counseling/services", status_code=201)
async def create_service(
    payload: ServiceCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("counseling.services.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if not payload.free_access:
        sku = (
            await session.get(ProductSku, payload.catalog_sku_id)
            if payload.catalog_sku_id
            else None
        )
        product = await session.get(Product, sku.product_id) if sku else None
        if (
            sku is None
            or sku.status != "active"
            or product is None
            or product.product_type not in {"counseling_session", "counseling_package"}
            or product.fulfillment_type != "appointment_credits"
        ):
            raise VavError(
                "COUNSELING_CATALOG_MAPPING_INVALID",
                "Paid services require an active counseling Catalog SKU.",
                status_code=422,
            )
    value = CounselingServiceDefinition(
        **payload.model_dump(),
        status="draft",
        cancellation_policy={"mode": "manual_review"},
        no_show_policy={"consume_credit": False, "mode": "manual_review"},
        scope_policy={"therapy": False, "medical": False, "legal": False, "emergency": False},
        created_by=principal.user.id,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.put("/admin/counseling/services/{service_id}/localizations/{locale}")
async def localize_service(
    service_id: UUID,
    locale: str,
    payload: ServiceLocalizationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.services.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(CounselingServiceDefinition, service_id) is None:
        raise VavError("COUNSELING_SERVICE_NOT_FOUND", "Service was not found.", status_code=404)
    value = await session.scalar(
        select(CounselingServiceLocalization).where(
            CounselingServiceLocalization.service_id == service_id,
            CounselingServiceLocalization.locale == locale,
        )
    )
    if value is None:
        value = CounselingServiceLocalization(
            service_id=service_id, locale=locale, **payload.model_dump()
        )
        session.add(value)
    else:
        for key, item in payload.model_dump().items():
            setattr(value, key, item)
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/counseling/services/{service_id}/mentors/{mentor_id}")
async def link_mentor_service(
    service_id: UUID,
    mentor_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.services.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if (
        await session.get(CounselingMentor, mentor_id) is None
        or await session.get(CounselingServiceDefinition, service_id) is None
    ):
        raise VavError(
            "COUNSELING_MAPPING_NOT_FOUND", "Mentor or service was not found.", status_code=404
        )
    value = await session.scalar(
        select(CounselingMentorService).where(
            CounselingMentorService.mentor_id == mentor_id,
            CounselingMentorService.service_id == service_id,
        )
    )
    if value is None:
        value = CounselingMentorService(mentor_id=mentor_id, service_id=service_id, status="active")
        session.add(value)
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/counseling/mentors/{mentor_id}/activate")
async def activate_mentor(
    mentor_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.mentors.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CounselingMentor, mentor_id)
    localization = await session.scalar(
        select(CounselingMentorLocalization).where(
            CounselingMentorLocalization.mentor_id == mentor_id,
            CounselingMentorLocalization.translation_status == "ready",
        )
    )
    if value is None or localization is None:
        raise VavError(
            "COUNSELING_MENTOR_NOT_READY",
            "An approved localization is required before activation.",
            status_code=409,
        )
    value.status = "active"
    value.version += 1
    await session.commit()
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.post("/admin/counseling/services/{service_id}/publish")
async def publish_service(
    service_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.services.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CounselingServiceDefinition, service_id)
    localization = await session.scalar(
        select(CounselingServiceLocalization).where(
            CounselingServiceLocalization.service_id == service_id,
            CounselingServiceLocalization.translation_status == "ready",
        )
    )
    link = await session.scalar(
        select(CounselingMentorService).where(
            CounselingMentorService.service_id == service_id,
            CounselingMentorService.status == "active",
        )
    )
    if value is None or localization is None or link is None:
        raise VavError(
            "COUNSELING_SERVICE_NOT_READY",
            "A ready localization and active mentor are required before publishing.",
            status_code=409,
        )
    value.status = "published"
    value.version += 1
    await session.commit()
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.post("/admin/counseling/availability-rules", status_code=201)
async def create_rule(
    payload: AvailabilityRuleRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.schedules.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = CounselingAvailabilityRule(**payload.model_dump(), status="active")
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.get("/admin/counseling/appointments")
async def admin_appointments(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("counseling.appointments.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CounselingAppointment).order_by(CounselingAppointment.created_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [appointment_payload(item) for item in values]}, request_id_from_request(request)
    )


@router.post("/admin/counseling/appointments/{appointment_id}/transition")
async def admin_transition(
    appointment_id: UUID,
    payload: TransitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("counseling.appointments.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CounselingAppointment, appointment_id)
    if value is None:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    await appointment_service.transition(
        session,
        value,
        target=payload.target_status,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(appointment_payload(value), request_id_from_request(request))


@router.post("/admin/counseling/appointments/{appointment_id}/propose-time")
async def propose_time(
    appointment_id: UUID,
    payload: ProposalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("counseling.appointments.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await transaction_lock(session, f"counseling-proposal:{appointment_id}")
    value = await session.scalar(
        select(CounselingAppointment)
        .where(CounselingAppointment.id == appointment_id)
        .with_for_update()
    )
    if value is None:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    if value.proposal_version != payload.expected_proposal_version:
        raise VavError(
            "COUNSELING_PROPOSAL_STALE", "A newer time proposal exists.", status_code=409
        )
    service = await session.get(CounselingServiceDefinition, value.service_id)
    assert service is not None
    hold = await availability_service.hold(
        session,
        mentor_id=payload.mentor_id,
        service_id=value.service_id,
        user_id=value.user_id,
        starts_at=payload.starts_at,
        idempotency_key=f"proposal:{value.id}:{value.proposal_version + 1}",
    )
    value.mentor_id = payload.mentor_id
    value.slot_hold_id = hold.id
    value.scheduled_starts_at = hold.starts_at
    value.scheduled_ends_at = hold.ends_at
    value.proposal_version += 1
    if value.status == "pending_review":
        await appointment_service.transition(
            session,
            value,
            target="time_proposed",
            actor_id=principal.user.id,
            reason=payload.reason,
        )
    else:
        await session.commit()
    return success(appointment_payload(value), request_id_from_request(request))


@router.post("/admin/counseling/appointments/{appointment_id}/complete")
async def complete_appointment(
    appointment_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("counseling.sessions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CounselingAppointment, appointment_id)
    if value is None:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    completed = await appointment_service.complete(
        session, value, actor_id=principal.user.id, idempotency_key=payload.reason
    )
    return success(
        {"session_id": str(completed.id), "status": completed.status},
        request_id_from_request(request),
    )


@router.post("/admin/counseling/sessions/{session_id}/records", status_code=201)
async def create_record(
    session_id: UUID,
    payload: RecordCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission = (
        "counseling.records.private"
        if payload.record_type == "mentor_note"
        else "counseling.records.manage"
    )
    principal.require(permission)
    if await session.get(CounselingSession, session_id) is None:
        raise VavError("COUNSELING_SESSION_NOT_FOUND", "Session was not found.", status_code=404)
    version = (
        await session.scalar(
            select(func.max(CounselingRecord.version)).where(
                CounselingRecord.session_id == session_id,
                CounselingRecord.record_type == payload.record_type,
            )
        )
    ) or 0
    value = CounselingRecord(
        session_id=session_id,
        record_type=payload.record_type,
        visibility="client" if payload.record_type == "client_summary" else "mentor_private",
        version=version + 1,
        status="published"
        if payload.publish and payload.record_type == "client_summary"
        else "draft",
        content_encrypted=encrypt_sensitive(payload.content),
        created_by=principal.user.id,
        published_at=now() if payload.publish and payload.record_type == "client_summary" else None,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success(
        {"id": str(value.id), "version": value.version, "status": value.status},
        request_id_from_request(request),
    )


@router.post("/admin/counseling/appointments/{appointment_id}/follow-ups", status_code=201)
async def create_followup(
    appointment_id: UUID,
    payload: FollowUpCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("counseling.followups.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    appointment = await session.get(CounselingAppointment, appointment_id)
    if appointment is None:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    value = CounselingFollowUp(
        appointment_id=appointment.id,
        user_id=appointment.user_id,
        assigned_to=principal.user.id,
        follow_up_type=payload.follow_up_type,
        status="open",
        due_at=payload.due_at,
        content_encrypted=encrypt_sensitive(payload.content),
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/counseling/appointments/{appointment_id}/safety-referrals", status_code=201)
async def create_safety_referral(
    appointment_id: UUID,
    payload: SafetyReferralRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("counseling.safety.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(CounselingAppointment, appointment_id) is None:
        raise VavError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", status_code=404)
    value = CounselingSafetyReferral(
        appointment_id=appointment_id,
        risk_level=payload.risk_level,
        category=payload.category,
        details_encrypted=encrypt_sensitive(payload.details),
        status="open",
        created_by=principal.user.id,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success(
        {"id": str(value.id), "risk_level": value.risk_level, "emergency_service": False},
        request_id_from_request(request),
    )
