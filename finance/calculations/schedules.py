"""Recurring schedule math: due-date occurrences and monthly equivalents."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from typing import Iterator

# Exact monthly multipliers (Fraction keeps cents math exact before rounding)
MONTHLY_FACTOR: dict[str, Fraction] = {
    "weekly": Fraction(52, 12),
    "biweekly": Fraction(26, 12),
    "twice_monthly": Fraction(2),
    "monthly": Fraction(1),
    "quarterly": Fraction(1, 3),
    "annual": Fraction(1, 12),
}


class ScheduleError(ValueError):
    pass


def monthly_equivalent_cents(amount_cents: int, frequency: str) -> int:
    try:
        f = MONTHLY_FACTOR[frequency]
    except KeyError as exc:
        raise ScheduleError(f"Unknown frequency: {frequency}") from exc
    v = amount_cents * f
    # round half away from zero
    return int(v + Fraction(1, 2)) if v >= 0 else -int(-v + Fraction(1, 2))


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _add_months(d: date, months: int, day: int) -> date:
    m = d.month - 1 + months
    return _clamp_day(d.year + m // 12, m % 12 + 1, day)


@dataclass(frozen=True)
class Schedule:
    frequency: str
    due_day: int | None = None
    due_day_2: int | None = None
    anchor_date: date | None = None

    def validate(self) -> None:
        if self.frequency not in MONTHLY_FACTOR:
            raise ScheduleError(f"Unknown frequency: {self.frequency}")
        for d in (self.due_day, self.due_day_2):
            if d is not None and not 1 <= d <= 31:
                raise ScheduleError("Due day must be between 1 and 31")
        if self.frequency in ("weekly", "biweekly", "quarterly", "annual") and not self.anchor_date:
            raise ScheduleError(f"{'An' if self.frequency[0] in 'aeiou' else 'A'} {self.frequency} schedule needs a first due date")

    @property
    def is_dated(self) -> bool:
        """True when enough information exists to compute due dates."""
        if self.frequency in ("monthly", "twice_monthly"):
            return self.due_day is not None or self.anchor_date is not None
        return self.anchor_date is not None

    def occurrences(self, start: date, end: date) -> Iterator[date]:
        """Yield due dates d with start <= d <= end."""
        if not self.is_dated or end < start:
            return
        f = self.frequency
        if f in ("weekly", "biweekly"):
            step = timedelta(days=7 if f == "weekly" else 14)
            a = self.anchor_date
            if a < start:
                k = -(-(start - a).days // step.days)  # ceil
                a = a + step * k
            while a <= end:
                yield a
                a += step
        elif f in ("monthly", "quarterly", "annual"):
            months = {"monthly": 1, "quarterly": 3, "annual": 12}[f]
            day = self.due_day or self.anchor_date.day
            if self.anchor_date:
                base = self.anchor_date
                d, i = base, 0
                # fast-forward
                if base < start:
                    i = max(0, ((start.year - base.year) * 12 + start.month - base.month) // months - 1)
                while True:
                    d = _add_months(base, i * months, day)
                    if d > end:
                        break
                    if d >= start:
                        yield d
                    i += 1
            else:  # monthly with due_day only
                cur = date(start.year, start.month, 1)
                while True:
                    d = _clamp_day(cur.year, cur.month, day)
                    if d > end:
                        break
                    if d >= start:
                        yield d
                    cur = _add_months(cur, 1, 1)
        elif f == "twice_monthly":
            d1 = self.due_day or (self.anchor_date.day if self.anchor_date else 1)
            d2 = self.due_day_2 or (d1 + 15 if d1 <= 13 else d1 - 15)
            days = sorted({d1, d2})
            cur = date(start.year, start.month, 1)
            while cur <= end:
                for day in days:
                    d = _clamp_day(cur.year, cur.month, day)
                    if start <= d <= end:
                        yield d
                cur = _add_months(cur, 1, 1)

    def next_due(self, on_or_after: date) -> date | None:
        return next(self.occurrences(on_or_after, on_or_after + timedelta(days=400)), None)
