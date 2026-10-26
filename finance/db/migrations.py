"""Tiny, dependency-free schema migration runner.

Each migration has an integer version and a function that receives a live
connection. Migrations must be idempotent (check before altering) so a
partially-applied upgrade can be re-run safely. Before upgrading an existing
database that already holds data, a backup copy is written automatically.

To add a migration in a later stage:
    @migration(2, "add budgets table")
    def _m2(conn): ...
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from finance.db.models import Base

MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = []


def migration(version: int, description: str):
    def deco(fn):
        MIGRATIONS.append((version, description, fn))
        MIGRATIONS.sort(key=lambda m: m[0])
        return fn

    return deco


def latest_version() -> int:
    return MIGRATIONS[-1][0] if MIGRATIONS else 0


def current_version(conn: Connection) -> int:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT)"
        )
    )
    v = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
    return int(v or 0)


def _has_user_data(conn: Connection) -> bool:
    insp = inspect(conn)
    return "accounts" in insp.get_table_names() and bool(
        conn.execute(text("SELECT COUNT(*) FROM accounts")).scalar()
    )


def _backup_before_upgrade(engine: Engine, from_version: int) -> None:
    from finance import config

    db_file = engine.url.database
    if not db_file or db_file == ":memory:":
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = config.backup_dir() / f"pre-migration-v{from_version}-{stamp}.db"
    src = sqlite3.connect(db_file)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()


def run_migrations(engine: Engine) -> list[int]:
    applied: list[int] = []
    with engine.begin() as conn:
        cur = current_version(conn)
        pending = [m for m in MIGRATIONS if m[0] > cur]
        needs_backup = bool(pending) and cur > 0 and _has_user_data(conn)
    if needs_backup:
        _backup_before_upgrade(engine, cur)
    for version, desc, fn in pending:
        with engine.begin() as conn:
            fn(conn)
            conn.execute(
                text("INSERT INTO schema_version (version, description, applied_at) VALUES (:v, :d, :t)"),
                {"v": version, "d": desc, "t": datetime.now().isoformat(timespec="seconds")},
            )
        applied.append(version)
    return applied


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #
@migration(1, "initial schema: accounts, snapshots, categories, bills, income, transactions, audit")
def _m1(conn: Connection) -> None:
    # create_all only creates missing tables, so this is idempotent.
    Base.metadata.create_all(conn)
