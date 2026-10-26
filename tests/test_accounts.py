import json
from datetime import date, timedelta

import pytest

from finance.db.models import AuditLog
from finance.services import accounts as svc
from finance.services import bills
from finance.services.accounts import ValidationError


def test_create_and_snapshot(session):
    a = svc.create_account(session, name="Main Checking", account_type="checking", balance_cents=150_00,
                           as_of=date(2026, 10, 1))
    assert a.current_balance_cents == 150_00
    assert not a.is_liability and a.signed_balance_cents == 150_00
    hist = svc.history(session, a.id)
    assert [(h.as_of_date, h.balance_cents) for h in hist] == [(date(2026, 10, 1), 150_00)]


def test_liability_sign(session):
    card = svc.create_account(session, name="Card", account_type="credit_card", balance_cents=500_00)
    assert card.is_liability and card.signed_balance_cents == -500_00


@pytest.mark.parametrize("kwargs,msg", [
    ({"name": "  ", "account_type": "checking"}, "name is required"),
    ({"name": "X", "account_type": "piggy_bank"}, "Unknown account type"),
    ({"name": "X", "account_type": "checking", "balance_cents": -5}, "positive"),
    ({"name": "X", "account_type": "credit_card", "interest_rate": 250.0}, "Interest rate"),
    ({"name": "X", "account_type": "auto_loan", "payment_due_day": 40}, "due day"),
    ({"name": "X", "account_type": "credit_card", "credit_limit_cents": -1}, "negative"),
])
def test_validation(session, kwargs, msg):
    with pytest.raises(ValidationError, match=msg):
        svc.create_account(session, **kwargs)


def test_unique_name_per_type(session):
    svc.create_account(session, name="Savings", account_type="savings")
    with pytest.raises(ValidationError, match="already exists"):
        svc.create_account(session, name="Savings", account_type="savings")
    svc.create_account(session, name="Savings", account_type="high_yield_savings")  # different type is fine


def test_balance_history_and_backdating(session):
    a = svc.create_account(session, name="Sav", account_type="savings", balance_cents=1000_00, as_of=date(2026, 9, 1))
    svc.set_balance(session, a.id, 1200_00, as_of=date(2026, 10, 1))
    assert a.current_balance_cents == 1200_00
    # a back-dated entry is kept in history but doesn't overwrite the newer current balance
    svc.set_balance(session, a.id, 1100_00, as_of=date(2026, 9, 15))
    assert a.current_balance_cents == 1200_00 and a.balance_as_of == date(2026, 10, 1)
    assert [h.balance_cents for h in svc.history(session, a.id)] == [1000_00, 1100_00, 1200_00]
    with pytest.raises(ValidationError, match="future"):
        svc.set_balance(session, a.id, 5, as_of=date.today() + timedelta(days=1))


def test_update_writes_audit_diff(session):
    a = svc.create_account(session, name="Card", account_type="credit_card", balance_cents=10_00)
    svc.update_account(session, a.id, interest_rate=22.99, name="Card")  # name unchanged -> not in diff
    session.flush()
    log = session.query(AuditLog).filter_by(entity="account", entity_id=a.id, action="update").one()
    assert json.loads(log.changes) == {"interest_rate": [None, 22.99]}


def test_deactivate_hides_from_active_list(session):
    a = svc.create_account(session, name="Old", account_type="cash")
    svc.deactivate(session, a.id)
    assert a not in svc.list_accounts(session)
    assert a in svc.list_accounts(session, active_only=False)


def test_delete_refused_when_referenced(session):
    loan = svc.create_account(session, name="Loan", account_type="auto_loan", balance_cents=100_00)
    bills.create_bill(session, name="Loan payment", kind="debt_payment", amount_cents=10_00, pays_account_id=loan.id)
    with pytest.raises(ValidationError, match="Deactivate"):
        svc.delete_account(session, loan.id)
    other = svc.create_account(session, name="Spare", account_type="cash")
    svc.delete_account(session, other.id)
    session.flush()
    assert svc.find_by_name(session, "Spare") is None
