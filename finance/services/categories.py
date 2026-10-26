"""Default category tree and lookups."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.db.models import Category

# name -> (kind, [subcategories])
DEFAULT_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "Housing": ("expense", ["Rent", "Mortgage", "Maintenance"]),
    "Groceries": ("expense", []),
    "Restaurants": ("expense", []),
    "Transportation": ("expense", ["Fuel & Car Wash", "Parking & Tolls", "Rideshare & Transit", "Car Maintenance"]),
    "Utilities": ("expense", ["Electric", "Internet", "Phone", "Water"]),
    "Insurance": ("expense", ["Auto Insurance", "Life Insurance", "Health Insurance", "Renters Insurance"]),
    "Healthcare": ("expense", ["Fitness", "Medical", "Pharmacy"]),
    "Personal Care": ("expense", ["Haircut"]),
    "Shopping": ("expense", []),
    "Entertainment": ("expense", ["Golf", "Games"]),
    "Subscriptions": ("expense", ["Software", "Streaming"]),
    "Childcare": ("expense", []),
    "Education": ("expense", ["Tuition"]),
    "Debt Payments": ("debt_payment", ["Auto Loan", "Student Loan", "Credit Card", "Personal Loan"]),
    "Savings Transfers": ("savings", ["Retirement Contribution", "Emergency Fund"]),
    "Other": ("expense", []),
    "Income": ("income", ["Salary", "Bonus", "Side Business", "Refund", "Other Income"]),
    "Transfers": ("transfer", ["Between My Accounts", "Credit Card Payment"]),
}


def ensure_default_categories(session: Session) -> None:
    existing = {(c.name, c.parent_id) for c in session.scalars(select(Category))}
    for name, (kind, subs) in DEFAULT_CATEGORIES.items():
        parent = session.scalar(select(Category).where(Category.name == name, Category.parent_id.is_(None)))
        if parent is None:
            parent = Category(name=name, kind=kind, is_system=True)
            session.add(parent)
            session.flush()
        for sub in subs:
            if (sub, parent.id) not in existing:
                session.add(Category(name=sub, parent_id=parent.id, kind=kind, is_system=True))
    session.flush()


def find_category(session: Session, name: str, parent: str | None = None) -> Category | None:
    if parent:
        p = session.scalar(select(Category).where(Category.name == parent, Category.parent_id.is_(None)))
        if p is None:
            return None
        return session.scalar(select(Category).where(Category.name == name, Category.parent_id == p.id))
    return session.scalar(select(Category).where(Category.name == name, Category.parent_id.is_(None)))


def category_label(cat: Category | None) -> str:
    if cat is None:
        return "Uncategorized"
    return f"{cat.parent.name} › {cat.name}" if cat.parent else cat.name


def top_level_name(cat: Category | None) -> str:
    if cat is None:
        return "Uncategorized"
    return cat.parent.name if cat.parent else cat.name


def all_categories(session: Session) -> list[Category]:
    cats = list(session.scalars(select(Category)))
    return sorted(cats, key=lambda c: category_label(c).lower())
