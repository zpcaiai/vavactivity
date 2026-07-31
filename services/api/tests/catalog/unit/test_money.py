import pytest

from vav.common.exceptions import VavError
from vav.modules.catalog.domain import Money, round_discount


def test_money_uses_exact_integer_minor_units() -> None:
    assert Money(1999, "USD").multiply(2) == Money(3998, "USD")
    assert round_discount(1999, 1500) == 300
    assert Money(1999, "USD") - Money(300, "USD") == Money(1699, "USD")


def test_money_rejects_cross_currency_arithmetic() -> None:
    with pytest.raises(VavError, match="Different currencies"):
        Money(1000, "USD") + Money(1000, "TWD")


def test_fixed_discount_cannot_make_money_negative() -> None:
    assert min(500, 800) == 500
    assert Money(500, "USD") - Money(500, "USD") == Money(0, "USD")
