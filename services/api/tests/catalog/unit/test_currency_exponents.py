from decimal import Decimal


def to_minor(value: str, exponent: int) -> int:
    return int(Decimal(value) * (Decimal(10) ** exponent))


def test_supported_currency_exponents() -> None:
    assert to_minor("19.99", 2) == 1999
    assert to_minor("199.00", 2) == 19900
    assert to_minor("1200", 0) == 1200
    assert to_minor("299.50", 2) == 29950
