"""Render every page headlessly with Streamlit's AppTest (requires streamlit installed)."""
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

PAGES = [
    ("overview", "render"), ("accounts", "render"), ("bills", "render"), ("debts", "render"),
    ("net_worth", "render"), ("import_page", "render"), ("settings", "render"),
    ("placeholders", "transactions"), ("placeholders", "budgets"), ("placeholders", "savings"),
    ("placeholders", "forecasting"), ("placeholders", "reports"),
]


@pytest.fixture
def seeded(engine):
    from finance.db import session_scope
    import importlib.util

    spec = importlib.util.spec_from_file_location("example", ROOT / "scripts" / "load_example_data.py")
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with session_scope(engine) as s:
        mod.load(s)
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.mark.parametrize("module,fn", PAGES)
def test_page_renders(seeded, module, fn):
    script = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom finance.ui.pages import {module}\n{module}.{fn}()\n"
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception, at.exception


def test_full_app_starts(seeded):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception


def test_empty_database_renders(engine):
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    st.cache_resource.clear()
