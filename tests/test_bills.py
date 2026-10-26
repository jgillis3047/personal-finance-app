from datetime import date

import pytest

from finance.services import bills as svc
from finance.services.accounts import ValidationError

TODAY = date(2026, 10, 24)


def make(session, **kw):
    base = dict(name="Rent", kind="bill", amount_cents=1500_00, frequency="monthly", due_day=1,
                tracking_start=date(2026, 9, 1))
    base.update(kw)
    return svc.create_bill(session, **base)


def test_past_due_is_overdue_not_paid(session):
    make(session)
    occ = svc.occurrences(session, date(2026, 9, 1), date(2026, 11, 30), today=TODAY)
    assert [(o.due_date, o.status) for o in occ] == [
        (date(2026, 9, 1), "overdue"), (date(2026, 10, 1), "overdue"), (date(2026, 11, 1), "upcoming")]


def test_tracking_start_skips_cycles_before_tracking(session):
    make(session, tracking_start=TODAY)
    up = svc.upcoming(session, 30, today=TODAY)
    assert [(o.due_date, o.status) for o in up] == [(date(2026, 11, 1), "upcoming")]


def test_mark_paid_and_skip_and_undo(session):
    b = make(session)
    p = svc.mark_paid(session, b.id, date(2026, 9, 1), paid_date=date(2026, 9, 1))
    svc.mark_paid(session, b.id, date(2026, 10, 1), status="skipped")
    occ = {o.due_date: o.status for o in svc.occurrences(session, date(2026, 9, 1), date(2026, 10, 31), today=TODAY)}
    assert occ == {date(2026, 9, 1): "paid", date(2026, 10, 1): "skipped"}
    with pytest.raises(ValidationError, match="already marked"):
        svc.mark_paid(session, b.id, date(2026, 9, 1))
    svc.unmark(session, p.id)
    session.flush()
    occ = {o.due_date: o.status for o in svc.occurrences(session, date(2026, 9, 1), date(2026, 9, 30), today=TODAY)}
    assert occ == {date(2026, 9, 1): "overdue"}


def test_due_today_status(session):
    make(session, name="Car", due_day=24, tracking_start=TODAY)
    assert svc.upcoming(session, 0, today=TODAY)[0].status == "due_today"


def test_undated_bill_not_in_calendar_but_in_monthly_total(session):
    b = make(session, name="Gym", due_day=None, amount_cents=30_00)
    assert svc.upcoming(session, 30, today=TODAY) == []
    assert svc.monthly_cents(b) == 30_00


def test_biweekly_requires_first_due_date(session):
    with pytest.raises(ValidationError, match="first due date"):
        make(session, name="X", frequency="biweekly", due_day=None)


def test_validation(session):
    with pytest.raises(ValidationError):
        make(session, name="")
    with pytest.raises(ValidationError):
        make(session, name="Y", amount_cents=-1)
    with pytest.raises(ValidationError):
        make(session, name="Z", kind="mystery")
    make(session, name="Dup")
    with pytest.raises(ValidationError, match="already exists"):
        make(session, name="Dup")


def test_update_bill_changes_schedule(session):
    b = make(session, tracking_start=TODAY)
    svc.update_bill(session, b.id, due_day=5)
    assert svc.upcoming(session, 30, today=TODAY)[0].due_date == date(2026, 11, 5)
