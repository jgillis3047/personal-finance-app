"""Recurring bills and planned outflows.

A bill is never considered paid just because its due date passed: an
occurrence is *paid* only when a BillPayment row exists for it (created by the
user, or in Stage 3 by an explicit transaction match).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.calculations.schedules import Schedule, ScheduleError, monthly_equivalent_cents
from finance.db.models import BILL_KINDS, FREQUENCIES, Bill, BillPayment
from finance.services import audit
from finance.services.accounts import ValidationError

EDITABLE = {
    "name", "kind", "category_id", "amount_cents", "frequency", "due_day", "due_day_2", "anchor_date",
    "tracking_start", "payment_account_id", "pays_account_id", "autopay", "is_active", "needs_review",
    "review_note", "notes",
}


def schedule_of(bill: Bill) -> Schedule:
    return Schedule(bill.frequency, bill.due_day, bill.due_day_2, bill.anchor_date)


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in EDITABLE:
            raise ValidationError(f"Unknown bill field: {k}")
        if isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    if "name" in out and not out["name"]:
        raise ValidationError("Bill name is required")
    if "kind" in out and out["kind"] not in BILL_KINDS:
        raise ValidationError(f"Unknown bill kind: {out['kind']}")
    if "frequency" in out and out["frequency"] not in FREQUENCIES:
        raise ValidationError(f"Unknown frequency: {out['frequency']}")
    if "amount_cents" in out and (out["amount_cents"] is None or out["amount_cents"] < 0):
        raise ValidationError("Bill amount must be zero or more")
    return out


def _validate_schedule(bill: Bill) -> None:
    try:
        s = schedule_of(bill)
        # Monthly-style items may be left undated (shown as "due date not set");
        # interval schedules can't be computed at all without a first due date.
        if s.is_dated or bill.frequency not in ("monthly", "twice_monthly"):
            s.validate()
        elif bill.due_day is not None and not 1 <= bill.due_day <= 31:
            raise ScheduleError("Due day must be between 1 and 31")
    except ScheduleError as exc:
        raise ValidationError(str(exc)) from exc


def create_bill(session: Session, **fields) -> Bill:
    data = _clean(fields)
    if session.scalar(select(Bill).where(Bill.name == data["name"])):
        raise ValidationError(f"A bill named '{data['name']}' already exists")
    data.setdefault("tracking_start", date.today())
    data.setdefault("frequency", "monthly")
    data.setdefault("kind", "bill")
    bill = Bill(**data)
    _validate_schedule(bill)
    session.add(bill)
    session.flush()
    audit.record(session, "bill", bill.id, "create", data)
    return bill


def update_bill(session: Session, bill_id: int, **fields) -> Bill:
    bill = get(session, bill_id)
    data = _clean(fields)
    if "name" in data:
        other = session.scalar(select(Bill).where(Bill.name == data["name"]))
        if other and other.id != bill.id:
            raise ValidationError(f"A bill named '{data['name']}' already exists")
    changes = audit.diff(bill, data)
    for k, v in data.items():
        setattr(bill, k, v)
    _validate_schedule(bill)
    if changes:
        audit.record(session, "bill", bill.id, "update", changes)
    return bill


def get(session: Session, bill_id: int) -> Bill:
    b = session.get(Bill, bill_id)
    if b is None:
        raise ValidationError(f"Bill {bill_id} not found")
    return b


def list_bills(session: Session, *, active_only: bool = True) -> list[Bill]:
    q = select(Bill).order_by(Bill.name)
    if active_only:
        q = q.where(Bill.is_active.is_(True))
    return list(session.scalars(q))


def monthly_cents(bill: Bill) -> int:
    return monthly_equivalent_cents(bill.amount_cents, bill.frequency)


@dataclass
class Occurrence:
    bill: Bill
    due_date: date
    status: str  # paid | skipped | overdue | due_today | upcoming
    payment: BillPayment | None

    @property
    def days_until(self) -> int:
        return (self.due_date - date.today()).days


def occurrences(session: Session, start: date, end: date, *, today: date | None = None,
                bills: list[Bill] | None = None) -> list[Occurrence]:
    today = today or date.today()
    out: list[Occurrence] = []
    for bill in bills if bills is not None else list_bills(session):
        paid = {p.due_date: p for p in bill.payments}
        s = schedule_of(bill)
        lo = max(start, bill.tracking_start) if bill.tracking_start else start
        for d in s.occurrences(lo, end):
            p = paid.get(d)
            if p:
                status = p.status
            elif d < today:
                status = "overdue"
            elif d == today:
                status = "due_today"
            else:
                status = "upcoming"
            out.append(Occurrence(bill, d, status, p))
    out.sort(key=lambda o: (o.due_date, o.bill.name))
    return out


def upcoming(session: Session, days: int = 30, *, today: date | None = None, include_overdue: bool = True,
             lookback_days: int = 90) -> list[Occurrence]:
    today = today or date.today()
    start = today - timedelta(days=lookback_days) if include_overdue else today
    occ = occurrences(session, start, today + timedelta(days=days), today=today)
    return [o for o in occ if o.status in ("overdue", "due_today", "upcoming")]


def mark_paid(session: Session, bill_id: int, due_date: date, *, paid_date: date | None = None,
              amount_cents: int | None = None, status: str = "paid", note: str | None = None) -> BillPayment:
    if status not in ("paid", "skipped"):
        raise ValidationError("Status must be 'paid' or 'skipped'")
    bill = get(session, bill_id)
    existing = session.scalar(select(BillPayment).where(BillPayment.bill_id == bill.id, BillPayment.due_date == due_date))
    if existing:
        raise ValidationError(f"{bill.name} is already marked {existing.status} for {due_date:%b %d, %Y}")
    p = BillPayment(due_date=due_date, status=status,
                    paid_date=paid_date or (date.today() if status == "paid" else None),
                    amount_cents=bill.amount_cents if amount_cents is None else amount_cents, note=note)
    bill.payments.append(p)
    session.flush()
    audit.record(session, "bill_payment", p.id, "create",
                 {"bill": bill.name, "due_date": due_date, "status": status, "amount_cents": p.amount_cents})
    return p


def unmark(session: Session, payment_id: int) -> None:
    p = session.get(BillPayment, payment_id)
    if p is None:
        raise ValidationError("Payment record not found")
    audit.record(session, "bill_payment", p.id, "delete",
                 {"bill_id": p.bill_id, "due_date": p.due_date, "status": p.status})
    p.bill.payments.remove(p)
    session.delete(p)
