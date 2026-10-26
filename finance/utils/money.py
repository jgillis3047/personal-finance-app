"""Money helpers. All amounts are stored as integer cents to avoid float drift."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENT = Decimal("0.01")


class MoneyError(ValueError):
    pass


def to_cents(value) -> int:
    """Convert a user/import value (str, int, float, Decimal) into integer cents.

    Accepts strings like "$1,234.56", "(45.00)" (accounting negative) and "-12".
    Raises MoneyError for anything that is not a number — never guesses.
    """
    if value is None:
        raise MoneyError("Amount is missing")
    if isinstance(value, bool):
        raise MoneyError("Amount cannot be a boolean")
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        value = repr(value)
    if isinstance(value, Decimal):
        d = value
    else:
        s = str(value).strip()
        if not s:
            raise MoneyError("Amount is empty")
        negative = False
        if s.startswith("(") and s.endswith(")"):
            negative, s = True, s[1:-1]
        s = s.replace("$", "").replace(",", "").replace(" ", "")
        if s.endswith("-"):  # some banks print "45.00-"
            negative, s = True, s[:-1]
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise MoneyError(f"Not a valid amount: {value!r}") from exc
        if negative:
            d = -d
    if not d.is_finite():
        raise MoneyError(f"Not a valid amount: {value!r}")
    return int((d.quantize(_CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


def from_cents(cents: int | None) -> Decimal:
    if cents is None:
        return Decimal("0.00")
    return (Decimal(cents) / 100).quantize(_CENT)


def fmt(cents: int | None, *, signed: bool = False, whole: bool = False) -> str:
    """Format cents as a currency string, e.g. -123456 -> "-$1,234.56"."""
    if cents is None:
        return "—"
    d = from_cents(cents)
    neg = d < 0
    d = abs(d)
    body = f"{d:,.0f}" if whole else f"{d:,.2f}"
    sign = "-" if neg else ("+" if signed and d != 0 else "")
    return f"{sign}${body}"
