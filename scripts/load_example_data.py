"""Load fictional example data for testing/demo.

Refuses to touch a database that already has accounts, so it can't mix demo
numbers into real data. Use with a separate database:

    run_app.bat demo
    (or) set FINANCE_APP_DB=C:\\somewhere\\demo.db  then run this script
"""
import _bootstrap  # noqa: F401

import sys
from datetime import date, timedelta

from finance import config
from finance.db import init_db, session_scope
from finance.db.models import Account
from finance.services import accounts, bills, income
from finance.services.categories import find_category


def load(session, today: date | None = None) -> None:
    today = today or date.today()
    t = lambda months: today - timedelta(days=30 * months)  # noqa: E731

    chk = accounts.create_account(session, name="Everyday Checking", account_type="checking", balance_cents=284_512,
                                  as_of=t(3), institution="Example Bank")
    sav = accounts.create_account(session, name="Rainy Day Fund", account_type="high_yield_savings",
                                  balance_cents=600_000, as_of=t(3), institution="Example Bank", interest_rate=4.1)
    ret = accounts.create_account(session, name="Workplace 401(k)", account_type="retirement",
                                  balance_cents=1_850_000, as_of=t(3))
    card = accounts.create_account(session, name="Rewards Visa", account_type="credit_card", balance_cents=145_090,
                                   as_of=t(3), credit_limit_cents=800_000, interest_rate=24.99,
                                   minimum_payment_cents=4_000, payment_due_day=18)
    car = accounts.create_account(session, name="Hatchback Loan", account_type="auto_loan", balance_cents=1_120_000,
                                  as_of=t(3), interest_rate=6.9, minimum_payment_cents=36_500, payment_due_day=12,
                                  original_balance_cents=2_200_000)
    # A few months of balance history so the trend charts have something to show
    for i, (c, s, r, cc, l) in enumerate([(301_000, 640_000, 1_905_000, 120_000, 1_090_000),
                                          (276_400, 690_000, 1_962_000, 98_250, 1_058_000),
                                          (312_870, 740_000, 2_011_500, 87_400, 1_026_300)]):
        d = t(2 - i)
        for a, v in ((chk, c), (sav, s), (ret, r), (card, cc), (car, l)):
            accounts.set_balance(session, a.id, v, as_of=d, note="Example data")

    income.create_income(session, name="Example Employer", kind="salary", amount_cents=260_000,
                         frequency="biweekly", deposit_account_id=chk.id)
    cat = lambda n, p=None: (find_category(session, n, p) or find_category(session, "Other")).id  # noqa: E731
    for name, kind, c, amt, day, extra in [
        ("Apartment rent", "bill", cat("Rent", "Housing"), 175_000, 1, {}),
        ("Electric", "bill", cat("Electric", "Utilities"), 9_500, 20, {}),
        ("Internet", "bill", cat("Internet", "Utilities"), 6_500, 8, {"autopay": True}),
        ("Phone", "bill", cat("Phone", "Utilities"), 5_500, 15, {"autopay": True}),
        ("Car payment", "debt_payment", cat("Auto Loan", "Debt Payments"), 36_500, 12, {"pays_account_id": car.id}),
        ("Card payment", "debt_payment", cat("Credit Card", "Debt Payments"), 20_000, 18, {"pays_account_id": card.id}),
        ("Auto insurance", "bill", cat("Auto Insurance", "Insurance"), 13_800, 5, {}),
        ("Streaming bundle", "bill", cat("Streaming", "Subscriptions"), 2_299, 22, {"autopay": True}),
        ("Groceries", "planned", cat("Groceries"), 55_000, None, {}),
        ("Eating out", "planned", cat("Restaurants"), 25_000, None, {}),
        ("Fuel", "planned", cat("Fuel & Car Wash", "Transportation"), 16_000, None, {}),
        ("Savings transfer", "savings", cat("Emergency Fund", "Savings Transfers"), 50_000, 2,
         {"pays_account_id": sav.id}),
    ]:
        bills.create_bill(session, name=name, kind=kind, category_id=c, amount_cents=amt, frequency="monthly",
                          due_day=day, payment_account_id=chk.id, tracking_start=today - timedelta(days=10), **extra)
    bills.create_bill(session, name="Renters insurance", kind="bill", category_id=cat("Renters Insurance", "Insurance"),
                      amount_cents=18_000, frequency="annual", anchor_date=today + timedelta(days=45))


if __name__ == "__main__":
    engine = init_db()
    with session_scope(engine) as s:
        if s.query(Account).count():
            print(f"{config.db_path()} already has data — example data not loaded.")
            sys.exit(0)
        load(s)
    print(f"Example data loaded into {config.db_path()}")
