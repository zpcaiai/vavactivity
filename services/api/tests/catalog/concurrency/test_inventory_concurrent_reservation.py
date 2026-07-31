import asyncio
from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.catalog import InventoryItem, Product, ProductSku
from vav.models.identity import User
from vav.modules.catalog.inventory import available_quantity, inventory_service
from vav.modules.identity.domain import UserStatus


async def create_last_seat() -> tuple[ProductSku, InventoryItem]:
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"race-{suffix}@example.com",
            display_email=f"race-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"RACE-{suffix.upper()}",
            product_type="activity_ticket",
            fulfillment_type="event_admission",
            internal_name="Last seat test",
            status="draft",
            visibility="public",
            default_locale="zh-CN",
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(product)
        await session.flush()
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"RACE-SKU-{suffix.upper()}",
            internal_name="Last seat",
            billing_type="one_time",
            status="active",
            fulfillment_configuration={
                "activity_id": str(uuid4()),
                "ticket_type": "general",
            },
            inventory_policy="finite",
        )
        session.add(sku)
        await session.flush()
        item = InventoryItem(
            sku_id=sku.id,
            inventory_policy="finite",
            total_capacity=1,
            reserved_quantity=0,
            sold_quantity=0,
            safety_stock=0,
            overselling_allowed=False,
            oversell_limit=0,
        )
        session.add(item)
        await session.commit()
        return sku, item


@pytest.mark.asyncio
async def test_only_one_request_can_reserve_the_last_seat() -> None:
    sku, item = await create_last_seat()

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                reservation = await inventory_service.reserve(
                    session,
                    sku_id=sku.id,
                    quantity=1,
                    user_id=None,
                    anonymous_session_id=uuid4(),
                    pricing_quote_id=None,
                )
                return "success" if reservation is not None else "not_required"
            except VavError as error:
                return error.code

    outcomes = await asyncio.gather(attempt(), attempt())
    assert sorted(outcomes) == ["INVENTORY_NOT_AVAILABLE", "success"]
    async with session_factory() as session:
        persisted = await session.get(InventoryItem, item.id)
        assert persisted is not None
        assert persisted.reserved_quantity == 1
        assert available_quantity(persisted) == 0
