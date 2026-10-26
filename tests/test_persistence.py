"""Database creation, migrations, persistence across restarts, backups."""
import sqlite3
from datetime import date

from sqlalchemy import text

from finance.db import init_db, session_scope
from finance.db.migrations import latest_version, run_migrations
from finance.db.models import Category
from finance.db.session import dispose_all
from finance.services import accounts, backup, bills


def test_init_is_idempotent(db_file):
    e = init_db(db_file)
    assert run_migrations(e) == []  # nothing pending second time
    init_db(db_file)
    with session_scope(e) as s:
        v = s.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        n_cats = s.query(Category).count()
    assert v == latest_version()
    init_db(db_file)
    with session_scope(e) as s:
        assert s.query(Category).count() == n_cats  # default categories not duplicated


def test_data_survives_restart(db_file):
    e = init_db(db_file)
    with session_scope(e) as s:
        a = accounts.create_account(s, name="Checking", account_type="checking", balance_cents=123_45)
        bills.create_bill(s, name="Rent", amount_cents=1000_00, due_day=1)
        aid = a.id
    dispose_all()  # simulate closing the app

    e2 = init_db(db_file)
    with session_scope(e2) as s:
        a = accounts.get(s, aid)
        assert a.current_balance_cents == 123_45
        assert [b.name for b in bills.list_bills(s)] == ["Rent"]


def test_failed_transaction_rolls_back(db_file):
    e = init_db(db_file)
    try:
        with session_scope(e) as s:
            accounts.create_account(s, name="Temp", account_type="cash")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with session_scope(e) as s:
        assert accounts.find_by_name(s, "Temp") is None


def test_backup_is_a_readable_copy(db_file):
    e = init_db(db_file)
    with session_scope(e) as s:
        accounts.create_account(s, name="Sav", account_type="savings", balance_cents=5_00, as_of=date(2026, 1, 1))
    p = backup.create_backup("test")
    con = sqlite3.connect(p)
    assert con.execute("SELECT name FROM accounts").fetchall() == [("Sav",)]
    con.close()
    assert backup.backup_bytes()[:16] == b"SQLite format 3\x00"
