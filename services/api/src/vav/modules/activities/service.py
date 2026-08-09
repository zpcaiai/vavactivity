from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.activities import (
    Activity,
    ActivityCheckinCredential,
    ActivityCheckinEvent,
    ActivityGroup,
    ActivityGroupingPlan,
    ActivityGroupMember,
    ActivityInboxEvent,
    ActivityInteractionRestriction,
    ActivityLocalization,
    ActivityLocation,
    ActivityMutualChoice,
    ActivityParticipantProfile,
    ActivityPostEventChoice,
    ActivityRegistration,
    ActivityRegistrationForm,
    ActivityRegistrationHistory,
    ActivitySession,
    ActivityTicketType,
    ActivityTicketTypeLocalization,
    ActivityWaitlistEntry,
)
from vav.models.catalog import (
    CouponRedemptionReservation,
    InventoryItem,
    InventoryReservation,
    Price,
    Product,
    ProductSku,
)
from vav.models.commerce import (
    Cart,
    CartItem,
    Entitlement,
    Order,
    PaymentLedgerEntry,
)
from vav.models.identity import User
from vav.models.system import OutboxEvent
from vav.modules.activities.crypto import (
    decrypt_private,
    encrypt_private,
    issue_checkin_token,
    verify_checkin_token,
)
from vav.modules.activities.domain import (
    ActivityStatus,
    AttendanceStatus,
    RegistrationStatus,
    WaitlistStatus,
    canonical_user_pair,
    deterministic_groups,
    ensure_activity_transition,
    ensure_registration_transition,
    validate_form_response,
)
from vav.modules.activities.schemas import RegistrationCreateRequest
from vav.modules.catalog.inventory import available_quantity, inventory_service
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.commerce.domain import OrderStatus
from vav.modules.commerce.schemas import CheckoutOrderRequest
from vav.modules.commerce.service import _history, entitlement_service, order_service
from vav.modules.identity.audit import record_security_event


def now() -> datetime:
    return datetime.now(UTC)


async def transaction_lock(session: AsyncSession, key: str) -> None:
    """Serialize high-risk aggregate operations without leaking lock details."""
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


def registration_number() -> str:
    return f"REG-{now():%Y%m%d}-{secrets.token_hex(5).upper()}"


def registration_payload(value: ActivityRegistration) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "registration_number": value.registration_number,
        "activity_id": str(value.activity_id),
        "ticket_type_id": str(value.ticket_type_id),
        "status": value.status,
        "attendance_status": value.attendance_status,
        "order_id": str(value.order_id) if value.order_id else None,
        "entitlement_id": str(value.entitlement_id) if value.entitlement_id else None,
        "review_status": value.review_status,
        "user_visible_review_message": value.user_visible_review_message,
        "confirmed_at": value.confirmed_at.isoformat() if value.confirmed_at else None,
        "version": value.version,
    }


def waitlist_payload(value: ActivityWaitlistEntry) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "activity_id": str(value.activity_id),
        "ticket_type_id": str(value.ticket_type_id),
        "registration_id": str(value.registration_id),
        "status": value.status,
        "sequence_number": value.sequence_number,
        "manual_order_override": value.manual_order_override,
        "promotion_offered_at": (
            value.promotion_offered_at.isoformat() if value.promotion_offered_at else None
        ),
        "promotion_offer_expires_at": (
            value.promotion_offer_expires_at.isoformat()
            if value.promotion_offer_expires_at
            else None
        ),
        "promoted_at": value.promoted_at.isoformat() if value.promoted_at else None,
    }


async def localized_activity_payload(
    session: AsyncSession,
    activity: Activity,
    *,
    locale: str,
    include_private_location: bool = False,
) -> dict[str, Any]:
    payloads = await localized_activity_payloads(
        session,
        [activity],
        locale=locale,
        include_private_location=include_private_location,
    )
    return payloads[0]


def _serialize_activity_payload(
    activity: Activity,
    *,
    localization: ActivityLocalization | None,
    locations: list[ActivityLocation],
    sessions: list[ActivitySession],
    ticket_types: list[ActivityTicketType],
    ticket_localizations: dict[UUID, ActivityTicketTypeLocalization],
    prices_by_sku: dict[UUID, list[Price]],
    inventory_by_sku: dict[UUID, InventoryItem],
    form: ActivityRegistrationForm | None,
    include_private_location: bool,
) -> dict[str, Any]:
    ticket_payloads: list[dict[str, Any]] = []
    for ticket in ticket_types:
        prices = prices_by_sku.get(ticket.catalog_sku_id, [])
        inventory = inventory_by_sku.get(ticket.catalog_sku_id)
        available = available_quantity(inventory) if inventory else None
        if inventory is None or inventory.inventory_policy == "unlimited":
            availability: dict[str, Any] = {"status": "available", "remaining": None}
        elif (available or 0) <= 0:
            availability = {"status": "sold_out", "remaining": 0}
        elif (available or 0) <= max(3, inventory.safety_stock):
            availability = {"status": "limited", "remaining": available}
        else:
            availability = {"status": "available", "remaining": available}
        if ticket.capacity_display_mode == "hidden":
            availability = {"status": "hidden", "remaining": None}
        elif ticket.capacity_display_mode != "exact":
            availability["remaining"] = None
        localized_ticket = ticket_localizations.get(ticket.id)
        ticket_payloads.append(
            {
                "id": str(ticket.id),
                "ticket_code": ticket.ticket_code,
                "name": localized_ticket.name if localized_ticket else ticket.internal_name,
                "description": localized_ticket.description if localized_ticket else None,
                "eligibility_notice": (
                    localized_ticket.eligibility_notice if localized_ticket else None
                ),
                "catalog_product_id": str(ticket.catalog_product_id),
                "catalog_sku_id": str(ticket.catalog_sku_id),
                "waitlist_enabled": ticket.waitlist_enabled,
                "registration_opens_at": (
                    ticket.registration_opens_at.isoformat()
                    if ticket.registration_opens_at
                    else None
                ),
                "registration_closes_at": (
                    ticket.registration_closes_at.isoformat()
                    if ticket.registration_closes_at
                    else None
                ),
                "prices": [
                    {
                        "currency": price.currency_code,
                        "unit_amount_minor": price.unit_amount_minor,
                        "billing_type": price.billing_type,
                    }
                    for price in prices
                ],
                "availability": availability,
            }
        )
    location_payload: list[dict[str, Any]] = []
    for item in locations:
        detail: dict[str, Any] = {
            "id": str(item.id),
            "type": item.location_type,
            "venue_name": item.venue_name,
            "country_code": item.country_code,
            "region": item.region,
            "city": item.city,
            "public_address_precision": item.public_address_precision,
        }
        if include_private_location:
            for key in (
                "address_line_1_encrypted",
                "address_line_2_encrypted",
                "postal_code_encrypted",
                "online_join_url_encrypted",
            ):
                encrypted = getattr(item, key)
                if encrypted:
                    detail[key.removesuffix("_encrypted")] = decrypt_private(encrypted)["value"]
        location_payload.append(detail)
    return {
        "id": str(activity.id),
        "activity_code": activity.activity_code,
        "status": activity.status,
        "format": activity.activity_format,
        "title": localization.title if localization else activity.internal_name,
        "slug": localization.slug if localization else activity.activity_code,
        "summary": localization.summary if localization else None,
        "description_blocks": localization.description_blocks if localization else [],
        "timezone": activity.timezone,
        "starts_at": activity.starts_at.isoformat(),
        "ends_at": activity.ends_at.isoformat(),
        "registration_opens_at": (
            activity.registration_opens_at.isoformat() if activity.registration_opens_at else None
        ),
        "registration_closes_at": (
            activity.registration_closes_at.isoformat() if activity.registration_closes_at else None
        ),
        "locations": location_payload,
        "sessions": [
            {
                "id": str(item.id),
                "session_code": item.session_code,
                "title": item.title,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
                "location_id": str(item.location_id) if item.location_id else None,
            }
            for item in sessions
        ],
        "ticket_types": ticket_payloads,
        "registration_form": (
            {
                "schema_version": form.schema_version,
                "form_schema": form.form_schema,
                "consent_requirements": form.consent_requirements,
            }
            if form
            else {"schema_version": 1, "form_schema": {"fields": []}, "consent_requirements": []}
        ),
        "post_event_choice_enabled": activity.post_event_choice_enabled,
    }


async def localized_activity_payloads(
    session: AsyncSession,
    activities: list[Activity],
    *,
    locale: str,
    include_private_location: bool = False,
) -> list[dict[str, Any]]:
    """Serialize many activities with a fixed number of database queries."""
    if not activities:
        return []
    activity_ids = [activity.id for activity in activities]
    activity_by_id = {activity.id: activity for activity in activities}
    supported_locales = {locale, *(activity.default_locale for activity in activities)}

    localizations = list(
        (
            await session.scalars(
                select(ActivityLocalization).where(
                    ActivityLocalization.activity_id.in_(activity_ids),
                    ActivityLocalization.locale.in_(supported_locales),
                )
            )
        ).all()
    )
    localization_by_activity: dict[UUID, ActivityLocalization] = {}
    for localization in localizations:
        current_localization = localization_by_activity.get(localization.activity_id)
        if current_localization is None or (
            localization.locale == locale and current_localization.locale != locale
        ):
            localization_by_activity[localization.activity_id] = localization

    locations_by_activity: dict[UUID, list[ActivityLocation]] = defaultdict(list)
    for location in (
        await session.scalars(
            select(ActivityLocation).where(ActivityLocation.activity_id.in_(activity_ids))
        )
    ).all():
        locations_by_activity[location.activity_id].append(location)

    sessions_by_activity: dict[UUID, list[ActivitySession]] = defaultdict(list)
    for activity_session in (
        await session.scalars(
            select(ActivitySession)
            .where(ActivitySession.activity_id.in_(activity_ids))
            .order_by(
                ActivitySession.activity_id, ActivitySession.sort_order, ActivitySession.starts_at
            )
        )
    ).all():
        sessions_by_activity[activity_session.activity_id].append(activity_session)

    tickets = list(
        (
            await session.scalars(
                select(ActivityTicketType)
                .where(
                    ActivityTicketType.activity_id.in_(activity_ids),
                    ActivityTicketType.status == "active",
                )
                .order_by(
                    ActivityTicketType.activity_id,
                    ActivityTicketType.sort_order,
                    ActivityTicketType.id,
                )
            )
        ).all()
    )
    tickets_by_activity: dict[UUID, list[ActivityTicketType]] = defaultdict(list)
    ticket_by_id = {ticket.id: ticket for ticket in tickets}
    for ticket in tickets:
        tickets_by_activity[ticket.activity_id].append(ticket)

    ticket_localization_by_id: dict[UUID, ActivityTicketTypeLocalization] = {}
    if tickets:
        for ticket_localization in (
            await session.scalars(
                select(ActivityTicketTypeLocalization).where(
                    ActivityTicketTypeLocalization.ticket_type_id.in_(ticket_by_id),
                    ActivityTicketTypeLocalization.locale.in_(supported_locales),
                )
            )
        ).all():
            current_ticket_localization = ticket_localization_by_id.get(
                ticket_localization.ticket_type_id
            )
            ticket = ticket_by_id[ticket_localization.ticket_type_id]
            default_locale = activity_by_id[ticket.activity_id].default_locale
            if (
                current_ticket_localization is None
                or (
                    ticket_localization.locale == locale
                    and current_ticket_localization.locale != locale
                )
            ) and ticket_localization.locale in {locale, default_locale}:
                ticket_localization_by_id[ticket_localization.ticket_type_id] = (
                    ticket_localization
                )

    sku_ids = [ticket.catalog_sku_id for ticket in tickets]
    prices_by_sku: dict[UUID, list[Price]] = defaultdict(list)
    inventory_by_sku: dict[UUID, InventoryItem] = {}
    if sku_ids:
        current_time = now()
        for price in (
            await session.scalars(
                select(Price)
                .where(
                    Price.sku_id.in_(sku_ids),
                    Price.status == "active",
                    Price.valid_from <= current_time,
                    or_(Price.valid_until.is_(None), Price.valid_until > current_time),
                )
                .order_by(Price.sku_id, Price.currency_code, Price.unit_amount_minor)
            )
        ).all():
            prices_by_sku[price.sku_id].append(price)
        inventory_by_sku = {
            inventory_item.sku_id: inventory_item
            for inventory_item in (
                await session.scalars(
                    select(InventoryItem).where(InventoryItem.sku_id.in_(sku_ids))
                )
            ).all()
        }

    form_by_activity = {
        form.activity_id: form
        for form in (
            await session.scalars(
                select(ActivityRegistrationForm).where(
                    ActivityRegistrationForm.activity_id.in_(activity_ids)
                )
            )
        ).all()
    }
    return [
        _serialize_activity_payload(
            activity,
            localization=localization_by_activity.get(activity.id),
            locations=locations_by_activity.get(activity.id, []),
            sessions=sessions_by_activity.get(activity.id, []),
            ticket_types=tickets_by_activity.get(activity.id, []),
            ticket_localizations=ticket_localization_by_id,
            prices_by_sku=prices_by_sku,
            inventory_by_sku=inventory_by_sku,
            form=form_by_activity.get(activity.id),
            include_private_location=include_private_location,
        )
        for activity in activities
    ]


def transition_registration(
    session: AsyncSession,
    registration: ActivityRegistration,
    target: RegistrationStatus,
    *,
    actor_type: str,
    actor_id: UUID | None = None,
    reason_code: str | None = None,
    reason: str | None = None,
) -> None:
    before = registration.status
    if before != target:
        ensure_registration_transition(before, target)
        registration.status = target
        registration.version += 1
    if target == RegistrationStatus.CONFIRMED:
        registration.confirmed_at = registration.confirmed_at or now()
    if target == RegistrationStatus.CANCELLED:
        registration.cancelled_at = now()
    session.add(
        ActivityRegistrationHistory(
            registration_id=registration.id,
            from_status=before,
            to_status=target,
            reason_code=reason_code,
            reason=reason,
            actor_type=actor_type,
            actor_user_id=actor_id,
        )
    )


class ActivityPublicationService:
    async def validate_for_publish(
        self, session: AsyncSession, activity: Activity
    ) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        if activity.ends_at <= activity.starts_at:
            errors.append({"code": "ACTIVITY_WINDOW_INVALID", "field": "ends_at"})
        if (
            activity.registration_opens_at
            and activity.registration_closes_at
            and activity.registration_opens_at >= activity.registration_closes_at
        ):
            errors.append({"code": "REGISTRATION_WINDOW_INVALID", "field": "registration_opens_at"})
        if activity.registration_closes_at and activity.registration_closes_at > activity.starts_at:
            errors.append(
                {"code": "REGISTRATION_CLOSE_AFTER_START", "field": "registration_closes_at"}
            )
        try:
            ZoneInfo(activity.timezone)
        except ZoneInfoNotFoundError:
            errors.append({"code": "ACTIVITY_TIMEZONE_INVALID", "field": "timezone"})
        locations = list(
            (
                await session.scalars(
                    select(ActivityLocation).where(ActivityLocation.activity_id == activity.id)
                )
            ).all()
        )
        if activity.activity_format in {"in_person", "hybrid"} and not any(
            location.location_type == "in_person" for location in locations
        ):
            errors.append({"code": "IN_PERSON_LOCATION_REQUIRED", "field": "locations"})
        if activity.activity_format in {"online", "hybrid"} and not any(
            location.location_type == "online" and location.online_join_url_encrypted
            for location in locations
        ):
            errors.append({"code": "ONLINE_MEETING_REQUIRED", "field": "locations"})
        if activity.post_event_choice_enabled and (
            not activity.post_event_choice_opens_at
            or not activity.post_event_choice_closes_at
            or activity.post_event_choice_opens_at < activity.starts_at
            or activity.post_event_choice_opens_at >= activity.post_event_choice_closes_at
        ):
            errors.append({"code": "POST_EVENT_WINDOW_INVALID", "field": "post_event_choice"})
        localization = await session.scalar(
            select(ActivityLocalization).where(
                ActivityLocalization.activity_id == activity.id,
                ActivityLocalization.locale == activity.default_locale,
                ActivityLocalization.translation_status == "ready",
            )
        )
        if localization is None:
            errors.append({"code": "DEFAULT_LOCALIZATION_NOT_READY", "field": "localizations"})
        tickets = list(
            (
                await session.scalars(
                    select(ActivityTicketType).where(
                        ActivityTicketType.activity_id == activity.id,
                        ActivityTicketType.status == "active",
                    )
                )
            ).all()
        )
        if not tickets:
            errors.append({"code": "ACTIVE_TICKET_REQUIRED", "field": "ticket_types"})
        for ticket in tickets:
            sku = await session.get(ProductSku, ticket.catalog_sku_id)
            product = await session.get(Product, ticket.catalog_product_id)
            if (
                sku is None
                or product is None
                or sku.product_id != product.id
                or product.product_type != "activity_ticket"
                or product.fulfillment_type != "event_admission"
                or product.status != "active"
                or sku.status != "active"
            ):
                errors.append({"code": "TICKET_CATALOG_LINK_INVALID", "field": ticket.ticket_code})
                continue
            price = await session.scalar(
                select(Price).where(Price.sku_id == sku.id, Price.status == "active").limit(1)
            )
            if price is None or (sku.billing_type == "free" and price.unit_amount_minor != 0):
                errors.append({"code": "TICKET_PRICE_INVALID", "field": ticket.ticket_code})
            inventory = await session.scalar(
                select(InventoryItem).where(InventoryItem.sku_id == sku.id)
            )
            if sku.inventory_policy != "unlimited" and inventory is None:
                errors.append({"code": "TICKET_INVENTORY_REQUIRED", "field": ticket.ticket_code})
            if (
                ticket.registration_opens_at
                and ticket.registration_closes_at
                and ticket.registration_opens_at >= ticket.registration_closes_at
            ):
                errors.append(
                    {"code": "TICKET_REGISTRATION_WINDOW_INVALID", "field": ticket.ticket_code}
                )
        return errors

    async def transition(
        self,
        session: AsyncSession,
        activity: Activity,
        target: ActivityStatus,
        *,
        actor_id: UUID,
        reason: str,
    ) -> Activity:
        if target in {
            ActivityStatus.SCHEDULED,
            ActivityStatus.PUBLISHED,
            ActivityStatus.REGISTRATION_OPEN,
        }:
            errors = await self.validate_for_publish(session, activity)
            if errors:
                raise VavError(
                    "ACTIVITY_PUBLICATION_BLOCKED",
                    "Activity is not ready to publish.",
                    status_code=409,
                    details=errors,
                )
        before = activity.status
        ensure_activity_transition(before, target)
        if target == ActivityStatus.CANCELLED:
            await self._cancel_downstream(session, activity, actor_id=actor_id, reason=reason)
        activity.status = target
        activity.updated_by = actor_id
        activity.version += 1
        session.add(
            OutboxEvent(
                topic="activity.status.changed",
                aggregate_type="activity",
                aggregate_id=str(activity.id),
                payload={"activity_id": str(activity.id), "from": before, "to": target},
            )
        )
        record_security_event(
            session,
            event_type="activity.status.changed",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity",
            target_id=activity.id,
            reason=reason,
            before_state={"status": before},
            after_state={"status": target},
        )
        await session.commit()
        return activity

    async def _cancel_downstream(
        self, session: AsyncSession, activity: Activity, *, actor_id: UUID, reason: str
    ) -> None:
        tickets = list(
            (
                await session.scalars(
                    select(ActivityTicketType).where(ActivityTicketType.activity_id == activity.id)
                )
            ).all()
        )
        for ticket in tickets:
            ticket.status = "inactive"
            sku = await session.get(ProductSku, ticket.catalog_sku_id)
            if sku is not None:
                sku.status = "inactive"
        registrations = list(
            (
                await session.scalars(
                    select(ActivityRegistration)
                    .where(
                        ActivityRegistration.activity_id == activity.id,
                        ActivityRegistration.status.not_in(
                            (
                                RegistrationStatus.CANCELLED,
                                RegistrationStatus.REJECTED,
                                RegistrationStatus.EXPIRED,
                            )
                        ),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for registration in registrations:
            transition_registration(
                session,
                registration,
                RegistrationStatus.CANCELLED,
                actor_type="admin",
                actor_id=actor_id,
                reason_code="activity_cancelled",
                reason=reason,
            )
            if registration.order_id or registration.entitlement_id:
                session.add(
                    OutboxEvent(
                        topic="activity.cancellation.commerce_action_required",
                        aggregate_type="activity_registration",
                        aggregate_id=str(registration.id),
                        payload={
                            "activity_id": str(activity.id),
                            "registration_id": str(registration.id),
                            "order_id": str(registration.order_id)
                            if registration.order_id
                            else None,
                            "entitlement_id": str(registration.entitlement_id)
                            if registration.entitlement_id
                            else None,
                            "policy": str(
                                activity.cancellation_policy_snapshot.get(
                                    "requested_action", "manual_review"
                                )
                            ),
                        },
                    )
                )
        waitlist_entries = list(
            (
                await session.scalars(
                    select(ActivityWaitlistEntry).where(
                        ActivityWaitlistEntry.activity_id == activity.id,
                        ActivityWaitlistEntry.status.in_(
                            (WaitlistStatus.ACTIVE, WaitlistStatus.PROMOTION_OFFERED)
                        ),
                    )
                )
            ).all()
        )
        for entry in waitlist_entries:
            entry.status = WaitlistStatus.CANCELLED
        credentials = list(
            (
                await session.scalars(
                    select(ActivityCheckinCredential)
                    .join(
                        ActivityRegistration,
                        ActivityRegistration.id == ActivityCheckinCredential.registration_id,
                    )
                    .where(ActivityRegistration.activity_id == activity.id)
                )
            ).all()
        )
        for credential in credentials:
            credential.status = "revoked"
            credential.rotated_at = now()
        choices = list(
            (
                await session.scalars(
                    select(ActivityPostEventChoice).where(
                        ActivityPostEventChoice.activity_id == activity.id,
                        ActivityPostEventChoice.status == "active",
                    )
                )
            ).all()
        )
        for choice in choices:
            choice.status = "withdrawn"
            choice.withdrawn_at = now()
        session.add(
            OutboxEvent(
                topic="activity.cancelled",
                aggregate_type="activity",
                aggregate_id=str(activity.id),
                payload={"activity_id": str(activity.id)},
            )
        )


class ActivityRegistrationService:
    async def _capacity_available(self, session: AsyncSession, ticket: ActivityTicketType) -> bool:
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == ticket.catalog_sku_id)
        )
        return (
            item is None
            or item.inventory_policy == "unlimited"
            or (available_quantity(item) or 0) > 0
        )

    async def _create_order(
        self,
        session: AsyncSession,
        registration: ActivityRegistration,
        user: User,
        ticket: ActivityTicketType,
        *,
        currency: str,
        locale: str,
        billing_email: str,
    ) -> Order:
        anonymous_id = uuid4()
        cart = Cart(
            anonymous_session_id=anonymous_id,
            currency_code=currency,
            status="active",
            expires_at=now() + timedelta(minutes=30),
        )
        session.add(cart)
        await session.flush()
        session.add(CartItem(cart_id=cart.id, sku_id=ticket.catalog_sku_id, quantity=1))
        await session.commit()
        order = await order_service.create(
            session,
            user=user,
            request=CheckoutOrderRequest(
                cart_id=cart.id,
                anonymous_session_id=anonymous_id,
                locale=locale,
                billing_email=billing_email,
                expected_total_minor=None,
                terms_version=user.terms_version or "activity-v1",
                privacy_version=user.privacy_version or "activity-v1",
                refund_policy_version="activity-v1",
            ),
            idempotency_key=f"activity-{registration.id}",
        )
        persisted_registration = await session.get(ActivityRegistration, registration.id)
        if persisted_registration is None:
            raise VavError("REGISTRATION_NOT_FOUND", "Registration was not found.", status_code=404)
        persisted_registration.order_id = order.id
        persisted_registration.pricing_quote_id = order.pricing_quote_id
        await session.commit()
        if order.total_minor == 0:
            await self._fulfill_zero_order(session, order)
        return order

    async def _fulfill_zero_order(self, session: AsyncSession, order: Order) -> None:
        locked_order = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if locked_order is None or locked_order.status == OrderStatus.FULFILLED:
            return
        order = locked_order
        _history(session, order, OrderStatus.PAYMENT_PROCESSING, actor_type="system")
        _history(session, order, OrderStatus.PAID, actor_type="system")
        order.paid_at = now()
        reservation_ids = list(
            (
                await session.scalars(
                    select(InventoryReservation.id).where(InventoryReservation.order_id == order.id)
                )
            ).all()
        )
        for reservation_id in reservation_ids:
            await inventory_service.confirm(session, reservation_id, commit=False)
        coupon_ids = list(
            (
                await session.scalars(
                    select(CouponRedemptionReservation.id).where(
                        CouponRedemptionReservation.order_id == order.id
                    )
                )
            ).all()
        )
        for reservation_id in coupon_ids:
            await coupon_redemption_service.confirm(session, reservation_id, commit=False)
        _history(session, order, OrderStatus.FULFILLING, actor_type="system")
        await entitlement_service.activate_order(session, order)
        _history(session, order, OrderStatus.FULFILLED, actor_type="system")
        order.fulfilled_at = now()
        session.add(
            PaymentLedgerEntry(
                entry_type="zero_value_order_fulfilled",
                order_id=order.id,
                provider="internal",
                provider_reference=f"zero:{order.id}",
                currency_code=order.currency_code,
                amount_minor=0,
                effective_at=now(),
            )
        )
        await session.commit()

    async def create(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        user: User,
        request: RegistrationCreateRequest,
    ) -> ActivityRegistration:
        await transaction_lock(session, f"activity-registration:{activity.id}:{user.id}")
        activity = (
            await session.scalar(
                select(Activity).where(Activity.id == activity.id).with_for_update()
            )
            or activity
        )
        current = now()
        if activity.status not in {ActivityStatus.PUBLISHED, ActivityStatus.REGISTRATION_OPEN}:
            raise VavError(
                "ACTIVITY_REGISTRATION_CLOSED", "Registration is not open.", status_code=409
            )
        if activity.registration_opens_at and current < activity.registration_opens_at:
            raise VavError(
                "ACTIVITY_REGISTRATION_NOT_STARTED", "Registration has not opened.", status_code=409
            )
        if activity.registration_closes_at and current >= activity.registration_closes_at:
            raise VavError(
                "ACTIVITY_REGISTRATION_CLOSED", "Registration is closed.", status_code=409
            )
        existing = await session.scalar(
            select(ActivityRegistration).where(
                ActivityRegistration.activity_id == activity.id,
                ActivityRegistration.user_id == user.id,
            )
        )
        if existing is not None:
            return existing
        ticket = await session.get(ActivityTicketType, request.ticket_type_id)
        if ticket is None or ticket.activity_id != activity.id or ticket.status != "active":
            raise VavError(
                "ACTIVITY_TICKET_NOT_FOUND", "Ticket type was not found.", status_code=404
            )
        if ticket.registration_opens_at and current < ticket.registration_opens_at:
            raise VavError(
                "ACTIVITY_TICKET_REGISTRATION_NOT_STARTED",
                "Ticket registration has not opened.",
                status_code=409,
            )
        if ticket.registration_closes_at and current >= ticket.registration_closes_at:
            raise VavError(
                "ACTIVITY_TICKET_REGISTRATION_CLOSED",
                "Ticket registration is closed.",
                status_code=409,
            )
        form = await session.scalar(
            select(ActivityRegistrationForm).where(
                ActivityRegistrationForm.activity_id == activity.id
            )
        )
        response = validate_form_response(
            form.form_schema if form else {"fields": []},
            request.form_response,
            max_response_chars=20_000,
        )
        required_consents = {
            str(item.get("key"))
            for item in (form.consent_requirements if form else [])
            if item.get("required")
        }
        if not required_consents.issubset(set(request.accepted_consents)):
            raise VavError(
                "ACTIVITY_CONSENT_REQUIRED", "Required consent is missing.", status_code=422
            )
        response["_system"] = {
            "accepted_consents": sorted(request.accepted_consents),
            "commerce": {
                "currency": request.currency_code,
                "locale": request.locale,
                "billing_email": str(request.billing_email or user.display_email),
            },
        }
        approval = ticket.approval_policy_override or activity.approval_policy
        if ticket.eligibility_rules or approval == "rule_assisted":
            # The unresolved eligibility policy may assist a human review, but it
            # must never reject a participant opaquely.
            approval = "manual"
        payment_timing = ticket.payment_timing_override or activity.payment_timing_policy
        capacity = await self._capacity_available(session, ticket)
        if not capacity:
            if not (activity.waitlist_enabled and ticket.waitlist_enabled):
                raise VavError("ACTIVITY_SOLD_OUT", "This ticket is sold out.", status_code=409)
            initial = RegistrationStatus.WAITLISTED
        elif approval == "manual":
            initial = RegistrationStatus.PENDING_APPROVAL
        else:
            initial = RegistrationStatus.STARTED
        registration = ActivityRegistration(
            registration_number=registration_number(),
            activity_id=activity.id,
            ticket_type_id=ticket.id,
            user_id=user.id,
            status=RegistrationStatus.STARTED,
            form_schema_version=form.schema_version if form else 1,
            form_response_encrypted=encrypt_private(response),
        )
        session.add(registration)
        await session.flush()
        if initial == RegistrationStatus.WAITLISTED:
            transition_registration(
                session, registration, initial, actor_type="system", reason_code="capacity_full"
            )
            sequence = int(
                await session.scalar(
                    select(func.coalesce(func.max(ActivityWaitlistEntry.sequence_number), 0)).where(
                        ActivityWaitlistEntry.activity_id == activity.id,
                        ActivityWaitlistEntry.ticket_type_id == ticket.id,
                    )
                )
                or 0
            )
            session.add(
                ActivityWaitlistEntry(
                    activity_id=activity.id,
                    ticket_type_id=ticket.id,
                    user_id=user.id,
                    registration_id=registration.id,
                    status=WaitlistStatus.ACTIVE,
                    sequence_number=sequence + 1,
                    joined_at=now(),
                )
            )
            await session.commit()
            return registration
        if initial == RegistrationStatus.PENDING_APPROVAL:
            transition_registration(
                session, registration, initial, actor_type="user", actor_id=user.id
            )
        await session.commit()
        if approval == "automatic" or payment_timing == "before_approval":
            try:
                order = await self._create_order(
                    session,
                    registration,
                    user,
                    ticket,
                    currency=request.currency_code,
                    locale=request.locale,
                    billing_email=str(request.billing_email or user.display_email),
                )
            except VavError as error:
                if error.code not in {"INVENTORY_NOT_AVAILABLE", "ACTIVITY_SOLD_OUT"} or not (
                    activity.waitlist_enabled and ticket.waitlist_enabled
                ):
                    raise
                await session.rollback()
                persisted = await session.scalar(
                    select(ActivityRegistration)
                    .where(ActivityRegistration.id == registration.id)
                    .with_for_update()
                )
                if persisted is None:
                    raise
                transition_registration(
                    session,
                    persisted,
                    RegistrationStatus.WAITLISTED,
                    actor_type="system",
                    reason_code="last_seat_race_lost",
                )
                sequence = int(
                    await session.scalar(
                        select(
                            func.coalesce(func.max(ActivityWaitlistEntry.sequence_number), 0)
                        ).where(
                            ActivityWaitlistEntry.activity_id == activity.id,
                            ActivityWaitlistEntry.ticket_type_id == ticket.id,
                        )
                    )
                    or 0
                )
                session.add(
                    ActivityWaitlistEntry(
                        activity_id=activity.id,
                        ticket_type_id=ticket.id,
                        user_id=user.id,
                        registration_id=persisted.id,
                        status=WaitlistStatus.ACTIVE,
                        sequence_number=sequence + 1,
                        joined_at=now(),
                    )
                )
                await session.commit()
                return persisted
            refreshed_registration = await session.get(ActivityRegistration, registration.id)
            if (
                refreshed_registration
                and order.total_minor > 0
                and refreshed_registration.status == RegistrationStatus.STARTED
            ):
                transition_registration(
                    session,
                    refreshed_registration,
                    RegistrationStatus.PENDING_PAYMENT,
                    actor_type="system",
                )
                await session.commit()
        elif registration.status == RegistrationStatus.STARTED:
            transition_registration(
                session, registration, RegistrationStatus.CONFIRMED, actor_type="system"
            )
            await session.commit()
        return registration

    async def review(
        self,
        session: AsyncSession,
        registration: ActivityRegistration,
        *,
        action: str,
        reason_code: str,
        user_message: str | None,
        private_notes: str | None,
        actor_id: UUID,
    ) -> ActivityRegistration:
        if registration.status != RegistrationStatus.PENDING_APPROVAL:
            raise VavError(
                "REGISTRATION_NOT_REVIEWABLE",
                "Registration is not pending review.",
                status_code=409,
            )
        if action == "request_information":
            registration.review_status = "information_requested"
            registration.reviewed_by = actor_id
            registration.reviewed_at = now()
            registration.review_reason_code = reason_code
            registration.user_visible_review_message = user_message
            registration.review_notes_encrypted = (
                encrypt_private({"notes": private_notes}) if private_notes else None
            )
            session.add(
                OutboxEvent(
                    topic="activity.registration.information_requested",
                    aggregate_type="activity_registration",
                    aggregate_id=str(registration.id),
                    payload={
                        "registration_id": str(registration.id),
                        "recipient_user_id": str(registration.user_id),
                    },
                )
            )
            await session.commit()
            return registration
        registration.reviewed_by = actor_id
        registration.reviewed_at = now()
        registration.review_reason_code = reason_code
        registration.user_visible_review_message = user_message
        registration.review_notes_encrypted = (
            encrypt_private({"notes": private_notes}) if private_notes else None
        )
        if action == "reject":
            registration.review_status = "rejected"
            transition_registration(
                session,
                registration,
                RegistrationStatus.REJECTED,
                actor_type="admin",
                actor_id=actor_id,
                reason_code=reason_code,
            )
            await session.commit()
            return registration
        registration.review_status = "approved"
        activity = await session.get(Activity, registration.activity_id)
        ticket = await session.get(ActivityTicketType, registration.ticket_type_id)
        user = await session.get(User, registration.user_id)
        if activity is None or ticket is None or user is None:
            raise VavError(
                "REGISTRATION_CONTEXT_INVALID", "Registration context is invalid.", status_code=409
            )
        payment_timing = ticket.payment_timing_override or activity.payment_timing_policy
        if registration.entitlement_id:
            target = RegistrationStatus.CONFIRMED
        elif payment_timing == "after_approval":
            target = RegistrationStatus.APPROVED_PENDING_PAYMENT
        else:
            target = RegistrationStatus.PENDING_PAYMENT
        transition_registration(
            session,
            registration,
            target,
            actor_type="admin",
            actor_id=actor_id,
            reason_code=reason_code,
        )
        await session.commit()
        if payment_timing == "after_approval" and registration.order_id is None:
            private = decrypt_private(registration.form_response_encrypted)
            commerce = private.get("_system", {}).get("commerce", {})
            order = await self._create_order(
                session,
                registration,
                user,
                ticket,
                currency=str(commerce.get("currency", "USD")),
                locale=str(commerce.get("locale", user.preferred_locale)),
                billing_email=str(commerce.get("billing_email", user.display_email)),
            )
            refreshed_registration = await session.get(ActivityRegistration, registration.id)
            if (
                refreshed_registration
                and order.total_minor == 0
                and refreshed_registration.entitlement_id is None
            ):
                raise VavError(
                    "ACTIVITY_ENTITLEMENT_PROJECTION_FAILED",
                    "Free registration could not be projected.",
                    status_code=409,
                )
            if refreshed_registration is not None:
                registration = refreshed_registration
        return registration

    async def project_entitlement(
        self,
        session: AsyncSession,
        entitlement: Entitlement,
        *,
        source_event_id: UUID | None = None,
    ) -> ActivityRegistration | None:
        if entitlement.entitlement_type != "activity_admission":
            return None
        event_id = source_event_id or entitlement.id
        existing_event = await session.scalar(
            select(ActivityInboxEvent).where(ActivityInboxEvent.source_event_id == event_id)
        )
        if existing_event is not None:
            projected: ActivityRegistration | None = await session.scalar(
                select(ActivityRegistration).where(
                    ActivityRegistration.entitlement_id == entitlement.id
                )
            )
            return projected
        await transaction_lock(session, f"activity-entitlement:{entitlement.id}")
        registration = await session.scalar(
            select(ActivityRegistration)
            .where(
                ActivityRegistration.order_id == entitlement.order_id,
                ActivityRegistration.user_id == entitlement.user_id,
            )
            .with_for_update()
        )
        if registration is None:
            return None
        registration.entitlement_id = entitlement.id
        if registration.status == RegistrationStatus.PENDING_APPROVAL:
            pass
        elif registration.status != RegistrationStatus.CONFIRMED:
            transition_registration(
                session,
                registration,
                RegistrationStatus.CONFIRMED,
                actor_type="system",
                reason_code="entitlement_activated",
            )
        session.add(
            ActivityInboxEvent(
                source_event_id=event_id,
                event_type="entitlement.activated",
                processing_status="processed",
                processed_at=now(),
            )
        )
        session.add(
            OutboxEvent(
                topic="activity.registration.confirmed",
                aggregate_type="activity_registration",
                aggregate_id=str(registration.id),
                payload={
                    "registration_id": str(registration.id),
                    "activity_id": str(registration.activity_id),
                    "entitlement_id": str(entitlement.id),
                },
            )
        )
        return registration

    async def cancel(
        self,
        session: AsyncSession,
        registration: ActivityRegistration,
        *,
        actor_type: str,
        actor_id: UUID,
        reason_code: str,
        reason: str,
    ) -> ActivityRegistration:
        await transaction_lock(session, f"activity-registration:{registration.id}")
        registration = (
            await session.scalar(
                select(ActivityRegistration)
                .where(ActivityRegistration.id == registration.id)
                .with_for_update()
            )
            or registration
        )
        if registration.status in {
            RegistrationStatus.CANCELLED,
            RegistrationStatus.REJECTED,
            RegistrationStatus.EXPIRED,
        }:
            return registration
        transition_registration(
            session,
            registration,
            RegistrationStatus.CANCELLED,
            actor_type=actor_type,
            actor_id=actor_id,
            reason_code=reason_code,
            reason=reason,
        )
        waitlist = await session.scalar(
            select(ActivityWaitlistEntry).where(
                ActivityWaitlistEntry.registration_id == registration.id
            )
        )
        if waitlist and waitlist.status in {
            WaitlistStatus.ACTIVE,
            WaitlistStatus.PROMOTION_OFFERED,
        }:
            waitlist.status = WaitlistStatus.CANCELLED
        credential = await session.scalar(
            select(ActivityCheckinCredential).where(
                ActivityCheckinCredential.registration_id == registration.id
            )
        )
        if credential:
            credential.status = "revoked"
            credential.rotated_at = now()
        session.add(
            OutboxEvent(
                topic="activity.registration.cancelled",
                aggregate_type="activity_registration",
                aggregate_id=str(registration.id),
                payload={
                    "registration_id": str(registration.id),
                    "activity_id": str(registration.activity_id),
                    "recipient_user_id": str(registration.user_id),
                    "commerce_action_required": bool(
                        registration.order_id or registration.entitlement_id
                    ),
                },
            )
        )
        record_security_event(
            session,
            event_type="activity.registration.cancelled",
            actor_type=actor_type,
            actor_user_id=actor_id,
            target_type="activity_registration",
            target_id=registration.id,
            reason=reason,
        )
        await session.commit()
        return registration

    async def offer_waitlist_places(self, session: AsyncSession, *, limit: int = 100) -> int:
        if not get_settings().activity_waitlist_auto_promotion_enabled:
            return 0
        offered = 0
        entries = list(
            (
                await session.scalars(
                    select(ActivityWaitlistEntry)
                    .where(ActivityWaitlistEntry.status == WaitlistStatus.ACTIVE)
                    .order_by(
                        ActivityWaitlistEntry.priority_score.desc(),
                        ActivityWaitlistEntry.manual_order_override.asc().nullslast(),
                        ActivityWaitlistEntry.sequence_number,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
        )
        remaining_by_ticket: dict[UUID, int] = {}
        for entry in entries:
            ticket = await session.get(ActivityTicketType, entry.ticket_type_id)
            if ticket is None:
                continue
            if ticket.id not in remaining_by_ticket:
                inventory = await session.scalar(
                    select(InventoryItem)
                    .where(InventoryItem.sku_id == ticket.catalog_sku_id)
                    .with_for_update()
                )
                if inventory is None or inventory.inventory_policy == "unlimited":
                    remaining_by_ticket[ticket.id] = limit
                else:
                    active_offers = int(
                        await session.scalar(
                            select(func.count(ActivityWaitlistEntry.id)).where(
                                ActivityWaitlistEntry.ticket_type_id == ticket.id,
                                ActivityWaitlistEntry.status == WaitlistStatus.PROMOTION_OFFERED,
                                ActivityWaitlistEntry.promotion_offer_expires_at > now(),
                            )
                        )
                        or 0
                    )
                    remaining_by_ticket[ticket.id] = max(
                        0, (available_quantity(inventory) or 0) - active_offers
                    )
            if remaining_by_ticket[ticket.id] <= 0:
                continue
            entry.status = WaitlistStatus.PROMOTION_OFFERED
            entry.promotion_offered_at = now()
            entry.promotion_offer_expires_at = now() + timedelta(
                minutes=get_settings().activity_waitlist_promotion_ttl_minutes
            )
            session.add(
                OutboxEvent(
                    topic="activity.waitlist.promotion_offered",
                    aggregate_type="activity_waitlist_entry",
                    aggregate_id=str(entry.id),
                    payload={
                        "waitlist_entry_id": str(entry.id),
                        "registration_id": str(entry.registration_id),
                        "offer_expires_at": entry.promotion_offer_expires_at.isoformat(),
                    },
                )
            )
            offered += 1
            remaining_by_ticket[ticket.id] -= 1
        await session.commit()
        return offered

    async def accept_waitlist_offer(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        registration: ActivityRegistration,
        user: User,
    ) -> ActivityRegistration:
        entry = await session.scalar(
            select(ActivityWaitlistEntry)
            .where(
                ActivityWaitlistEntry.registration_id == registration.id,
                ActivityWaitlistEntry.status == WaitlistStatus.PROMOTION_OFFERED,
            )
            .with_for_update()
        )
        if (
            entry is None
            or entry.promotion_offer_expires_at is None
            or entry.promotion_offer_expires_at <= now()
        ):
            raise VavError(
                "WAITLIST_OFFER_NOT_ACTIVE",
                "No active waitlist offer is available.",
                status_code=409,
            )
        ticket = await session.get(ActivityTicketType, registration.ticket_type_id)
        if ticket is None or not await self._capacity_available(session, ticket):
            raise VavError(
                "ACTIVITY_SOLD_OUT", "The offered place is no longer available.", status_code=409
            )
        approval = ticket.approval_policy_override or activity.approval_policy
        if ticket.eligibility_rules or approval == "rule_assisted":
            approval = "manual"
        payment_timing = ticket.payment_timing_override or activity.payment_timing_policy
        target = (
            RegistrationStatus.PENDING_APPROVAL
            if approval == "manual"
            else RegistrationStatus.PENDING_PAYMENT
        )
        transition_registration(
            session,
            registration,
            target,
            actor_type="user",
            actor_id=user.id,
            reason_code="waitlist_offer_accepted",
        )
        entry.status = WaitlistStatus.PROMOTED
        entry.promoted_at = now()
        await session.commit()
        if approval == "automatic" or payment_timing == "before_approval":
            private = decrypt_private(registration.form_response_encrypted)
            commerce = private.get("_system", {}).get("commerce", {})
            await self._create_order(
                session,
                registration,
                user,
                ticket,
                currency=str(commerce.get("currency", "USD")),
                locale=str(commerce.get("locale", user.preferred_locale)),
                billing_email=str(commerce.get("billing_email", user.display_email)),
            )
        refreshed = await session.get(ActivityRegistration, registration.id)
        return refreshed or registration

    async def offer_waitlist_entry(
        self,
        session: AsyncSession,
        entry: ActivityWaitlistEntry,
        *,
        actor_id: UUID,
        reason: str,
    ) -> ActivityWaitlistEntry:
        await transaction_lock(session, f"activity-waitlist:{entry.ticket_type_id}")
        entry = (
            await session.scalar(
                select(ActivityWaitlistEntry)
                .where(ActivityWaitlistEntry.id == entry.id)
                .with_for_update()
            )
            or entry
        )
        if entry.status != WaitlistStatus.ACTIVE:
            raise VavError(
                "WAITLIST_ENTRY_NOT_OFFERABLE",
                "Only an active waitlist entry can be offered.",
                status_code=409,
            )
        ticket = await session.get(ActivityTicketType, entry.ticket_type_id)
        if ticket is None:
            raise VavError("ACTIVITY_TICKET_NOT_FOUND", "Ticket was not found.", status_code=404)
        inventory = await session.scalar(
            select(InventoryItem)
            .where(InventoryItem.sku_id == ticket.catalog_sku_id)
            .with_for_update()
        )
        if inventory is not None and inventory.inventory_policy != "unlimited":
            active_offers = int(
                await session.scalar(
                    select(func.count(ActivityWaitlistEntry.id)).where(
                        ActivityWaitlistEntry.ticket_type_id == ticket.id,
                        ActivityWaitlistEntry.status == WaitlistStatus.PROMOTION_OFFERED,
                        ActivityWaitlistEntry.promotion_offer_expires_at > now(),
                    )
                )
                or 0
            )
            if (available_quantity(inventory) or 0) - active_offers <= 0:
                raise VavError(
                    "ACTIVITY_SOLD_OUT", "No place is available to offer.", status_code=409
                )
        entry.status = WaitlistStatus.PROMOTION_OFFERED
        entry.promotion_offered_at = now()
        entry.promotion_offer_expires_at = now() + timedelta(
            minutes=get_settings().activity_waitlist_promotion_ttl_minutes
        )
        record_security_event(
            session,
            event_type="activity.waitlist.offer_created",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity_waitlist_entry",
            target_id=entry.id,
            reason=reason,
        )
        session.add(
            OutboxEvent(
                topic="activity.waitlist.promotion_offered",
                aggregate_type="activity_waitlist_entry",
                aggregate_id=str(entry.id),
                payload={
                    "waitlist_entry_id": str(entry.id),
                    "registration_id": str(entry.registration_id),
                    "offer_expires_at": entry.promotion_offer_expires_at.isoformat(),
                },
            )
        )
        await session.commit()
        return entry

    async def decline_waitlist_offer(
        self,
        session: AsyncSession,
        entry: ActivityWaitlistEntry,
        *,
        actor_id: UUID,
        reason: str,
    ) -> ActivityWaitlistEntry:
        await transaction_lock(session, f"activity-waitlist:{entry.ticket_type_id}")
        if entry.status not in {
            WaitlistStatus.ACTIVE,
            WaitlistStatus.PROMOTION_OFFERED,
        }:
            return entry
        entry.status = WaitlistStatus.DECLINED
        registration = await session.get(ActivityRegistration, entry.registration_id)
        if registration and registration.status == RegistrationStatus.WAITLISTED:
            transition_registration(
                session,
                registration,
                RegistrationStatus.CANCELLED,
                actor_type="user",
                actor_id=actor_id,
                reason_code="waitlist_declined",
                reason=reason,
            )
        await session.commit()
        return entry

    async def reorder_waitlist(
        self,
        session: AsyncSession,
        entry: ActivityWaitlistEntry,
        *,
        manual_order_override: int,
        actor_id: UUID,
        reason: str,
    ) -> ActivityWaitlistEntry:
        if not reason.strip():
            raise VavError(
                "WAITLIST_REORDER_REASON_REQUIRED",
                "A reason is required to reorder the waitlist.",
                status_code=422,
            )
        await transaction_lock(session, f"activity-waitlist:{entry.ticket_type_id}")
        before = entry.manual_order_override
        entry.manual_order_override = manual_order_override
        entry.override_reason = reason
        entry.overridden_by = actor_id
        record_security_event(
            session,
            event_type="activity.waitlist.reordered",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity_waitlist_entry",
            target_id=entry.id,
            reason=reason,
            before_state={"manual_order_override": before},
            after_state={"manual_order_override": manual_order_override},
        )
        await session.commit()
        return entry


class ActivityLifecycleService:
    async def advance_due(self, session: AsyncSession) -> int:
        current = now()
        activities = list(
            (
                await session.scalars(
                    select(Activity).where(
                        Activity.status.in_(
                            (
                                ActivityStatus.SCHEDULED,
                                ActivityStatus.PUBLISHED,
                                ActivityStatus.REGISTRATION_OPEN,
                                ActivityStatus.REGISTRATION_CLOSED,
                                ActivityStatus.IN_PROGRESS,
                            )
                        )
                    )
                )
            ).all()
        )
        changed = 0
        for activity in activities:
            target: ActivityStatus | None = None
            if activity.ends_at <= current and activity.status == ActivityStatus.IN_PROGRESS:
                target = ActivityStatus.COMPLETED
            elif (
                activity.starts_at <= current
                and activity.status == ActivityStatus.REGISTRATION_CLOSED
            ):
                target = ActivityStatus.IN_PROGRESS
            elif (
                activity.registration_closes_at
                and activity.registration_closes_at <= current
                and activity.status == ActivityStatus.REGISTRATION_OPEN
            ):
                target = ActivityStatus.REGISTRATION_CLOSED
            elif activity.status == ActivityStatus.SCHEDULED and (
                activity.registration_opens_at is None or activity.registration_opens_at <= current
            ):
                target = ActivityStatus.PUBLISHED
            elif (
                activity.status == ActivityStatus.PUBLISHED
                and activity.registration_closes_at
                and activity.registration_closes_at <= current
            ):
                target = ActivityStatus.REGISTRATION_CLOSED
            elif activity.status == ActivityStatus.PUBLISHED and (
                (activity.registration_opens_at and activity.registration_opens_at <= current)
                or (
                    activity.registration_opens_at is None
                    and (
                        activity.registration_closes_at is None
                        or activity.registration_closes_at > current
                    )
                )
            ):
                target = ActivityStatus.REGISTRATION_OPEN
            if target is None:
                continue
            ensure_activity_transition(activity.status, target)
            activity.status = target
            activity.version += 1
            changed += 1
        expired_entries = list(
            (
                await session.scalars(
                    select(ActivityWaitlistEntry).where(
                        ActivityWaitlistEntry.status == WaitlistStatus.PROMOTION_OFFERED,
                        ActivityWaitlistEntry.promotion_offer_expires_at <= current,
                    )
                )
            ).all()
        )
        for entry in expired_entries:
            entry.status = WaitlistStatus.OFFER_EXPIRED
            registration = await session.get(ActivityRegistration, entry.registration_id)
            if registration and registration.status == RegistrationStatus.WAITLISTED:
                transition_registration(
                    session,
                    registration,
                    RegistrationStatus.EXPIRED,
                    actor_type="system",
                    reason_code="waitlist_offer_expired",
                )
            session.add(
                OutboxEvent(
                    topic="activity.waitlist.offer_expired",
                    aggregate_type="activity_waitlist_entry",
                    aggregate_id=str(entry.id),
                    payload={
                        "waitlist_entry_id": str(entry.id),
                        "registration_id": str(entry.registration_id),
                    },
                )
            )
        await session.commit()
        return changed


class AttendanceService:
    async def credential(
        self, session: AsyncSession, registration: ActivityRegistration
    ) -> tuple[ActivityCheckinCredential, str]:
        if registration.status != RegistrationStatus.CONFIRMED:
            raise VavError(
                "CHECKIN_NOT_ELIGIBLE",
                "Only confirmed registrations can check in.",
                status_code=409,
            )
        activity = await session.get(Activity, registration.activity_id)
        if activity is None:
            raise VavError("ACTIVITY_NOT_FOUND", "Activity was not found.", status_code=404)
        if activity.status in {
            ActivityStatus.CANCELLED,
            ActivityStatus.ARCHIVED,
            ActivityStatus.DRAFT,
        }:
            raise VavError(
                "CHECKIN_NOT_AVAILABLE",
                "Check-in is not available for this activity.",
                status_code=409,
            )
        value = await session.scalar(
            select(ActivityCheckinCredential).where(
                ActivityCheckinCredential.registration_id == registration.id
            )
        )
        if value is None:
            reference = secrets.token_urlsafe(24)
            value = ActivityCheckinCredential(
                registration_id=registration.id,
                public_reference=reference,
                credential_secret_hash=secrets.token_hex(32),
                valid_from=activity.starts_at
                - timedelta(minutes=get_settings().activity_checkin_allow_early_minutes),
                valid_until=activity.ends_at
                + timedelta(minutes=get_settings().activity_checkin_allow_late_minutes),
                status="active",
            )
            session.add(value)
            await session.commit()
        expiry = min(
            int(value.valid_until.timestamp()),
            int(
                (
                    now() + timedelta(seconds=get_settings().activity_checkin_qr_ttl_seconds)
                ).timestamp()
            ),
        )
        if expiry <= int(now().timestamp()):
            raise VavError(
                "CHECKIN_WINDOW_CLOSED", "The check-in window is closed.", status_code=409
            )
        return value, issue_checkin_token(value.public_reference, expires_at=expiry)

    async def perform(
        self,
        session: AsyncSession,
        *,
        token: str | None,
        registration_number_value: str | None,
        session_id: UUID | None,
        action: str,
        actor_id: UUID,
        reason: str | None,
        device_reference: str | None,
    ) -> ActivityRegistration:
        if token:
            reference = verify_checkin_token(token)
            credential = await session.scalar(
                select(ActivityCheckinCredential).where(
                    ActivityCheckinCredential.public_reference == reference
                )
            )
            registration = (
                await session.get(ActivityRegistration, credential.registration_id)
                if credential
                else None
            )
            method = "qr"
            if (
                credential is None
                or credential.status != "active"
                or now() < credential.valid_from
                or now() > credential.valid_until
            ):
                raise VavError(
                    "CHECKIN_TOKEN_INVALID", "Check-in credential is not valid.", status_code=409
                )
        else:
            registration = await session.scalar(
                select(ActivityRegistration).where(
                    ActivityRegistration.registration_number == registration_number_value
                )
            )
            method = "manual"
        if registration is None or registration.status != RegistrationStatus.CONFIRMED:
            raise VavError(
                "CHECKIN_REGISTRATION_NOT_FOUND",
                "Confirmed registration was not found.",
                status_code=404,
            )
        registration = (
            await session.scalar(
                select(ActivityRegistration)
                .where(ActivityRegistration.id == registration.id)
                .with_for_update()
            )
            or registration
        )
        activity = await session.get(Activity, registration.activity_id)
        if activity is None or activity.status in {
            ActivityStatus.CANCELLED,
            ActivityStatus.ARCHIVED,
        }:
            raise VavError(
                "CHECKIN_ACTIVITY_UNAVAILABLE", "The activity is unavailable.", status_code=409
            )
        activity_session = await session.get(ActivitySession, session_id) if session_id else None
        if session_id and (
            activity_session is None or activity_session.activity_id != registration.activity_id
        ):
            raise VavError(
                "CHECKIN_SESSION_INVALID", "The check-in session is invalid.", status_code=409
            )
        if activity_session:
            if activity_session.checkin_opens_at and now() < activity_session.checkin_opens_at:
                raise VavError(
                    "CHECKIN_WINDOW_NOT_OPEN", "The check-in window is not open.", status_code=409
                )
            if activity_session.checkin_closes_at and now() > activity_session.checkin_closes_at:
                raise VavError(
                    "CHECKIN_WINDOW_CLOSED", "The check-in window is closed.", status_code=409
                )
        before = registration.attendance_status
        if action == "revoke":
            if not reason:
                raise VavError(
                    "CHECKIN_REVOKE_REASON_REQUIRED",
                    "A revoke reason is required.",
                    status_code=422,
                )
            if before != AttendanceStatus.CHECKED_IN:
                raise VavError(
                    "CHECKIN_NOT_ACTIVE", "There is no active check-in to revoke.", status_code=409
                )
            registration.attendance_status = AttendanceStatus.CHECKIN_REVOKED
        else:
            latest = await session.scalar(
                select(ActivityCheckinEvent)
                .where(
                    ActivityCheckinEvent.registration_id == registration.id,
                    ActivityCheckinEvent.session_id == session_id
                    if session_id
                    else ActivityCheckinEvent.session_id.is_(None),
                )
                .order_by(ActivityCheckinEvent.occurred_at.desc(), ActivityCheckinEvent.id.desc())
                .limit(1)
            )
            if latest is not None and latest.action == "check_in":
                record_security_event(
                    session,
                    event_type="activity.checkin.duplicate_attempted",
                    actor_type="admin",
                    actor_user_id=actor_id,
                    target_type="activity_registration",
                    target_id=registration.id,
                    metadata={"original_event_id": str(latest.id)},
                )
                await session.commit()
                return registration
            registration.attendance_status = AttendanceStatus.CHECKED_IN
        session.add(
            ActivityCheckinEvent(
                activity_id=registration.activity_id,
                session_id=session_id,
                registration_id=registration.id,
                action=action,
                method=method,
                performed_by=actor_id,
                reason=reason,
                device_reference=device_reference,
            )
        )
        record_security_event(
            session,
            event_type=f"activity.checkin.{action}",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity_registration",
            target_id=registration.id,
            reason=reason,
            before_state={"attendance_status": before},
            after_state={"attendance_status": registration.attendance_status},
        )
        await session.commit()
        return registration


class GroupingService:
    async def create(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        actor_id: UUID,
        plan_name: str,
        target_size: int,
        seed: str,
        checked_in_only: bool,
        publish: bool,
    ) -> ActivityGroupingPlan:
        if target_size > get_settings().activity_grouping_max_group_size:
            raise VavError(
                "GROUP_SIZE_INVALID",
                "Target group size exceeds the configured limit.",
                status_code=422,
            )
        query = select(ActivityRegistration.id).where(
            ActivityRegistration.activity_id == activity.id,
            ActivityRegistration.status == RegistrationStatus.CONFIRMED,
        )
        if checked_in_only:
            query = query.where(ActivityRegistration.attendance_status == "checked_in")
        registration_ids = list(
            (await session.scalars(query.order_by(ActivityRegistration.id))).all()
        )
        chunks = deterministic_groups(registration_ids, target_size=target_size, seed=seed)
        plan = ActivityGroupingPlan(
            activity_id=activity.id,
            plan_name=plan_name,
            grouping_method="random",
            target_group_size=target_size,
            grouping_rules={"checked_in_only": checked_in_only},
            random_seed=seed,
            status="published" if publish else "draft",
            created_by=actor_id,
            locked_by=actor_id if publish else None,
            locked_at=now() if publish else None,
        )
        session.add(plan)
        await session.flush()
        for index, registrations in enumerate(chunks, start=1):
            group = ActivityGroup(
                grouping_plan_id=plan.id,
                group_code=f"G{index:03d}",
                display_name=f"Group {index}",
                capacity=target_size,
            )
            session.add(group)
            await session.flush()
            for registration_id in registrations:
                session.add(
                    ActivityGroupMember(
                        grouping_plan_id=plan.id,
                        group_id=group.id,
                        registration_id=registration_id,
                        assignment_source="random",
                        assigned_by=actor_id,
                        assigned_at=now(),
                    )
                )
        await session.commit()
        return plan

    async def set_locked(
        self,
        session: AsyncSession,
        plan: ActivityGroupingPlan,
        *,
        locked: bool,
        actor_id: UUID,
        reason: str,
    ) -> ActivityGroupingPlan:
        await transaction_lock(session, f"activity-grouping:{plan.id}")
        plan = (
            await session.scalar(
                select(ActivityGroupingPlan)
                .where(ActivityGroupingPlan.id == plan.id)
                .with_for_update()
            )
            or plan
        )
        before = plan.status
        if locked:
            plan.status = "locked"
            plan.locked_by = actor_id
            plan.locked_at = now()
        else:
            plan.status = "draft"
            plan.locked_by = None
            plan.locked_at = None
        plan.version += 1
        record_security_event(
            session,
            event_type=f"activity.grouping.{'locked' if locked else 'unlocked'}",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity_grouping_plan",
            target_id=plan.id,
            reason=reason,
            before_state={"status": before},
            after_state={"status": plan.status},
        )
        await session.commit()
        return plan

    async def move_member(
        self,
        session: AsyncSession,
        *,
        target_group: ActivityGroup,
        registration_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> ActivityGroupMember:
        plan = await session.scalar(
            select(ActivityGroupingPlan)
            .where(ActivityGroupingPlan.id == target_group.grouping_plan_id)
            .with_for_update()
        )
        if plan is None:
            raise VavError(
                "GROUPING_PLAN_NOT_FOUND", "Grouping plan was not found.", status_code=404
            )
        if plan.status == "locked":
            raise VavError(
                "GROUPING_PLAN_LOCKED",
                "Unlock the grouping plan before moving members.",
                status_code=409,
            )
        registration = await session.get(ActivityRegistration, registration_id)
        if registration is None or registration.activity_id != plan.activity_id:
            raise VavError(
                "GROUP_MEMBER_NOT_ELIGIBLE",
                "Registration is not eligible for this group.",
                status_code=409,
            )
        current = await session.scalar(
            select(ActivityGroupMember).where(
                ActivityGroupMember.grouping_plan_id == plan.id,
                ActivityGroupMember.registration_id == registration_id,
                ActivityGroupMember.removed_at.is_(None),
            )
        )
        if current is not None and current.group_id == target_group.id:
            return current
        if current is not None:
            current.removed_at = now()
            current.removed_by = actor_id
            current.removal_reason = reason
        member = ActivityGroupMember(
            grouping_plan_id=plan.id,
            group_id=target_group.id,
            registration_id=registration_id,
            assignment_source="manual",
            assignment_reason=reason,
            assigned_by=actor_id,
            assigned_at=now(),
        )
        session.add(member)
        record_security_event(
            session,
            event_type="activity.grouping.member_moved",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="activity_grouping_plan",
            target_id=plan.id,
            reason=reason,
            before_state={"group_id": str(current.group_id) if current else None},
            after_state={"group_id": str(target_group.id), "registration_id": str(registration_id)},
        )
        await session.commit()
        return member


class MutualChoiceService:
    async def ensure_eligible(
        self,
        session: AsyncSession,
        activity: Activity,
        registration: ActivityRegistration,
    ) -> None:
        current = now()
        user = await session.get(User, registration.user_id)
        if (
            activity.status != ActivityStatus.COMPLETED
            or not activity.post_event_choice_enabled
            or activity.post_event_choice_opens_at is None
            or activity.post_event_choice_closes_at is None
            or current < activity.post_event_choice_opens_at
            or current >= activity.post_event_choice_closes_at
            or registration.status != RegistrationStatus.CONFIRMED
            or user is None
            or user.status != "active"
        ):
            raise VavError(
                "POST_EVENT_PARTICIPANT_NOT_ELIGIBLE",
                "The post-event participant experience is unavailable.",
                status_code=403,
            )
        if (
            get_settings().activity_post_event_require_checkin
            and registration.attendance_status != AttendanceStatus.CHECKED_IN
        ):
            raise VavError("POST_EVENT_CHECKIN_REQUIRED", "Check-in is required.", status_code=403)

    async def directory(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        viewer: ActivityRegistration,
    ) -> list[ActivityParticipantProfile]:
        await self.ensure_eligible(session, activity, viewer)
        profiles = list(
            (
                await session.scalars(
                    select(ActivityParticipantProfile)
                    .join(
                        ActivityRegistration,
                        ActivityRegistration.id == ActivityParticipantProfile.registration_id,
                    )
                    .join(User, User.id == ActivityParticipantProfile.user_id)
                    .where(
                        ActivityParticipantProfile.activity_id == activity.id,
                        ActivityParticipantProfile.visibility_status == "visible",
                        ActivityParticipantProfile.user_id != viewer.user_id,
                        ActivityRegistration.status == RegistrationStatus.CONFIRMED,
                        User.status == "active",
                    )
                    .order_by(
                        ActivityParticipantProfile.display_name, ActivityParticipantProfile.id
                    )
                )
            ).all()
        )
        if get_settings().activity_post_event_require_checkin:
            eligible_registration_ids = set(
                (
                    await session.scalars(
                        select(ActivityRegistration.id).where(
                            ActivityRegistration.id.in_(
                                [profile.registration_id for profile in profiles]
                            ),
                            ActivityRegistration.attendance_status == AttendanceStatus.CHECKED_IN,
                        )
                    )
                ).all()
            )
            profiles = [
                profile
                for profile in profiles
                if profile.registration_id in eligible_registration_ids
            ]
        return profiles

    async def upsert_profile(
        self,
        session: AsyncSession,
        registration: ActivityRegistration,
        *,
        display_name: str,
        introduction: str | None,
        visibility: str,
        consent: bool,
    ) -> ActivityParticipantProfile:
        if not consent:
            raise VavError(
                "PARTICIPANT_PROFILE_CONSENT_REQUIRED",
                "Explicit consent is required.",
                status_code=422,
            )
        if registration.status != RegistrationStatus.CONFIRMED:
            raise VavError(
                "PARTICIPANT_PROFILE_NOT_ELIGIBLE",
                "Confirmed registration is required.",
                status_code=409,
            )
        activity = await session.get(Activity, registration.activity_id)
        if activity is None:
            raise VavError("ACTIVITY_NOT_FOUND", "Activity was not found.", status_code=404)
        await self.ensure_eligible(session, activity, registration)
        profile = await session.scalar(
            select(ActivityParticipantProfile).where(
                ActivityParticipantProfile.activity_id == registration.activity_id,
                ActivityParticipantProfile.user_id == registration.user_id,
            )
        )
        if profile is None:
            profile = ActivityParticipantProfile(
                activity_id=registration.activity_id,
                registration_id=registration.id,
                user_id=registration.user_id,
                display_name=display_name,
                brief_introduction=introduction,
                visibility_status=visibility,
            )
            session.add(profile)
        else:
            profile.display_name = display_name
            profile.brief_introduction = introduction
            profile.visibility_status = visibility
        await session.commit()
        return profile

    async def choose(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        chooser: ActivityRegistration,
        chosen_user_id: UUID,
        choice_value: str,
    ) -> ActivityPostEventChoice:
        current = now()
        await self.ensure_eligible(session, activity, chooser)
        first, second = canonical_user_pair(chooser.user_id, chosen_user_id)
        await transaction_lock(session, f"activity-choice:{activity.id}:{first}:{second}")
        chosen_registration = await session.scalar(
            select(ActivityRegistration).where(
                ActivityRegistration.activity_id == activity.id,
                ActivityRegistration.user_id == chosen_user_id,
                ActivityRegistration.status == RegistrationStatus.CONFIRMED,
            )
        )
        if chosen_registration is None:
            raise VavError("PARTICIPANT_NOT_FOUND", "Participant was not found.", status_code=404)
        await self.ensure_eligible(session, activity, chosen_registration)
        chosen_profile = await session.scalar(
            select(ActivityParticipantProfile).where(
                ActivityParticipantProfile.activity_id == activity.id,
                ActivityParticipantProfile.user_id == chosen_user_id,
                ActivityParticipantProfile.visibility_status == "visible",
            )
        )
        if chosen_profile is None:
            raise VavError("PARTICIPANT_NOT_FOUND", "Participant was not found.", status_code=404)
        restriction = await session.scalar(
            select(ActivityInteractionRestriction).where(
                ActivityInteractionRestriction.user_a_id == first,
                ActivityInteractionRestriction.user_b_id == second,
                ActivityInteractionRestriction.status == "active",
            )
        )
        if restriction:
            raise VavError(
                "PARTICIPANT_INTERACTION_RESTRICTED",
                "This interaction is unavailable.",
                status_code=409,
            )
        existing = await session.scalar(
            select(ActivityPostEventChoice)
            .where(
                ActivityPostEventChoice.activity_id == activity.id,
                ActivityPostEventChoice.chooser_user_id == chooser.user_id,
                ActivityPostEventChoice.chosen_user_id == chosen_user_id,
            )
            .with_for_update()
        )
        if choice_value == "interested" and (
            existing is None or existing.choice != "interested" or existing.status != "active"
        ):
            interested_count = int(
                await session.scalar(
                    select(func.count(ActivityPostEventChoice.id)).where(
                        ActivityPostEventChoice.activity_id == activity.id,
                        ActivityPostEventChoice.chooser_user_id == chooser.user_id,
                        ActivityPostEventChoice.choice == "interested",
                        ActivityPostEventChoice.status == "active",
                    )
                )
                or 0
            )
            if interested_count >= get_settings().activity_post_event_max_interested_choices:
                raise VavError(
                    "POST_EVENT_CHOICE_LIMIT",
                    "Interested choice limit reached.",
                    status_code=409,
                )
        if existing is None:
            existing = ActivityPostEventChoice(
                activity_id=activity.id,
                chooser_user_id=chooser.user_id,
                chosen_user_id=chosen_user_id,
                choice=choice_value,
                status="active",
                submitted_at=current,
            )
            session.add(existing)
            await session.flush()
        else:
            existing.choice = choice_value
            existing.status = "active"
            existing.submitted_at = current
            existing.withdrawn_at = None
            existing.version += 1
        reciprocal = await session.scalar(
            select(ActivityPostEventChoice).where(
                ActivityPostEventChoice.activity_id == activity.id,
                ActivityPostEventChoice.chooser_user_id == chosen_user_id,
                ActivityPostEventChoice.chosen_user_id == chooser.user_id,
                ActivityPostEventChoice.choice == "interested",
                ActivityPostEventChoice.status == "active",
            )
        )
        if choice_value == "interested" and reciprocal:
            match = await session.scalar(
                select(ActivityMutualChoice).where(
                    ActivityMutualChoice.activity_id == activity.id,
                    ActivityMutualChoice.user_a_id == first,
                    ActivityMutualChoice.user_b_id == second,
                )
            )
            if match is None:
                match = ActivityMutualChoice(
                    activity_id=activity.id,
                    user_a_id=first,
                    user_b_id=second,
                    first_choice_id=existing.id,
                    second_choice_id=reciprocal.id,
                    status="matched_private",
                    matched_at=current,
                )
                session.add(match)
                session.add(
                    OutboxEvent(
                        topic="activity.mutual_choice.created",
                        aggregate_type="activity_mutual_choice",
                        aggregate_id=str(match.id),
                        payload={
                            "activity_id": str(activity.id),
                            "user_a_id": str(first),
                            "user_b_id": str(second),
                            "contact_disclosed": False,
                        },
                    )
                )
            elif match.status != "matched_private":
                match.status = "matched_private"
                match.matched_at = current
                match.first_choice_id = existing.id
                match.second_choice_id = reciprocal.id
                session.add(
                    OutboxEvent(
                        topic="activity.mutual_choice.created",
                        aggregate_type="activity_mutual_choice",
                        aggregate_id=str(match.id),
                        payload={
                            "activity_id": str(activity.id),
                            "user_a_id": str(first),
                            "user_b_id": str(second),
                            "contact_disclosed": False,
                        },
                    )
                )
        elif choice_value != "interested":
            match = await session.scalar(
                select(ActivityMutualChoice).where(
                    ActivityMutualChoice.activity_id == activity.id,
                    ActivityMutualChoice.user_a_id == first,
                    ActivityMutualChoice.user_b_id == second,
                    ActivityMutualChoice.status == "matched_private",
                )
            )
            if match is not None:
                match.status = "withdrawn"
        await session.commit()
        return existing

    async def withdraw(
        self,
        session: AsyncSession,
        *,
        activity: Activity,
        chooser: ActivityRegistration,
        chosen_user_id: UUID,
    ) -> None:
        await self.ensure_eligible(session, activity, chooser)
        first, second = canonical_user_pair(chooser.user_id, chosen_user_id)
        await transaction_lock(session, f"activity-choice:{activity.id}:{first}:{second}")
        choice = await session.scalar(
            select(ActivityPostEventChoice)
            .where(
                ActivityPostEventChoice.activity_id == activity.id,
                ActivityPostEventChoice.chooser_user_id == chooser.user_id,
                ActivityPostEventChoice.chosen_user_id == chosen_user_id,
            )
            .with_for_update()
        )
        if choice is None or choice.status != "active":
            return
        choice.status = "withdrawn"
        choice.withdrawn_at = now()
        choice.version += 1
        match = await session.scalar(
            select(ActivityMutualChoice).where(
                ActivityMutualChoice.activity_id == activity.id,
                ActivityMutualChoice.user_a_id == first,
                ActivityMutualChoice.user_b_id == second,
                ActivityMutualChoice.status == "matched_private",
            )
        )
        if match is not None:
            match.status = "withdrawn"
        record_security_event(
            session,
            event_type="activity.post_event_choice.withdrawn",
            actor_type="user",
            actor_user_id=chooser.user_id,
            target_type="activity",
            target_id=activity.id,
        )
        await session.commit()


publication_service = ActivityPublicationService()
registration_service = ActivityRegistrationService()
activity_lifecycle_service = ActivityLifecycleService()
attendance_service = AttendanceService()
grouping_service = GroupingService()
mutual_choice_service = MutualChoiceService()
