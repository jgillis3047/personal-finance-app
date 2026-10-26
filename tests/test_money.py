from decimal import Decimal

import pytest

from finance.utils.money import MoneyError, fmt, from_cents, to_cents


@pytest.mark.parametrize("raw,cents", [
    (0, 0), (12, 1200), (12.5, 1250), (0.1 + 0.2, 30), ("1,234.56", 123456), ("$1,234.56", 123456),
    ("(45.00)", -4500), ("45.00-", -4500), ("-12", -1200), (Decimal("2.005"), 201), ("13848.33", 1384833),
    (" 7 ", 700),
])
def test_to_cents(raw, cents):
    assert to_cents(raw) == cents


@pytest.mark.parametrize("bad", [None, "", "abc", "1.2.3", True, "nan", float("inf")])
def test_to_cents_rejects_non_numbers(bad):
    with pytest.raises(MoneyError):
        to_cents(bad)


def test_formatting():
    assert fmt(123456) == "$1,234.56"
    assert fmt(-3084263) == "-$30,842.63"
    assert fmt(48900, signed=True) == "+$489.00"
    assert fmt(0, signed=True) == "$0.00"
    assert fmt(None) == "—"
    assert fmt(123456, whole=True) == "$1,235"
    assert from_cents(1) == Decimal("0.01")
