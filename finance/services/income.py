"""Income sources (projected income). Actual income comes from transactions in Stage 2+."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.calculations.schedules import monthly_equivalent_cents
from finance.db.models import FREQUENCIES, IncomeSource
from finance.services import audit
from finance.services.accounts import ValidationError

INCOME_KINDS = {"salary": "Salary", "bonus": "Bonus", "side_business": "Side business", "other": "Other income"}
EDITABLE = {"name", "kind", "amount_cents", "frequency", "is_net", "deposit_account_id", "is_active", "notes"}


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in EDITABLE:
            raise ValidationError(f"Unknown income field: {k}")
        if isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    if "name" in out and not out["name"]:
        raise ValidationError("Income name is required")
    if "kind" in out and out["kind"] not in INCOME_KINDS:
        raise ValidationError(f"Unknown income type: {out['kind']}")
    if "frequency" in out and out["frequency"] not in FREQUENCIES:
        raise ValidationError(f"Unknown frequency: {out['frequency']}")
    if "amount_cents" in out and (out["amount_cents"] is None or out["amount_cents"] < 0):
        raise ValidationError("Income amount must be zero or more")
    return out


def create_income(session: Session, **fields) -> IncomeSource:
    data = _clean(fields)
    if session.scalar(select(IncomeSource).where(IncomeSource.name == data["name"])):
        raise ValidationError(f"An income source named '{data['name']}' already exists")
    src = IncomeSource(**data)
    session.add(src)
    session.flush()
    audit.record(session, "income", src.id, "create", data)
    return src


def update_income(session: Session, income_id: int, **fields) -> IncomeSource:
    src = session.get(IncomeSource, income_id)
    if src is None:
        raise ValidationError("Income source not found")
    data = _clean(fields)
    changes = audit.diff(src, data)
    for k, v in data.items():
        setattr(src, k, v)
    if changes:
        audit.record(session, "income", src.id, "update", changes)
    return src


def list_income(session: Session, *, active_only: bool = True) -> list[IncomeSource]:
    q = select(IncomeSource).order_by(IncomeSource.name)
    if active_only:
        q = q.where(IncomeSource.is_active.is_(True))
    return list(session.scalars(q))


def monthly_cents(src: IncomeSource) -> int:
    return monthly_equivalent_cents(src.amount_cents, src.frequency)
