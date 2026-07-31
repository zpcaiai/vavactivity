from vav.modules.identity.permissions import ROLE_PERMISSIONS


def test_catalog_manager_does_not_receive_high_risk_inventory_adjustment() -> None:
    permissions = ROLE_PERMISSIONS["catalog_manager"]

    assert "catalog.products.create" in permissions
    assert "catalog.inventory.adjust" not in permissions
    assert "catalog.coupons.export" not in permissions


def test_member_has_no_administrator_permissions() -> None:
    assert ROLE_PERMISSIONS["member"] == set()
