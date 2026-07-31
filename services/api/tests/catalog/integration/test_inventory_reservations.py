from uuid import uuid4

import pytest

from vav.core.database import session_factory
from vav.models.catalog import InventoryItem, Product, ProductSku
from vav.models.identity import User
from vav.modules.catalog.inventory import available_quantity, inventory_service
from vav.modules.identity.domain import UserStatus


async def create_inventory(capacity: int = 2) -> tuple[ProductSku, InventoryItem]:
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"inventory-{suffix}@example.com",
            display_email=f"inventory-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"INV-{suffix.upper()}",
            product_type="digital_service",
            fulfillment_type="digital_access",
            internal_name="Inventory test",
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
            sku_code=f"INV-SKU-{suffix.upper()}",
            internal_name="Inventory test SKU",
            billing_type="one_time",
            status="active",
            fulfillment_configuration={"service_code": "inventory-test"},
            inventory_policy="finite",
        )
        session.add(sku)
        await session.flush()
        item = InventoryItem(
            sku_id=sku.id,
            inventory_policy="finite",
            total_capacity=capacity,
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
async def test_reservation_confirm_is_idempotent() -> None:
    sku, _ = await create_inventory()
    async with session_factory() as session:
        reservation = await inventory_service.reserve(
            session,
            sku_id=sku.id,
            quantity=1,
            user_id=None,
            anonymous_session_id=uuid4(),
            pricing_quote_id=None,
        )
        assert reservation is not None
        reservation_id = reservation.id
    async with session_factory() as session:
        first = await inventory_service.confirm(session, reservation_id)
        second = await inventory_service.confirm(session, reservation_id)
        assert first.status == second.status == "confirmed"
        item = await session.get(InventoryItem, first.inventory_item_id)
        assert item is not None
        assert item.reserved_quantity == 0
        assert item.sold_quantity == 1
        assert available_quantity(item) == 1


@pytest.mark.asyncio
async def test_expired_reservation_releases_capacity() -> None:
    sku, _ = await create_inventory(capacity=1)
    async with session_factory() as session:
        reservation = await inventory_service.reserve(
            session,
            sku_id=sku.id,
            quantity=1,
            user_id=None,
            anonymous_session_id=uuid4(),
            pricing_quote_id=None,
        )
        assert reservation is not None
        reservation_id = reservation.id
    async with session_factory() as session:
        released = await inventory_service.release(
            session,
            reservation_id,
            reason="Integration test forces expiration.",
            expired=True,
        )
        item = await session.get(InventoryItem, released.inventory_item_id)
        assert released.status == "expired"
        assert item is not None
        assert item.reserved_quantity == 0
        assert available_quantity(item) == 1
