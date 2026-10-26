from datetime import date

import pytest

from finance.calculations.schedules import Schedule, ScheduleError, monthly_equivalent_cents


def occ(s, a, b):
    return list(s.occurrences(a, b))


def test_monthly_due_day_clamps_to_month_end():
    s = Schedule("monthly", due_day=31)
    assert occ(s, date(2027, 1, 1), date(2027, 4, 30)) == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]
    assert occ(s, date(2028, 2, 1), date(2028, 2, 29)) == [date(2028, 2, 29)]  # leap year


def test_monthly_window_bounds_inclusive():
    s = Schedule("monthly", due_day=25)
    assert occ(s, date(2026, 10, 25), date(2026, 11, 25)) == [date(2026, 10, 25), date(2026, 11, 25)]
    assert s.next_due(date(2026, 10, 26)) == date(2026, 11, 25)


def test_monthly_from_anchor_keeps_day_after_short_month():
    s = Schedule("monthly", anchor_date=date(2027, 1, 31))
    assert occ(s, date(2027, 2, 1), date(2027, 3, 31)) == [date(2027, 2, 28), date(2027, 3, 31)]


def test_weekly_and_biweekly():
    w = Schedule("weekly", anchor_date=date(2026, 10, 2))
    assert occ(w, date(2026, 10, 10), date(2026, 10, 24)) == [date(2026, 10, 16), date(2026, 10, 23)]
    b = Schedule("biweekly", anchor_date=date(2026, 10, 2))
    assert occ(b, date(2026, 10, 1), date(2026, 11, 15)) == [date(2026, 10, 2), date(2026, 10, 16),
                                                              date(2026, 10, 30), date(2026, 11, 13)]
    # anchor in the future: nothing before it
    assert occ(b, date(2026, 9, 1), date(2026, 9, 30)) == []


def test_twice_monthly():
    s = Schedule("twice_monthly", due_day=1, due_day_2=15)
    assert occ(s, date(2026, 11, 1), date(2026, 12, 1)) == [date(2026, 11, 1), date(2026, 11, 15), date(2026, 12, 1)]
    s2 = Schedule("twice_monthly", due_day=15, due_day_2=31)
    assert occ(s2, date(2027, 2, 1), date(2027, 2, 28)) == [date(2027, 2, 15), date(2027, 2, 28)]


def test_quarterly_and_annual():
    q = Schedule("quarterly", anchor_date=date(2026, 1, 15))
    assert occ(q, date(2026, 5, 1), date(2027, 1, 31)) == [date(2026, 7, 15), date(2026, 10, 15), date(2027, 1, 15)]
    a = Schedule("annual", anchor_date=date(2024, 2, 29))
    assert occ(a, date(2025, 1, 1), date(2028, 12, 31)) == [date(2025, 2, 28), date(2026, 2, 28),
                                                             date(2027, 2, 28), date(2028, 2, 29)]


def test_undated_schedule_has_no_occurrences():
    s = Schedule("monthly")
    assert not s.is_dated
    assert occ(s, date(2026, 1, 1), date(2026, 12, 31)) == []
    assert s.next_due(date(2026, 1, 1)) is None


def test_validation():
    with pytest.raises(ScheduleError):
        Schedule("biweekly").validate()
    with pytest.raises(ScheduleError):
        Schedule("monthly", due_day=32).validate()
    with pytest.raises(ScheduleError):
        Schedule("fortnightly").validate()


@pytest.mark.parametrize("amount,freq,expected", [
    (100_00, "monthly", 100_00), (100_00, "weekly", 433_33), (2600_00, "biweekly", 5633_33),
    (100_00, "twice_monthly", 200_00), (300_00, "quarterly", 100_00), (180_00, "annual", 15_00),
    (1_00, "weekly", 4_33),
])
def test_monthly_equivalent(amount, freq, expected):
    assert monthly_equivalent_cents(amount, freq) == expected
