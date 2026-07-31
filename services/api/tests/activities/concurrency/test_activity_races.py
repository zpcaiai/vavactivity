import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from vav.core.database import session_factory
from vav.models.activities import (
    Activity,
    ActivityCheckinEvent,
    ActivityMutualChoice,
    ActivityParticipantProfile,
    ActivityRegistration,
    ActivityTicketType,
    ActivityWaitlistEntry,
)
from vav.models.catalog import InventoryItem, Product, ProductSku
from vav.models.identity import User
from vav.modules.activities.service import (
    attendance_service,
    mutual_choice_service,
    registration_service,
)


async def _create_activity_graph(*, waitlisted_users: int = 0) -> dict[str, object]:
    suffix = uuid4().hex
    current = datetime.now(UTC)
    starts_at = current + timedelta(days=2) if waitlisted_users else current - timedelta(hours=2)
    ends_at = starts_at + timedelta(hours=1)
    post_event_opens_at = ends_at if waitlisted_users else current - timedelta(minutes=30)
    post_event_closes_at = post_event_opens_at + timedelta(hours=3)
    async with session_factory() as session:
        actor = User(
            email=f"activity-race-actor-{suffix}@example.com",
            display_email=f"activity-race-actor-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"ACT-RACE-{suffix.upper()}",
            product_type="activity_ticket",
            fulfillment_type="event_admission",
            internal_name="Activity race ticket",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(product)
        await session.flush()
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"ACT-RACE-SKU-{suffix.upper()}",
            internal_name="Activity race seat",
            billing_type="free",
            status="active",
            fulfillment_configuration={"activity_id": str(uuid4()), "ticket_type": "general"},
            inventory_policy="finite",
        )
        session.add(sku)
        await session.flush()
        inventory = InventoryItem(
            sku_id=sku.id,
            inventory_policy="finite",
            total_capacity=1,
            reserved_quantity=0,
            sold_quantity=0,
            safety_stock=0,
            overselling_allowed=False,
            oversell_limit=0,
        )
        session.add(inventory)
        activity = Activity(
            activity_code=f"activity-race-{suffix}",
            internal_name="Activity concurrency test",
            activity_format="online",
            status="completed" if waitlisted_users == 0 else "registration_open",
            visibility="public",
            default_locale="zh-CN",
            timezone="UTC",
            registration_opens_at=starts_at - timedelta(days=2),
            registration_closes_at=starts_at - timedelta(hours=1),
            starts_at=starts_at,
            ends_at=ends_at,
            post_event_choice_opens_at=post_event_opens_at,
            post_event_choice_closes_at=post_event_closes_at,
            approval_policy="automatic",
            payment_timing_policy="not_required",
            waitlist_enabled=True,
            post_event_choice_enabled=True,
            cancellation_policy_snapshot={"default": "manual_review"},
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(activity)
        await session.flush()
        sku.fulfillment_configuration = {
            "activity_id": str(activity.id),
            "ticket_type": "general",
        }
        ticket = ActivityTicketType(
            activity_id=activity.id,
            ticket_code="general",
            internal_name="General",
            catalog_product_id=product.id,
            catalog_sku_id=sku.id,
            status="active",
            waitlist_enabled=True,
            max_quantity_per_user=1,
            eligibility_rules={},
            capacity_display_mode="status_only",
        )
        session.add(ticket)
        await session.flush()
        users: list[User] = []
        registrations: list[ActivityRegistration] = []
        for index in range(max(2, waitlisted_users)):
            user = User(
                email=f"activity-race-{suffix}-{index}@example.com",
                display_email=f"activity-race-{suffix}-{index}@example.com",
                password_hash=None,
                status="active",
            )
            session.add(user)
            await session.flush()
            registration = ActivityRegistration(
                registration_number=f"REG-RACE-{suffix[:12]}-{index}",
                activity_id=activity.id,
                ticket_type_id=ticket.id,
                user_id=user.id,
                status="waitlisted" if waitlisted_users else "confirmed",
                attendance_status="not_checked_in" if waitlisted_users else "checked_in",
                form_schema_version=1,
                form_response_encrypted="integration-test-not-read",
                confirmed_at=None if waitlisted_users else current,
            )
            session.add(registration)
            await session.flush()
            if waitlisted_users:
                session.add(
                    ActivityWaitlistEntry(
                        activity_id=activity.id,
                        ticket_type_id=ticket.id,
                        user_id=user.id,
                        registration_id=registration.id,
                        status="active",
                        sequence_number=index + 1,
                        joined_at=current + timedelta(seconds=index),
                    )
                )
            else:
                session.add(
                    ActivityParticipantProfile(
                        activity_id=activity.id,
                        registration_id=registration.id,
                        user_id=user.id,
                        display_name=f"Participant {index}",
                        visibility_status="visible",
                    )
                )
            users.append(user)
            registrations.append(registration)
        await session.commit()
        return {
            "actor_id": actor.id,
            "activity_id": activity.id,
            "ticket_id": ticket.id,
            "user_ids": [user.id for user in users],
            "registration_ids": [registration.id for registration in registrations],
            "registration_number": registrations[0].registration_number,
        }


@pytest.mark.asyncio
async def test_two_workers_offer_only_one_released_place() -> None:
    graph = await _create_activity_graph(waitlisted_users=2)

    async def offer() -> int:
        async with session_factory() as session:
            return await registration_service.offer_waitlist_places(session)

    await asyncio.gather(offer(), offer())
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(ActivityWaitlistEntry.id)).where(
                ActivityWaitlistEntry.ticket_type_id == graph["ticket_id"],
                ActivityWaitlistEntry.status == "promotion_offered",
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_duplicate_concurrent_checkin_appends_one_attendance_event() -> None:
    graph = await _create_activity_graph()
    registration_id = UUID(str(graph["registration_ids"][0]))  # type: ignore[index]
    registration_number = str(graph["registration_number"])
    actor_id = UUID(str(graph["actor_id"]))

    async def checkin() -> None:
        async with session_factory() as session:
            await attendance_service.perform(
                session,
                token=None,
                registration_number_value=registration_number,
                session_id=None,
                action="check_in",
                actor_id=actor_id,
                reason=None,
                device_reference="pytest",
            )

    await asyncio.gather(checkin(), checkin())
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(ActivityCheckinEvent.id)).where(
                ActivityCheckinEvent.registration_id == registration_id,
                ActivityCheckinEvent.action == "check_in",
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_reciprocal_choices_create_one_private_match() -> None:
    graph = await _create_activity_graph()
    activity_id = UUID(str(graph["activity_id"]))
    user_ids = [UUID(str(value)) for value in graph["user_ids"]]  # type: ignore[union-attr]
    registration_ids = [
        UUID(str(value))
        for value in graph["registration_ids"]  # type: ignore[union-attr]
    ]

    async def choose(registration_id: UUID, chosen_user_id: UUID) -> None:
        async with session_factory() as session:
            activity = await session.get(Activity, activity_id)
            registration = await session.get(ActivityRegistration, registration_id)
            assert activity is not None and registration is not None
            await mutual_choice_service.choose(
                session,
                activity=activity,
                chooser=registration,
                chosen_user_id=chosen_user_id,
                choice_value="interested",
            )

    await asyncio.gather(
        choose(registration_ids[0], user_ids[1]),
        choose(registration_ids[1], user_ids[0]),
    )
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(ActivityMutualChoice.id)).where(
                ActivityMutualChoice.activity_id == activity_id
            )
        )
    assert count == 1
