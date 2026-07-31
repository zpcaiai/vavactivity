# ruff: noqa: B008

from __future__ import annotations

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
from vav.models.activities import (
    Activity,
    ActivityGroup,
    ActivityGroupingPlan,
    ActivityGroupMember,
    ActivityInteractionRestriction,
    ActivityLocalization,
    ActivityLocation,
    ActivityMutualChoice,
    ActivityParticipantProfile,
    ActivityPostEventChoice,
    ActivityRegistration,
    ActivityRegistrationForm,
    ActivitySession,
    ActivityTicketType,
    ActivityWaitlistEntry,
)
from vav.models.catalog import Product, ProductSku
from vav.models.identity import SecurityAuditEvent
from vav.modules.activities.crypto import decrypt_private, encrypt_private
from vav.modules.activities.domain import ActivityStatus, canonical_user_pair, validate_form_schema
from vav.modules.activities.schemas import (
    ActivityCancelRequest,
    ActivityCreateRequest,
    ActivityTransitionRequest,
    ActivityUpdateRequest,
    CheckinRequest,
    FormUpsertRequest,
    GroupingRequest,
    GroupingStatusRequest,
    GroupMemberMoveRequest,
    LocalizationUpsertRequest,
    LocationCreateRequest,
    ParticipantProfileRequest,
    PostEventChoiceRequest,
    ReasonRequest,
    RegistrationCreateRequest,
    RestrictionRequest,
    ReviewRequest,
    SessionCreateRequest,
    TicketLinkRequest,
    WaitlistReorderRequest,
)
from vav.modules.activities.service import (
    attendance_service,
    grouping_service,
    localized_activity_payload,
    mutual_choice_service,
    publication_service,
    registration_payload,
    registration_service,
    waitlist_payload,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.identity.permissions import require_permission

router = APIRouter()


async def activity_or_404(session: AsyncSession, activity_id: UUID) -> Activity:
    activity = await session.get(Activity, activity_id)
    if activity is None:
        raise VavError("ACTIVITY_NOT_FOUND", "Activity was not found.", status_code=404)
    return activity


async def own_registration(
    session: AsyncSession, activity_id: UUID, principal: AuthenticatedPrincipal
) -> ActivityRegistration:
    registration = await session.scalar(
        select(ActivityRegistration).where(
            ActivityRegistration.activity_id == activity_id,
            ActivityRegistration.user_id == principal.user.id,
        )
    )
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    return registration


async def own_registration_by_id(
    session: AsyncSession, registration_id: UUID, principal: AuthenticatedPrincipal
) -> ActivityRegistration:
    registration = await session.scalar(
        select(ActivityRegistration).where(
            ActivityRegistration.id == registration_id,
            ActivityRegistration.user_id == principal.user.id,
        )
    )
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    return registration


@router.get("/activities")
async def list_public_activities(
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activities = list(
        (
            await session.scalars(
                select(Activity)
                .where(
                    Activity.visibility == "public",
                    Activity.status.in_(
                        (
                            ActivityStatus.PUBLISHED,
                            ActivityStatus.REGISTRATION_OPEN,
                            ActivityStatus.REGISTRATION_CLOSED,
                            ActivityStatus.IN_PROGRESS,
                            ActivityStatus.COMPLETED,
                        )
                    ),
                )
                .order_by(Activity.starts_at, Activity.id)
            )
        ).all()
    )
    data = [
        await localized_activity_payload(session, activity, locale=locale)
        for activity in activities
    ]
    return success({"items": data}, request_id_from_request(request))


@router.get("/activities/{slug}")
async def public_activity_detail(
    slug: str,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    localization = await session.scalar(
        select(ActivityLocalization).where(
            ActivityLocalization.locale == locale,
            ActivityLocalization.slug == slug,
        )
    )
    activity = await session.get(Activity, localization.activity_id) if localization else None
    if (
        activity is None
        or activity.visibility != "public"
        or activity.status
        not in {
            ActivityStatus.PUBLISHED,
            ActivityStatus.REGISTRATION_OPEN,
            ActivityStatus.REGISTRATION_CLOSED,
            ActivityStatus.IN_PROGRESS,
            ActivityStatus.COMPLETED,
        }
    ):
        raise VavError("ACTIVITY_NOT_FOUND", "Activity was not found.", status_code=404)
    return success(
        await localized_activity_payload(session, activity, locale=locale),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/ticket-types")
async def public_activity_ticket_types(
    activity_id: UUID,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    if activity.visibility != "public" or activity.status not in {
        ActivityStatus.PUBLISHED,
        ActivityStatus.REGISTRATION_OPEN,
        ActivityStatus.REGISTRATION_CLOSED,
        ActivityStatus.IN_PROGRESS,
        ActivityStatus.COMPLETED,
    }:
        raise VavError("ACTIVITY_NOT_FOUND", "Activity was not found.", status_code=404)
    value = await localized_activity_payload(session, activity, locale=locale)
    return success({"items": value["ticket_types"]}, request_id_from_request(request))


@router.post("/activities/{activity_id}/registrations", status_code=201)
async def register_for_activity(
    activity_id: UUID,
    payload: RegistrationCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    registration = await registration_service.create(
        session, activity=activity, user=principal.user, request=payload
    )
    return success(registration_payload(registration), request_id_from_request(request))


@router.get("/account/activity-registrations")
async def my_activity_registrations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    items = list(
        (
            await session.scalars(
                select(ActivityRegistration)
                .where(ActivityRegistration.user_id == principal.user.id)
                .order_by(ActivityRegistration.created_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [registration_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.get("/account/activity-registrations/{registration_id}")
async def my_activity_registration(
    registration_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration_by_id(session, registration_id, principal)
    return success(registration_payload(registration), request_id_from_request(request))


@router.post("/account/activity-registrations/{registration_id}/cancel")
async def cancel_my_activity_registration(
    registration_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration_by_id(session, registration_id, principal)
    value = await registration_service.cancel(
        session,
        registration,
        actor_type="user",
        actor_id=principal.user.id,
        reason_code=payload.reason_code,
        reason=payload.reason,
    )
    return success(registration_payload(value), request_id_from_request(request))


@router.get("/account/activity-waitlist")
async def my_activity_waitlist(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    items = list(
        (
            await session.scalars(
                select(ActivityWaitlistEntry)
                .where(ActivityWaitlistEntry.user_id == principal.user.id)
                .order_by(ActivityWaitlistEntry.joined_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [waitlist_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.post("/account/activity-waitlist/{entry_id}/accept")
async def accept_activity_waitlist_entry(
    entry_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.scalar(
        select(ActivityWaitlistEntry).where(
            ActivityWaitlistEntry.id == entry_id,
            ActivityWaitlistEntry.user_id == principal.user.id,
        )
    )
    if entry is None:
        raise VavError("WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry was not found.", status_code=404)
    registration = await session.get(ActivityRegistration, entry.registration_id)
    activity = await session.get(Activity, entry.activity_id)
    if registration is None or activity is None:
        raise VavError("WAITLIST_CONTEXT_INVALID", "Waitlist context is invalid.", status_code=409)
    value = await registration_service.accept_waitlist_offer(
        session, activity=activity, registration=registration, user=principal.user
    )
    return success(registration_payload(value), request_id_from_request(request))


@router.post("/account/activity-waitlist/{entry_id}/decline")
async def decline_activity_waitlist_entry(
    entry_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.scalar(
        select(ActivityWaitlistEntry).where(
            ActivityWaitlistEntry.id == entry_id,
            ActivityWaitlistEntry.user_id == principal.user.id,
        )
    )
    if entry is None:
        raise VavError("WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry was not found.", status_code=404)
    value = await registration_service.decline_waitlist_offer(
        session, entry, actor_id=principal.user.id, reason=payload.reason
    )
    return success(waitlist_payload(value), request_id_from_request(request))


@router.post("/account/activity-registrations/{activity_id}/accept-waitlist-offer")
async def accept_waitlist_offer(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    activity = await activity_or_404(session, activity_id)
    value = await registration_service.accept_waitlist_offer(
        session,
        activity=activity,
        registration=registration,
        user=principal.user,
    )
    return success(registration_payload(value), request_id_from_request(request))


@router.get("/account/activity-registrations/{activity_id}/access")
async def confirmed_activity_access(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    if registration.status != "confirmed":
        raise VavError(
            "ACTIVITY_ACCESS_NOT_ACTIVE", "Confirmed registration is required.", status_code=403
        )
    activity = await activity_or_404(session, activity_id)
    return success(
        await localized_activity_payload(
            session,
            activity,
            locale=principal.user.preferred_locale,
            include_private_location=True,
        ),
        request_id_from_request(request),
    )


@router.post("/account/activity-registrations/{activity_id}/checkin-credential")
async def get_checkin_credential(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    credential, token = await attendance_service.credential(session, registration)
    return success(
        {
            "token": token,
            "valid_from": credential.valid_from.isoformat(),
            "valid_until": credential.valid_until.isoformat(),
        },
        request_id_from_request(request),
    )


@router.put("/account/activities/{activity_id}/participant-profile")
async def upsert_participant_profile(
    activity_id: UUID,
    payload: ParticipantProfileRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    profile = await mutual_choice_service.upsert_profile(
        session,
        registration,
        display_name=payload.display_name,
        introduction=payload.brief_introduction,
        visibility=payload.visibility_status,
        consent=payload.consent,
    )
    return success(
        {
            "id": str(profile.id),
            "display_name": profile.display_name,
            "brief_introduction": profile.brief_introduction,
            "visibility_status": profile.visibility_status,
        },
        request_id_from_request(request),
    )


@router.get("/account/activities/{activity_id}/participants")
async def eligible_participants(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    activity = await activity_or_404(session, activity_id)
    profiles = await mutual_choice_service.directory(
        session, activity=activity, viewer=registration
    )
    return success(
        {
            "items": [
                {
                    "user_id": str(profile.user_id),
                    "display_name": profile.display_name,
                    "brief_introduction": profile.brief_introduction,
                }
                for profile in profiles
            ]
        },
        request_id_from_request(request),
    )


@router.get("/account/activities/{activity_id}/choices")
async def my_post_event_choices(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    activity = await activity_or_404(session, activity_id)
    await mutual_choice_service.ensure_eligible(session, activity, registration)
    items = list(
        (
            await session.scalars(
                select(ActivityPostEventChoice).where(
                    ActivityPostEventChoice.activity_id == activity_id,
                    ActivityPostEventChoice.chooser_user_id == principal.user.id,
                    ActivityPostEventChoice.status == "active",
                )
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "chosen_user_id": str(item.chosen_user_id),
                    "choice": item.choice,
                    "submitted_at": item.submitted_at.isoformat(),
                }
                for item in items
            ]
        },
        request_id_from_request(request),
    )


@router.put("/account/activities/{activity_id}/choices")
async def submit_post_event_choice(
    activity_id: UUID,
    payload: PostEventChoiceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    activity = await activity_or_404(session, activity_id)
    choice = await mutual_choice_service.choose(
        session,
        activity=activity,
        chooser=registration,
        chosen_user_id=payload.chosen_user_id,
        choice_value=payload.choice,
    )
    # One-sided state is intentionally exposed only to the chooser.
    return success(
        {"chosen_user_id": str(choice.chosen_user_id), "choice": choice.choice},
        request_id_from_request(request),
    )


@router.delete("/account/activities/{activity_id}/choices/{participant_id}")
async def withdraw_post_event_choice(
    activity_id: UUID,
    participant_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    activity = await activity_or_404(session, activity_id)
    await mutual_choice_service.withdraw(
        session,
        activity=activity,
        chooser=registration,
        chosen_user_id=participant_id,
    )
    return success({"status": "withdrawn"}, request_id_from_request(request))


@router.get("/account/activity-mutual-choices")
async def my_activity_mutual_choices(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    items = list(
        (
            await session.scalars(
                select(ActivityMutualChoice).where(
                    (ActivityMutualChoice.user_a_id == principal.user.id)
                    | (ActivityMutualChoice.user_b_id == principal.user.id),
                    ActivityMutualChoice.status == "matched_private",
                )
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "activity_id": str(item.activity_id),
                    "participant_user_id": str(
                        item.user_b_id if item.user_a_id == principal.user.id else item.user_a_id
                    ),
                    "status": item.status,
                    "matched_at": item.matched_at.isoformat(),
                    "contact_disclosed": False,
                    "introduction_invitation_id": (
                        str(item.introduction_invitation_id)
                        if item.introduction_invitation_id
                        else None
                    ),
                }
                for item in items
            ]
        },
        request_id_from_request(request),
    )


@router.get("/account/activities/{activity_id}/group")
async def my_activity_group(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await own_registration(session, activity_id, principal)
    row = (
        await session.execute(
            select(ActivityGroupMember, ActivityGroup, ActivityGroupingPlan)
            .join(ActivityGroup, ActivityGroup.id == ActivityGroupMember.group_id)
            .join(
                ActivityGroupingPlan,
                ActivityGroupingPlan.id == ActivityGroupMember.grouping_plan_id,
            )
            .where(
                ActivityGroupMember.registration_id == registration.id,
                ActivityGroupMember.removed_at.is_(None),
                ActivityGroupingPlan.activity_id == activity_id,
                ActivityGroupingPlan.status.in_(("published", "locked")),
            )
            .order_by(ActivityGroupingPlan.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise VavError("ACTIVITY_GROUP_NOT_AVAILABLE", "Group is not available.", status_code=404)
    _, group, plan = row
    members = list(
        (
            await session.scalars(
                select(ActivityParticipantProfile)
                .join(
                    ActivityGroupMember,
                    ActivityGroupMember.registration_id
                    == ActivityParticipantProfile.registration_id,
                )
                .where(
                    ActivityGroupMember.group_id == group.id,
                    ActivityGroupMember.removed_at.is_(None),
                    ActivityParticipantProfile.visibility_status == "visible",
                )
            )
        ).all()
    )
    return success(
        {
            "plan_id": str(plan.id),
            "group_id": str(group.id),
            "group_code": group.group_code,
            "display_name": group.display_name,
            "members": [
                {
                    "display_name": member.display_name,
                    "brief_introduction": member.brief_introduction,
                }
                for member in members
            ],
        },
        request_id_from_request(request),
    )


@router.post("/account/activity-interaction-restrictions", status_code=201)
async def create_interaction_restriction(
    payload: RestrictionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    first, second = canonical_user_pair(principal.user.id, payload.target_user_id)
    restriction = await session.scalar(
        select(ActivityInteractionRestriction).where(
            ActivityInteractionRestriction.user_a_id == first,
            ActivityInteractionRestriction.user_b_id == second,
        )
    )
    if restriction is None:
        restriction = ActivityInteractionRestriction(
            user_a_id=first,
            user_b_id=second,
            status="active",
            reason_code=payload.reason_code,
        )
        session.add(restriction)
    else:
        restriction.status = "active"
        restriction.reason_code = payload.reason_code
    matches = list(
        (
            await session.scalars(
                select(ActivityMutualChoice).where(
                    ActivityMutualChoice.user_a_id == first,
                    ActivityMutualChoice.user_b_id == second,
                    ActivityMutualChoice.status == "matched_private",
                )
            )
        ).all()
    )
    for match in matches:
        match.status = "suspended"
    await session.commit()
    return success({"status": "active"}, request_id_from_request(request))


@router.get("/admin/activities")
async def admin_list_activities(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    items = list(
        (await session.scalars(select(Activity).order_by(Activity.created_at.desc()))).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "activity_code": item.activity_code,
                    "internal_name": item.internal_name,
                    "status": item.status,
                    "starts_at": item.starts_at.isoformat(),
                    "version": item.version,
                }
                for item in items
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/activities", status_code=201)
async def admin_create_activity(
    payload: ActivityCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = Activity(
        **payload.model_dump(),
        status=ActivityStatus.DRAFT,
        visibility="public",
        created_by=principal.user.id,
        updated_by=principal.user.id,
        cancellation_policy_snapshot={
            "status": "configuration_required",
            "default": "manual_review",
        },
    )
    session.add(activity)
    await session.commit()
    return success(
        {"id": str(activity.id), "status": activity.status}, request_id_from_request(request)
    )


@router.get("/admin/activities/{activity_id}")
async def admin_activity_detail(
    activity_id: UUID,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    activity = await activity_or_404(session, activity_id)
    value = await localized_activity_payload(
        session, activity, locale=locale, include_private_location=True
    )
    value.update(
        {
            "internal_name": activity.internal_name,
            "visibility": activity.visibility,
            "approval_policy": activity.approval_policy,
            "payment_timing_policy": activity.payment_timing_policy,
            "waitlist_enabled": activity.waitlist_enabled,
            "post_event_choice_opens_at": (
                activity.post_event_choice_opens_at.isoformat()
                if activity.post_event_choice_opens_at
                else None
            ),
            "post_event_choice_closes_at": (
                activity.post_event_choice_closes_at.isoformat()
                if activity.post_event_choice_closes_at
                else None
            ),
            "version": activity.version,
        }
    )
    return success(value, request_id_from_request(request))


@router.patch("/admin/activities/{activity_id}")
async def admin_update_activity(
    activity_id: UUID,
    payload: ActivityUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    if activity.version != payload.expected_version:
        raise VavError(
            "ACTIVITY_VERSION_CONFLICT",
            "Activity changed since it was loaded.",
            status_code=409,
        )
    if activity.status in {
        ActivityStatus.COMPLETED,
        ActivityStatus.CANCELLED,
        ActivityStatus.ARCHIVED,
    }:
        raise VavError(
            "ACTIVITY_NOT_EDITABLE", "This activity can no longer be edited.", status_code=409
        )
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    for key, value in changes.items():
        setattr(activity, key, value)
    if activity.ends_at <= activity.starts_at:
        raise VavError(
            "ACTIVITY_WINDOW_INVALID", "Activity time window is invalid.", status_code=422
        )
    if activity.registration_closes_at and activity.registration_closes_at > activity.starts_at:
        raise VavError(
            "REGISTRATION_WINDOW_INVALID",
            "Registration must close before the activity.",
            status_code=422,
        )
    activity.updated_by = principal.user.id
    activity.version += 1
    await session.commit()
    return success(
        {"id": str(activity.id), "status": activity.status, "version": activity.version},
        request_id_from_request(request),
    )


@router.put("/admin/activities/{activity_id}/localizations/{locale}")
async def admin_upsert_localization(
    activity_id: UUID,
    locale: str,
    payload: LocalizationUpsertRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    if locale != payload.locale:
        raise VavError("LOCALE_MISMATCH", "Path and body locales must match.", status_code=422)
    value = await session.scalar(
        select(ActivityLocalization).where(
            ActivityLocalization.activity_id == activity.id,
            ActivityLocalization.locale == locale,
        )
    )
    values = payload.model_dump()
    if value is None:
        value = ActivityLocalization(activity_id=activity.id, **values)
        session.add(value)
    else:
        for key, item in values.items():
            setattr(value, key, item)
    activity.updated_by = principal.user.id
    activity.version += 1
    await session.commit()
    return success({"id": str(value.id), "locale": value.locale}, request_id_from_request(request))


@router.post("/admin/activities/{activity_id}/locations", status_code=201)
async def admin_add_location(
    activity_id: UUID,
    payload: LocationCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    data = payload.model_dump(
        exclude={"address_line_1", "address_line_2", "postal_code", "online_join_url"}
    )
    location = ActivityLocation(
        activity_id=activity.id,
        **data,
        address_line_1_encrypted=(
            encrypt_private({"value": payload.address_line_1}) if payload.address_line_1 else None
        ),
        address_line_2_encrypted=(
            encrypt_private({"value": payload.address_line_2}) if payload.address_line_2 else None
        ),
        postal_code_encrypted=(
            encrypt_private({"value": payload.postal_code}) if payload.postal_code else None
        ),
        online_join_url_encrypted=(
            encrypt_private({"value": payload.online_join_url}) if payload.online_join_url else None
        ),
    )
    session.add(location)
    activity.updated_by = principal.user.id
    activity.version += 1
    await session.commit()
    return success({"id": str(location.id)}, request_id_from_request(request))


@router.post("/admin/activities/{activity_id}/sessions", status_code=201)
async def admin_add_session(
    activity_id: UUID,
    payload: SessionCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    if payload.ends_at <= payload.starts_at:
        raise VavError(
            "ACTIVITY_SESSION_WINDOW_INVALID", "Session end must follow start.", status_code=422
        )
    if payload.location_id and await session.get(ActivityLocation, payload.location_id) is None:
        raise VavError("ACTIVITY_LOCATION_NOT_FOUND", "Location was not found.", status_code=404)
    value = ActivitySession(activity_id=activity.id, **payload.model_dump())
    session.add(value)
    activity.updated_by = principal.user.id
    activity.version += 1
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/activities/{activity_id}/tickets", status_code=201)
async def admin_link_ticket(
    activity_id: UUID,
    payload: TicketLinkRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.tickets.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    product = await session.get(Product, payload.catalog_product_id)
    sku = await session.get(ProductSku, payload.catalog_sku_id)
    if (
        product is None
        or sku is None
        or sku.product_id != product.id
        or product.product_type != "activity_ticket"
        or product.fulfillment_type != "event_admission"
    ):
        raise VavError(
            "ACTIVITY_TICKET_CATALOG_LINK_INVALID", "Catalog link is invalid.", status_code=409
        )
    configuration = dict(sku.fulfillment_configuration)
    configured_activity = configuration.get("activity_id")
    if configured_activity and str(configured_activity) != str(activity.id):
        raise VavError(
            "ACTIVITY_TICKET_ALREADY_LINKED", "SKU belongs to another activity.", status_code=409
        )
    configuration["activity_id"] = str(activity.id)
    configuration.setdefault("ticket_type", payload.ticket_code)
    sku.fulfillment_configuration = configuration
    value = ActivityTicketType(activity_id=activity.id, **payload.model_dump())
    session.add(value)
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.put("/admin/activities/{activity_id}/registration-form")
async def admin_upsert_form(
    activity_id: UUID,
    payload: FormUpsertRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await activity_or_404(session, activity_id)
    schema = validate_form_schema(
        payload.form_schema, max_fields=get_settings().activity_registration_form_max_fields
    )
    value = await session.scalar(
        select(ActivityRegistrationForm).where(ActivityRegistrationForm.activity_id == activity_id)
    )
    if value is None:
        value = ActivityRegistrationForm(
            activity_id=activity_id,
            schema_version=payload.schema_version,
            form_schema=schema,
            consent_requirements=payload.consent_requirements,
            created_by=principal.user.id,
        )
        session.add(value)
    else:
        value.schema_version = payload.schema_version
        value.form_schema = schema
        value.consent_requirements = payload.consent_requirements
    await session.commit()
    return success(
        {"id": str(value.id), "schema_version": value.schema_version},
        request_id_from_request(request),
    )


@router.post("/admin/activities/{activity_id}/transition")
async def admin_transition_activity(
    activity_id: UUID,
    payload: ActivityTransitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    required_permission = {
        ActivityStatus.CANCELLED: "activities.cancel",
        ActivityStatus.ARCHIVED: "activities.archive",
        ActivityStatus.IN_REVIEW: "activities.review",
    }.get(ActivityStatus(payload.target_status), "activities.publish")
    principal.require(required_permission)
    await publication_service.transition(
        session,
        activity,
        ActivityStatus(payload.target_status),
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(activity.id), "status": activity.status}, request_id_from_request(request)
    )


@router.post("/admin/activities/{activity_id}/cancel")
async def admin_cancel_activity(
    activity_id: UUID,
    payload: ActivityCancelRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.cancel")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    activity.cancellation_policy_snapshot = {
        **activity.cancellation_policy_snapshot,
        "requested_action": payload.refund_policy_action,
        "notify_participants": payload.notify_participants,
        "reason_code": payload.reason_code,
    }
    await publication_service.transition(
        session,
        activity,
        ActivityStatus.CANCELLED,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(activity.id), "status": activity.status},
        request_id_from_request(request),
    )


@router.get("/admin/activity-registrations")
async def admin_list_registrations(
    request: Request,
    activity_id: UUID | None = None,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.registrations.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    query = select(ActivityRegistration)
    if activity_id:
        query = query.where(ActivityRegistration.activity_id == activity_id)
    items = list(
        (await session.scalars(query.order_by(ActivityRegistration.created_at.desc()))).all()
    )
    return success(
        {"items": [registration_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.post("/admin/activity-registrations/{registration_id}/review")
async def admin_review_registration(
    registration_id: UUID,
    payload: ReviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.registrations.review")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await session.get(ActivityRegistration, registration_id)
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    value = await registration_service.review(
        session,
        registration,
        action=payload.action,
        reason_code=payload.reason_code,
        user_message=payload.user_message,
        private_notes=payload.private_notes,
        actor_id=principal.user.id,
    )
    return success(registration_payload(value), request_id_from_request(request))


@router.get("/admin/activity-registrations/{registration_id}")
async def admin_registration_detail(
    registration_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.registrations.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    registration = await session.get(ActivityRegistration, registration_id)
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    return success(registration_payload(registration), request_id_from_request(request))


@router.get("/admin/activity-registrations/{registration_id}/sensitive-response")
async def admin_registration_sensitive_response(
    registration_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.registrations.sensitive.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    registration = await session.get(ActivityRegistration, registration_id)
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    value = decrypt_private(registration.form_response_encrypted)
    value.pop("_system", None)
    return success(
        {"schema_version": registration.form_schema_version, "response": value},
        request_id_from_request(request),
    )


@router.post("/admin/activity-registrations/{registration_id}/cancel")
async def admin_cancel_registration(
    registration_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.registrations.cancel")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    registration = await session.get(ActivityRegistration, registration_id)
    if registration is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
    value = await registration_service.cancel(
        session,
        registration,
        actor_type="admin",
        actor_id=principal.user.id,
        reason_code=payload.reason_code,
        reason=payload.reason,
    )
    return success(registration_payload(value), request_id_from_request(request))


@router.get("/admin/activities/{activity_id}/waitlist")
async def admin_activity_waitlist(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    await activity_or_404(session, activity_id)
    items = list(
        (
            await session.scalars(
                select(ActivityWaitlistEntry)
                .where(ActivityWaitlistEntry.activity_id == activity_id)
                .order_by(
                    ActivityWaitlistEntry.priority_score.desc(),
                    ActivityWaitlistEntry.manual_order_override.asc().nullslast(),
                    ActivityWaitlistEntry.sequence_number,
                )
            )
        ).all()
    )
    return success(
        {"items": [waitlist_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.post("/admin/activity-waitlist/{entry_id}/reorder")
async def admin_reorder_waitlist(
    entry_id: UUID,
    payload: WaitlistReorderRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.reorder")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ActivityWaitlistEntry, entry_id)
    if entry is None:
        raise VavError("WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry was not found.", status_code=404)
    value = await registration_service.reorder_waitlist(
        session,
        entry,
        manual_order_override=payload.manual_order_override,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(waitlist_payload(value), request_id_from_request(request))


@router.post("/admin/activity-waitlist/{entry_id}/offer")
async def admin_offer_waitlist(
    entry_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ActivityWaitlistEntry, entry_id)
    if entry is None:
        raise VavError("WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry was not found.", status_code=404)
    value = await registration_service.offer_waitlist_entry(
        session, entry, actor_id=principal.user.id, reason=payload.reason
    )
    return success(waitlist_payload(value), request_id_from_request(request))


@router.post("/admin/activity-waitlist/{entry_id}/cancel")
async def admin_cancel_waitlist(
    entry_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ActivityWaitlistEntry, entry_id)
    if entry is None:
        raise VavError("WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry was not found.", status_code=404)
    registration = await session.get(ActivityRegistration, entry.registration_id)
    entry.status = "cancelled"
    if registration is not None:
        await registration_service.cancel(
            session,
            registration,
            actor_type="admin",
            actor_id=principal.user.id,
            reason_code=payload.reason_code,
            reason=payload.reason,
        )
    else:
        await session.commit()
    return success(waitlist_payload(entry), request_id_from_request(request))


@router.post("/admin/activity-checkins")
async def admin_checkin(
    payload: CheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.perform")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.action == "revoke":
        principal.require("activities.checkin.revoke")
    registration = await attendance_service.perform(
        session,
        token=payload.token,
        registration_number_value=payload.registration_number,
        session_id=payload.session_id,
        action=payload.action,
        actor_id=principal.user.id,
        reason=payload.reason,
        device_reference=payload.device_reference,
    )
    return success(registration_payload(registration), request_id_from_request(request))


@router.get("/admin/activities/{activity_id}/attendance")
async def admin_activity_attendance(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    await activity_or_404(session, activity_id)
    registrations = list(
        (
            await session.scalars(
                select(ActivityRegistration)
                .where(
                    ActivityRegistration.activity_id == activity_id,
                    ActivityRegistration.status == "confirmed",
                )
                .order_by(ActivityRegistration.registration_number)
            )
        ).all()
    )
    return success(
        {
            "summary": {
                "confirmed": len(registrations),
                "checked_in": sum(item.attendance_status == "checked_in" for item in registrations),
                "not_checked_in": sum(
                    item.attendance_status != "checked_in" for item in registrations
                ),
            },
            "items": [registration_payload(item) for item in registrations],
        },
        request_id_from_request(request),
    )


@router.post("/admin/activities/{activity_id}/grouping-plans", status_code=201)
async def admin_create_grouping(
    activity_id: UUID,
    payload: GroupingRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.groups.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    activity = await activity_or_404(session, activity_id)
    if payload.publish:
        principal.require("activities.groups.lock")
    plan = await grouping_service.create(
        session,
        activity=activity,
        actor_id=principal.user.id,
        plan_name=payload.plan_name,
        target_size=payload.target_group_size,
        seed=payload.seed,
        checked_in_only=payload.checked_in_only,
        publish=payload.publish,
    )
    return success({"id": str(plan.id), "status": plan.status}, request_id_from_request(request))


@router.get("/admin/activities/{activity_id}/grouping-plans")
async def admin_grouping_plans(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.groups.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    await activity_or_404(session, activity_id)
    plans = list(
        (
            await session.scalars(
                select(ActivityGroupingPlan)
                .where(ActivityGroupingPlan.activity_id == activity_id)
                .order_by(ActivityGroupingPlan.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(plan.id),
                    "plan_name": plan.plan_name,
                    "grouping_method": plan.grouping_method,
                    "target_group_size": plan.target_group_size,
                    "random_seed": plan.random_seed,
                    "status": plan.status,
                    "version": plan.version,
                }
                for plan in plans
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/activity-grouping-plans/{plan_id}/lock")
async def admin_lock_grouping_plan(
    plan_id: UUID,
    payload: GroupingStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.groups.lock")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    plan = await session.get(ActivityGroupingPlan, plan_id)
    if plan is None:
        raise VavError("GROUPING_PLAN_NOT_FOUND", "Grouping plan was not found.", status_code=404)
    value = await grouping_service.set_locked(
        session, plan, locked=True, actor_id=principal.user.id, reason=payload.reason
    )
    return success(
        {"id": str(value.id), "status": value.status, "version": value.version},
        request_id_from_request(request),
    )


@router.post("/admin/activity-grouping-plans/{plan_id}/unlock")
async def admin_unlock_grouping_plan(
    plan_id: UUID,
    payload: GroupingStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.groups.lock")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    plan = await session.get(ActivityGroupingPlan, plan_id)
    if plan is None:
        raise VavError("GROUPING_PLAN_NOT_FOUND", "Grouping plan was not found.", status_code=404)
    value = await grouping_service.set_locked(
        session, plan, locked=False, actor_id=principal.user.id, reason=payload.reason
    )
    return success(
        {"id": str(value.id), "status": value.status, "version": value.version},
        request_id_from_request(request),
    )


@router.post("/admin/activity-groups/{group_id}/members")
async def admin_move_group_member(
    group_id: UUID,
    payload: GroupMemberMoveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.groups.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    group = await session.get(ActivityGroup, group_id)
    if group is None:
        raise VavError("ACTIVITY_GROUP_NOT_FOUND", "Activity group was not found.", status_code=404)
    value = await grouping_service.move_member(
        session,
        target_group=group,
        registration_id=payload.registration_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(value.id), "group_id": str(value.group_id)},
        request_id_from_request(request),
    )


@router.get("/admin/activities/{activity_id}/post-event/analytics")
async def admin_activity_post_event_analytics(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.post_event.aggregate.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    await activity_or_404(session, activity_id)
    eligible = int(
        await session.scalar(
            select(func.count(ActivityRegistration.id)).where(
                ActivityRegistration.activity_id == activity_id,
                ActivityRegistration.status == "confirmed",
                ActivityRegistration.attendance_status == "checked_in",
            )
        )
        or 0
    )
    submitted = int(
        await session.scalar(
            select(func.count(func.distinct(ActivityPostEventChoice.chooser_user_id))).where(
                ActivityPostEventChoice.activity_id == activity_id,
                ActivityPostEventChoice.status == "active",
            )
        )
        or 0
    )
    matches = int(
        await session.scalar(
            select(func.count(ActivityMutualChoice.id)).where(
                ActivityMutualChoice.activity_id == activity_id,
                ActivityMutualChoice.status == "matched_private",
            )
        )
        or 0
    )
    return success(
        {
            "eligible_participants": eligible,
            "choice_submitters": submitted,
            "submission_rate": submitted / eligible if eligible else 0,
            "mutual_choices": matches,
            "mutual_choice_rate": matches / eligible if eligible else 0,
            "one_sided_choice_details": "restricted",
        },
        request_id_from_request(request),
    )


@router.post("/admin/activity-mutual-choices/{match_id}/suspend")
async def admin_suspend_activity_match(
    match_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.post_event.suspend_match")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    match = await session.get(ActivityMutualChoice, match_id)
    if match is None:
        raise VavError("ACTIVITY_MATCH_NOT_FOUND", "Activity match was not found.", status_code=404)
    match.status = "suspended"
    await session.commit()
    return success(
        {"id": str(match.id), "status": match.status, "reason_code": payload.reason_code},
        request_id_from_request(request),
    )


@router.get("/admin/activities/{activity_id}/audit")
async def admin_activity_audit(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    del principal
    await activity_or_404(session, activity_id)
    events = list(
        (
            await session.scalars(
                select(SecurityAuditEvent)
                .where(
                    SecurityAuditEvent.target_type == "activity",
                    SecurityAuditEvent.target_id == activity_id,
                    SecurityAuditEvent.event_type.like("activity.%"),
                )
                .order_by(SecurityAuditEvent.occurred_at.desc())
                .limit(200)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "actor_type": event.actor_type,
                    "reason": event.reason,
                    "created_at": event.occurred_at.isoformat(),
                }
                for event in events
            ]
        },
        request_id_from_request(request),
    )
