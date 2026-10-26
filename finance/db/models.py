"""SQLAlchemy ORM models.

Money is stored in integer cents (``*_cents`` columns). Rates are stored as
annual percentages (e.g. 6.49 for 6.49% APR).

Stage 1 creates the core tables used across all stages; later stages add
columns/tables through ``finance.db.migrations``.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Account types
# --------------------------------------------------------------------------- #
ASSET_TYPES: dict[str, str] = {
    "checking": "Checking",
    "savings": "Savings",
    "high_yield_savings": "High-yield savings",
    "retirement": "Retirement",
    "brokerage": "Brokerage",
    "hsa": "Health savings (HSA)",
    "cash": "Cash",
    "receivable": "Money owed to me",
    "other_asset": "Other asset",
}
LIABILITY_TYPES: dict[str, str] = {
    "credit_card": "Credit card",
    "auto_loan": "Auto loan",
    "student_loan": "Student loan",
    "personal_loan": "Personal loan",
    "mortgage": "Mortgage",
    "other_debt": "Other debt",
}
ACCOUNT_TYPES: dict[str, str] = {**ASSET_TYPES, **LIABILITY_TYPES}

# Groupings used by the dashboard
CASH_TYPES = {"checking", "savings", "high_yield_savings", "cash"}
SAVINGS_INVESTMENT_TYPES = {"savings", "high_yield_savings", "retirement", "brokerage", "hsa"}

FREQUENCIES: dict[str, str] = {
    "weekly": "Weekly",
    "biweekly": "Every 2 weeks",
    "twice_monthly": "Twice a month",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "annual": "Annually",
}

# What a recurring outflow *is* — keeps savings contributions and debt
# payments from being mistaken for ordinary spending.
BILL_KINDS: dict[str, str] = {
    "bill": "Fixed bill",
    "planned": "Planned spending (variable)",
    "debt_payment": "Debt payment",
    "savings": "Savings / investment contribution",
}

CATEGORY_KINDS = ("expense", "income", "transfer", "savings", "debt_payment")


def _now() -> datetime:
    return datetime.now()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, server_default=func.current_timestamp()
    )


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str | None] = mapped_column(String(120))
    # Positive number. For liabilities this is the amount owed.
    current_balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    balance_as_of: Mapped[date | None] = mapped_column(Date)
    credit_limit_cents: Mapped[int | None] = mapped_column(Integer)
    interest_rate: Mapped[float | None] = mapped_column(Float)  # APR / APY in percent
    minimum_payment_cents: Mapped[int | None] = mapped_column(Integer)
    original_balance_cents: Mapped[int | None] = mapped_column(Integer)
    payment_due_day: Mapped[int | None] = mapped_column(Integer)
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    snapshots: Mapped[list[BalanceSnapshot]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="BalanceSnapshot.as_of_date"
    )

    __table_args__ = (UniqueConstraint("name", "account_type", name="uq_account_name_type"),)

    @property
    def is_liability(self) -> bool:
        return self.account_type in LIABILITY_TYPES

    @property
    def type_label(self) -> str:
        return ACCOUNT_TYPES.get(self.account_type, self.account_type)

    @property
    def signed_balance_cents(self) -> int:
        """Balance as it contributes to net worth (liabilities negative)."""
        return -self.current_balance_cents if self.is_liability else self.current_balance_cents


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    as_of_date: Mapped[date] = mapped_column(Date)
    balance_cents: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual | workbook | statement
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    account: Mapped[Account] = relationship(back_populates="snapshots")

    __table_args__ = (Index("ix_snapshot_account_date", "account_id", "as_of_date"),)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    kind: Mapped[str] = mapped_column(String(20), default="expense")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    parent: Mapped[Category | None] = relationship(remote_side=[id])

    __table_args__ = (UniqueConstraint("name", "parent_id", name="uq_category_name_parent"),)


class Bill(TimestampMixin, Base):
    """A recurring outflow: a fixed bill, planned variable spending, a debt
    payment, or a savings contribution (see ``BILL_KINDS``)."""

    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="bill")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    due_day: Mapped[int | None] = mapped_column(Integer)  # 1-31 for monthly-style schedules
    due_day_2: Mapped[int | None] = mapped_column(Integer)  # second day for twice-monthly
    anchor_date: Mapped[date | None] = mapped_column(Date)  # first due date for weekly/biweekly/quarterly/annual
    # Occurrences before this date are not tracked (avoids flagging old cycles as overdue)
    tracking_start: Mapped[date] = mapped_column(Date, default=date.today)
    payment_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    pays_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))  # debt/savings account it feeds
    autopay: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    category: Mapped[Category | None] = relationship()
    payment_account: Mapped[Account | None] = relationship(foreign_keys=[payment_account_id])
    pays_account: Mapped[Account | None] = relationship(foreign_keys=[pays_account_id])
    payments: Mapped[list[BillPayment]] = relationship(back_populates="bill", cascade="all, delete-orphan")


class BillPayment(Base):
    __tablename__ = "bill_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="paid")  # paid | skipped
    paid_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    bill: Mapped[Bill] = relationship(back_populates="payments")

    __table_args__ = (UniqueConstraint("bill_id", "due_date", name="uq_bill_payment_cycle"),)


class IncomeSource(TimestampMixin, Base):
    __tablename__ = "income_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="salary")  # salary | bonus | side_business | other
    amount_cents: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    is_net: Mapped[bool] = mapped_column(Boolean, default=True)  # take-home vs gross
    deposit_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


class ImportRecord(Base):
    __tablename__ = "import_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(30))  # workbook | csv | xlsx | pdf
    filename: Mapped[str] = mapped_column(String(260))
    file_sha256: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)


class Transaction(TimestampMixin, Base):
    """Bank/credit transactions (populated by Stage 2 imports).

    ``amount_cents`` sign convention: negative = money out, positive = money in.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    posted_date: Mapped[date] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    original_description: Mapped[str | None] = mapped_column(Text)
    merchant: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    external_id: Mapped[str | None] = mapped_column(String(120))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("import_history.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()

    __table_args__ = (Index("ix_txn_account_date", "account_id", "posted_date"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create | update | deactivate | delete | import
    changes: Mapped[str | None] = mapped_column(Text)  # JSON


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
