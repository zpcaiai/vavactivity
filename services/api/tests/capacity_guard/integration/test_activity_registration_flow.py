from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.activities import Activity, ActivityTicketType
from vav.models.catalog import InventoryItem, Product, ProductSku
from vav.models.identity import User
from vav.modules.activities.schemas import RegistrationCreateRequest
from vav.modules.activities.service import registration_service
from vav.modules.capacity_guard import service as capacity_guard_service


@pytest.mark.asyncio
async def test_registration_owns_the_capacity_hold_and_rejection_promotes_the_queue() -> None:
    suffix = uuid4().hex
    current = datetime.now(UTC)
    async with session_factory() as session:
        owner = User(
            email=f"capacity-owner-{suffix}@example.com",
            display_email=f"capacity-owner-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        first_user = User(
            email=f"capacity-first-{suffix}@example.com",
            display_email=f"capacity-first-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        queued_user = User(
            email=f"capacity-queued-{suffix}@example.com",
            display_email=f"capacity-queued-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        session.add_all([owner, first_user, queued_user])
        await session.flush()

        product = Product(
            product_code=f"CAPACITY-{suffix.upper()}",
            product_type="activity_ticket",
            fulfillment_type="event_admission",
            internal_name="Capacity integration ticket",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(product)
        await session.flush()
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"CAPACITY-SKU-{suffix.upper()}",
            internal_name="Capacity integration seat",
            billing_type="free",
            status="active",
            fulfillment_configuration={},
            inventory_policy="finite",
        )
        session.add(sku)
        await session.flush()
        session.add(
            InventoryItem(
                sku_id=sku.id,
                inventory_policy="finite",
                total_capacity=2,
                reserved_quantity=0,
                sold_quantity=0,
                safety_stock=1,
                overselling_allowed=False,
                oversell_limit=0,
            )
        )
        activity = Activity(
            activity_code=f"capacity-{suffix}",
            internal_name="Capacity integration activity",
            activity_format="online",
            status="registration_open",
            visibility="public",
            default_locale="zh-CN",
            timezone="UTC",
            registration_opens_at=current - timedelta(hours=1),
            registration_closes_at=current + timedelta(days=1),
            starts_at=current + timedelta(days=2),
            ends_at=current + timedelta(days=2, hours=1),
            approval_policy="manual",
            payment_timing_policy="after_approval",
            waitlist_enabled=True,
            post_event_choice_enabled=False,
            cancellation_policy_snapshot={"default": "manual_review"},
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(activity)
        await session.flush()
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
        await session.commit()

        first = await registration_service.create(
            session,
            activity=activity,
            user=first_user,
            request=RegistrationCreateRequest(
                ticket_type_id=ticket.id,
                idempotency_key=f"first-{suffix}",
            ),
        )
        queued = await registration_service.create(
            session,
            activity=activity,
            user=queued_user,
            request=RegistrationCreateRequest(
                ticket_type_id=ticket.id,
                idempotency_key=f"queued-{suffix}",
            ),
        )

        assert first.status == "pending_approval"
        assert queued.status == "waitlisted"
        before = (
            await session.execute(
                text(
                    "SELECT capacity,is_unlimited,held_seats,waitlisted_count "
                    "FROM activity_capacity_counters WHERE ticket_type_id=:id"
                ),
                {"id": str(ticket.id)},
            )
        ).one()
        assert tuple(before) == (1, False, 1, 1)

        await registration_service.review(
            session,
            first,
            action="reject",
            reason_code="manual_review_rejected",
            user_message="The registration was not approved.",
            private_notes=None,
            actor_id=owner.id,
        )

        after = (
            await session.execute(
                text(
                    "SELECT held_seats,waitlisted_count "
                    "FROM activity_capacity_counters WHERE ticket_type_id=:id"
                ),
                {"id": str(ticket.id)},
            )
        ).one()
        offer_state = (
            await session.execute(
                text(
                    "SELECT state FROM activity_waitlist_promotion_offers "
                    "WHERE registration_id=:registration_id"
                ),
                {"registration_id": str(queued.id)},
            )
        ).scalar_one()
        assert tuple(after) == (1, 1)
        assert offer_state == "pending"


@pytest.mark.asyncio
async def test_lazy_counter_distinguishes_finite_zero_from_unlimited_without_inventory() -> None:
    suffix = uuid4().hex
    current = datetime.now(UTC)
    async with session_factory() as session:
        owner = User(
            email=f"capacity-mode-owner-{suffix}@example.com",
            display_email=f"capacity-mode-owner-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        session.add(owner)
        await session.flush()
        product = Product(
            product_code=f"CAPACITY-MODE-{suffix.upper()}",
            product_type="activity_ticket",
            fulfillment_type="event_admission",
            internal_name="Capacity mode integration ticket",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(product)
        await session.flush()
        finite_sku = ProductSku(
            product_id=product.id,
            sku_code=f"CAPACITY-ZERO-{suffix.upper()}",
            internal_name="Finite zero seat",
            billing_type="free",
            status="active",
            fulfillment_configuration={},
            inventory_policy="finite",
        )
        unlimited_sku = ProductSku(
            product_id=product.id,
            sku_code=f"CAPACITY-UNLIMITED-{suffix.upper()}",
            internal_name="Unlimited seat",
            billing_type="free",
            status="active",
            fulfillment_configuration={},
            inventory_policy="unlimited",
        )
        session.add_all([finite_sku, unlimited_sku])
        await session.flush()
        session.add(
            InventoryItem(
                sku_id=finite_sku.id,
                inventory_policy="finite",
                total_capacity=0,
                reserved_quantity=0,
                sold_quantity=0,
                safety_stock=0,
                overselling_allowed=False,
                oversell_limit=0,
            )
        )
        activity = Activity(
            activity_code=f"capacity-mode-{suffix}",
            internal_name="Capacity mode integration activity",
            activity_format="online",
            status="draft",
            visibility="private",
            default_locale="zh-CN",
            timezone="UTC",
            starts_at=current + timedelta(days=2),
            ends_at=current + timedelta(days=2, hours=1),
            approval_policy="automatic",
            payment_timing_policy="on_registration",
            waitlist_enabled=True,
            post_event_choice_enabled=False,
            cancellation_policy_snapshot={"default": "manual_review"},
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(activity)
        await session.flush()
        finite_ticket = ActivityTicketType(
            activity_id=activity.id,
            ticket_code="finite-zero",
            internal_name="Finite zero",
            catalog_product_id=product.id,
            catalog_sku_id=finite_sku.id,
            status="active",
            waitlist_enabled=True,
            max_quantity_per_user=1,
            eligibility_rules={},
            capacity_display_mode="status_only",
        )
        unlimited_ticket = ActivityTicketType(
            activity_id=activity.id,
            ticket_code="unlimited",
            internal_name="Unlimited",
            catalog_product_id=product.id,
            catalog_sku_id=unlimited_sku.id,
            status="active",
            waitlist_enabled=True,
            max_quantity_per_user=1,
            eligibility_rules={},
            capacity_display_mode="status_only",
        )
        session.add_all([finite_ticket, unlimited_ticket])
        await session.flush()

        finite = await capacity_guard_service._lock_counter(session, finite_ticket.id)
        unlimited = await capacity_guard_service._lock_counter(session, unlimited_ticket.id)

        assert finite["capacity"] == 0
        assert finite["is_unlimited"] is False
        assert unlimited["capacity"] == 0
        assert unlimited["is_unlimited"] is True

        finite_payload = await capacity_guard_service.get_capacity(session, finite_ticket.id)
        unlimited_payload = await capacity_guard_service.get_capacity(session, unlimited_ticket.id)

        assert finite_payload["remaining_seats"] == 0
        assert finite_payload["is_unlimited"] is False
        assert "remaining_seats" not in unlimited_payload
        assert unlimited_payload["is_unlimited"] is True
