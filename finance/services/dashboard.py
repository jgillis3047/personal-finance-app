"""Gathers dashboard numbers from the database."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.calculations import metrics
from finance.db.models import CASH_TYPES, SAVINGS_INVESTMENT_TYPES, Account, BalanceSnapshot, Transaction
from finance.services import accounts as acct_svc
from finance.services import bills as bill_svc
from finance.services import income as income_svc
from finance.services.categories import top_level_name


@dataclass
class Dashboard:
    # Planned (from income sources and recurring outflows), monthly equivalents
    income_cents: int = 0
    outflow_by_kind: dict[str, int] = field(default_factory=dict)
    spending_by_category: dict[str, int] = field(default_factory=dict)
    # Balances
    cash_cents: int = 0
    savings_investments_cents: int = 0
    receivables_cents: int = 0
    assets_cents: int = 0
    liabilities_cents: int = 0
    net_worth_cents: int = 0
    debt_by_account: list[tuple[str, int]] = field(default_factory=list)
    # Bills
    due_30_unpaid_cents: int = 0
    overdue_count: int = 0
    undated_bill_count: int = 0
    review_count: int = 0
    # Transactions (Stage 2+)
    transaction_count: int = 0
    actual_month: dict | None = None

    @property
    def expenses_cents(self) -> int:
        """Planned spending: bills + variable spending + debt payments (excludes savings contributions)."""
        return sum(v for k, v in self.outflow_by_kind.items() if k != "savings")

    @property
    def savings_contrib_cents(self) -> int:
        return self.outflow_by_kind.get("savings", 0)

    @property
    def fixed_cents(self) -> int:
        return self.outflow_by_kind.get("bill", 0) + self.outflow_by_kind.get("debt_payment", 0)

    @property
    def cash_flow_cents(self) -> int:
        return self.income_cents - self.expenses_cents

    @property
    def left_after_plan_cents(self) -> int:
        return self.income_cents - self.expenses_cents - self.savings_contrib_cents

    @property
    def savings_rate(self) -> float | None:
        return metrics.savings_rate(self.income_cents, self.expenses_cents)

    @property
    def available_after_bills_cents(self) -> int:
        return self.cash_cents - self.due_30_unpaid_cents


def build(session: Session, *, today: date | None = None, month: tuple[int, int] | None = None) -> Dashboard:
    today = today or date.today()
    d = Dashboard()

    d.income_cents = sum(income_svc.monthly_cents(s) for s in income_svc.list_income(session))

    by_kind: dict[str, int] = defaultdict(int)
    by_cat: dict[str, int] = defaultdict(int)
    for b in bill_svc.list_bills(session):
        m = bill_svc.monthly_cents(b)
        by_kind[b.kind] += m
        if b.kind != "savings":
            by_cat[top_level_name(b.category)] += m
        if not bill_svc.schedule_of(b).is_dated:
            d.undated_bill_count += 1
        if b.needs_review:
            d.review_count += 1
    d.outflow_by_kind = dict(by_kind)
    d.spending_by_category = dict(sorted(by_cat.items(), key=lambda kv: -kv[1]))

    accts = acct_svc.list_accounts(session)
    rows = [metrics.BalanceRow(a.id, a.current_balance_cents, a.is_liability, a.include_in_net_worth) for a in accts]
    d.assets_cents, d.liabilities_cents, d.net_worth_cents = metrics.net_worth_cents(rows)
    for a in accts:
        if a.needs_review:
            d.review_count += 1
        if a.account_type in CASH_TYPES:
            d.cash_cents += a.current_balance_cents
        if a.account_type in SAVINGS_INVESTMENT_TYPES:
            d.savings_investments_cents += a.current_balance_cents
        if a.account_type == "receivable" and a.include_in_net_worth:
            d.receivables_cents += a.current_balance_cents
        if a.is_liability and a.current_balance_cents:
            d.debt_by_account.append((a.name, a.current_balance_cents))
    d.debt_by_account.sort(key=lambda t: -t[1])

    upcoming = bill_svc.upcoming(session, 30, today=today)
    d.due_30_unpaid_cents = sum(o.bill.amount_cents for o in upcoming if o.bill.kind != "planned")
    d.overdue_count = sum(1 for o in upcoming if o.status == "overdue")

    d.transaction_count = session.query(Transaction).count()
    if d.transaction_count:
        d.actual_month = actual_for_month(session, *(month or (today.year, today.month)))
    return d


def actual_for_month(session: Session, year: int, month: int) -> dict:
    """Actual income/spending from imported transactions, excluding transfers."""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    txns = session.scalars(
        select(Transaction).where(Transaction.posted_date >= start, Transaction.posted_date < end,
                                  Transaction.is_transfer.is_(False))
    )
    income = spend = 0
    for t in txns:
        if t.amount_cents > 0:
            income += t.amount_cents
        else:
            spend += -t.amount_cents
    return {"income_cents": income, "spending_cents": spend}


def net_worth_series(session: Session) -> list[tuple[date, int, int, int]]:
    rows = session.execute(
        select(BalanceSnapshot.account_id, BalanceSnapshot.as_of_date, BalanceSnapshot.balance_cents,
               BalanceSnapshot.id, Account.account_type, Account.include_in_net_worth)
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(Account.include_in_net_worth.is_(True))
    ).all()
    from finance.db.models import LIABILITY_TYPES

    snaps = [metrics.Snapshot(r[0], r[1], r[2], r[4] in LIABILITY_TYPES, r[3]) for r in rows]
    return metrics.net_worth_history(snaps)
