"""Engine and session management."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from finance import config

_engines: dict[str, Engine] = {}


def get_engine(db_file: Path | str | None = None) -> Engine:
    path = str(Path(db_file) if db_file else config.db_path())
    if path not in _engines:
        engine = create_engine(f"sqlite:///{path}", future=True)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        _engines[path] = engine
    return _engines[path]


def dispose_all() -> None:
    for eng in _engines.values():
        eng.dispose()
    _engines.clear()


def init_db(db_file: Path | str | None = None) -> Engine:
    """Create/upgrade the schema and seed default categories. Safe to call repeatedly."""
    from finance.db.migrations import run_migrations
    from finance.services.categories import ensure_default_categories

    engine = get_engine(db_file)
    run_migrations(engine)
    with session_scope(engine) as s:
        ensure_default_categories(s)
    return engine


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on any error."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:  # includes Streamlit's rerun/stop signals
        session.rollback()
        raise
    finally:
        session.close()
