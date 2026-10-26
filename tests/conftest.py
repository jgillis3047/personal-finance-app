import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("FINANCE_APP_DB", str(path))
    yield path
    from finance.db.session import dispose_all

    dispose_all()


@pytest.fixture
def engine(db_file):
    from finance.db import init_db

    return init_db(db_file)


@pytest.fixture
def session(engine):
    from finance.db import session_scope

    with session_scope(engine) as s:
        yield s
