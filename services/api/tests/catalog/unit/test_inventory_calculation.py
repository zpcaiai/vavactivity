from vav.models.catalog import InventoryItem
from vav.modules.catalog.inventory import available_quantity


def test_finite_inventory_accounts_for_reservations_sales_and_safety_stock() -> None:
    item = InventoryItem(
        sku_id=None,  # type: ignore[arg-type]
        inventory_policy="finite",
        total_capacity=20,
        reserved_quantity=4,
        sold_quantity=7,
        safety_stock=2,
        overselling_allowed=False,
        oversell_limit=0,
    )
    assert available_quantity(item) == 7


def test_controlled_oversell_adds_only_the_configured_limit() -> None:
    item = InventoryItem(
        sku_id=None,  # type: ignore[arg-type]
        inventory_policy="finite",
        total_capacity=1,
        reserved_quantity=1,
        sold_quantity=0,
        safety_stock=0,
        overselling_allowed=True,
        oversell_limit=2,
    )
    assert available_quantity(item) == 2
