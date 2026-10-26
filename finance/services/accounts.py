"""Account management: create, edit, balance updates (with history), deactivate."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.db.models import ACCOUNT_TYPES, Account, BalanceSnapshot, Bill, IncomeSource, Transaction
from finance.services import audit


class ValidationError(ValueError):
    pass


EDITABLE_FIELDS = {
    "name", "account_type", "institution", "credit_limit_cents", "interest_rate",
    "minimum_payment_cents", "original_balance_cents", "payment_due_day",
    "include_in_net_worth", "is_active", "needs_review", "review_note", "notes",
}


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in EDITABLE_FIELDS:
            raise ValidationError(f"Unknown account field: {k}")
        if isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    if "name" in out:
        if not out["name"]:
            raise ValidationError("Account name is required")
        if len(out["name"]) > 120:
            raise ValidationError("Account name is too long (max 120 characters)")
    if "account_type" in out and out["account_type"] not in ACCOUNT_TYPES:
        raise ValidationError(f"Unknown account type: {out['account_type']}")
    for k in ("credit_limit_cents", "minimum_payment_cents", "original_balance_cents"):
        if out.get(k) is not None and out[k] < 0:
            raise ValidationError(f"{k.replace('_cents', '').replace('_', ' ').capitalize()} cannot be negative")
    if out.get("interest_rate") is not None and not 0 <= out["interest_rate"] <= 100:
        raise ValidationError("Interest rate must be between 0 and 100 (%)")
    if out.get("payment_due_day") is not None and not 1 <= out["payment_due_day"] <= 31:
        raise ValidationError("Payment due day must be between 1 and 31")
    return out


def _check_unique(session: Session, name: str, account_type: str, exclude_id: int | None = None) -> None:
    q = select(Account).where(Account.name == name, Account.account_type == account_type)
    existing = session.scalar(q)
    if existing and existing.id != exclude_id:
        raise ValidationError(f"An account named '{name}' of that type already exists")


def create_account(
    session: Session,
    *,
    name: str,
    account_type: str,
    balance_cents: int = 0,
    as_of: date | None = None,
    source: str = "manual",
    **fields,
) -> Account:
    data = _clean({"name": name, "account_type": account_type, **fields})
    if balance_cents < 0:
        raise ValidationError(
            "Enter balances as positive numbers. For credit cards and loans, enter the amount you owe."
        )
    _check_unique(session, data["name"], data["account_type"])
    acct = Account(**data, current_balance_cents=balance_cents, balance_as_of=as_of or date.today())
    session.add(acct)
    session.flush()
    session.add(BalanceSnapshot(account_id=acct.id, as_of_date=acct.balance_as_of,
                                balance_cents=balance_cents, source=source, note="Opening balance"))
    audit.record(session, "account", acct.id, "create", {**data, "balance_cents": balance_cents})
    return acct


def update_account(session: Session, account_id: int, **fields) -> Account:
    acct = get(session, account_id)
    data = _clean(fields)
    _check_unique(session, data.get("name", acct.name), data.get("account_type", acct.account_type), acct.id)
    changes = audit.diff(acct, data)
    for k, v in data.items():
        setattr(acct, k, v)
    if changes:
        audit.record(session, "account", acct.id, "update", changes)
    return acct


def set_balance(
    session: Session, account_id: int, balance_cents: int, *, as_of: date | None = None,
    source: str = "manual", note: str | None = None,
) -> BalanceSnapshot:
    """Record a balance as of a date. Keeps history; updates the current balance
    only if this snapshot is the most recent one."""
    if balance_cents < 0:
        raise ValidationError("Enter balances as positive numbers (amount owed for debts).")
    acct = get(session, account_id)
    as_of = as_of or date.today()
    if as_of > date.today():
        raise ValidationError("Balance date cannot be in the future")
    snap = BalanceSnapshot(account_id=acct.id, as_of_date=as_of, balance_cents=balance_cents, source=source, note=note)
    session.add(snap)
    old = acct.current_balance_cents
    if acct.balance_as_of is None or as_of >= acct.balance_as_of:
        acct.current_balance_cents = balance_cents
        acct.balance_as_of = as_of
    audit.record(session, "account", acct.id, "balance", {"balance_cents": (old, balance_cents), "as_of": as_of,
                                                          "source": source})
    session.flush()
    return snap


def deactivate(session: Session, account_id: int) -> None:
    acct = get(session, account_id)
    acct.is_active = False
    audit.record(session, "account", acct.id, "deactivate", {"is_active": (True, False)})


def delete_account(session: Session, account_id: int) -> None:
    """Permanently delete — refused if anything references the account."""
    acct = get(session, account_id)
    refs = (
        session.scalar(select(Transaction.id).where(Transaction.account_id == acct.id).limit(1))
        or session.scalar(select(Bill.id).where((Bill.payment_account_id == acct.id) | (Bill.pays_account_id == acct.id)).limit(1))
        or session.scalar(select(IncomeSource.id).where(IncomeSource.deposit_account_id == acct.id).limit(1))
    )
    if refs:
        raise ValidationError("This account is used by transactions, bills or income. Deactivate it instead.")
    audit.record(session, "account", acct.id, "delete", {"name": acct.name, "balance_cents": acct.current_balance_cents})
    session.delete(acct)


def get(session: Session, account_id: int) -> Account:
    acct = session.get(Account, account_id)
    if acct is None:
        raise ValidationError(f"Account {account_id} not found")
    return acct


def find_by_name(session: Session, name: str, account_type: str | None = None) -> Account | None:
    q = select(Account).where(Account.name == name)
    if account_type:
        q = q.where(Account.account_type == account_type)
    return session.scalar(q)


def list_accounts(session: Session, *, active_only: bool = True) -> list[Account]:
    q = select(Account).order_by(Account.account_type, Account.name)
    if active_only:
        q = q.where(Account.is_active.is_(True))
    return list(session.scalars(q))


def history(session: Session, account_id: int) -> list[BalanceSnapshot]:
    return list(session.scalars(
        select(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.as_of_date, BalanceSnapshot.id)
    ))
