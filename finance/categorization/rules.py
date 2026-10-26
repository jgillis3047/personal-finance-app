"""Keyword rules for classifying recurring outflows by name.

Generic keyword → (category, subcategory, kind) rules. Anything unmatched
falls back to "Other" and is flagged for review rather than guessed.
Stage 2 adds user-editable merchant rules for transactions on top of this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    pattern: str
    category: str
    subcategory: str | None
    kind: str  # bill | planned | debt_payment | savings


# Order matters: first match wins.
RECURRING_RULES: list[Rule] = [
    Rule(r"\b(roth|ira|401k|401\(k\)|retirement|brokerage|invest)", "Savings Transfers", "Retirement Contribution", "savings"),
    Rule(r"\bsavings?\b|emergency fund", "Savings Transfers", "Emergency Fund", "savings"),
    Rule(r"car insurance|auto insurance", "Insurance", "Auto Insurance", "bill"),
    Rule(r"life insurance", "Insurance", "Life Insurance", "bill"),
    Rule(r"health insurance", "Insurance", "Health Insurance", "bill"),
    Rule(r"renters? insurance", "Insurance", "Renters Insurance", "bill"),
    Rule(r"insurance", "Insurance", None, "bill"),
    Rule(r"\brent\b", "Housing", "Rent", "bill"),
    Rule(r"mortgage", "Housing", "Mortgage", "debt_payment"),
    Rule(r"student|school|tuition|sallie|navient|nelnet|mohela", "Debt Payments", "Student Loan", "debt_payment"),
    Rule(r"\b(car|auto|vehicle)\b( payment| loan)?$", "Debt Payments", "Auto Loan", "debt_payment"),
    Rule(r"\bgas\b|fuel|car wash", "Transportation", "Fuel & Car Wash", "planned"),
    Rule(r"uber|lyft|transit|parking|toll", "Transportation", "Rideshare & Transit", "planned"),
    Rule(r"electric|power|energy", "Utilities", "Electric", "bill"),
    Rule(r"internet|wifi|comcast|xfinity|spectrum", "Utilities", "Internet", "bill"),
    Rule(r"phone|verizon|t-?mobile|at&t", "Utilities", "Phone", "bill"),
    Rule(r"water|sewer|trash", "Utilities", "Water", "bill"),
    Rule(r"gym|fitness|planet fitness|peloton", "Healthcare", "Fitness", "bill"),
    Rule(r"chat ?gpt|openai|claude|software|adobe|microsoft 365|icloud|google one", "Subscriptions", "Software", "bill"),
    Rule(r"stream|netflix|hulu|spotify|disney|hbo|max\b|youtube|apple music|prime video", "Subscriptions", "Streaming", "bill"),
    Rule(r"hair ?cut|barber|salon", "Personal Care", "Haircut", "planned"),
    Rule(r"golf", "Entertainment", "Golf", "planned"),
    Rule(r"grocer|costco|trader joe|safeway|kroger|whole foods", "Groceries", None, "planned"),
    Rule(r"restaurant|dining|food|doordash|uber eats", "Restaurants", None, "planned"),
    Rule(r"daycare|childcare|babysit", "Childcare", None, "bill"),
    Rule(r"random|misc|spending money|fun money", "Other", None, "planned"),
]


@dataclass(frozen=True)
class Classification:
    category: str
    subcategory: str | None
    kind: str
    matched: bool


def classify_recurring(name: str) -> Classification:
    n = re.sub(r"\s+", " ", name.strip().lower())
    for r in RECURRING_RULES:
        if re.search(r.pattern, n):
            return Classification(r.category, r.subcategory, r.kind, True)
    return Classification("Other", None, "bill", False)


def debt_type_for(name: str) -> str:
    n = name.lower()
    if re.search(r"student|school|tuition|sallie|navient|nelnet|mohela", n):
        return "student_loan"
    if re.search(r"\b(car|auto|vehicle)\b", n):
        return "auto_loan"
    if "mortgage" in n or "home" in n:
        return "mortgage"
    return "other_debt"


def asset_type_for(name: str) -> tuple[str, bool]:
    """Map a balance label to an account type. Returns (type, confident)."""
    n = name.lower().strip()
    if re.search(r"high[- ]?yield|hysa", n):
        return "high_yield_savings", True
    if re.search(r"check", n):
        return "checking", True
    if re.search(r"saving", n):
        return "savings", True
    if re.search(r"retire|401|ira|roth|pension", n):
        return "retirement", True
    if re.search(r"brokerage|stock|invest|robinhood|fidelity|schwab|vanguard", n):
        return "brokerage", True
    if re.search(r"^cash$|cash on hand|wallet", n):
        return "cash", True
    return "other_asset", False
