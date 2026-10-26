"""Personal Finance — Streamlit entry point.  Run with:  streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Personal Finance", page_icon="💵", layout="wide", initial_sidebar_state="expanded")

from finance.ui import common as ui  # noqa: E402
from finance.ui.pages import (  # noqa: E402
    accounts, bills, debts, import_page, net_worth, overview, placeholders, settings,
)

st.markdown(
    """
    <style>
      [data-testid="stMetric"] {
        border: 1px solid rgba(148,163,184,.28); border-radius: 12px; padding: 12px 16px;
        background: rgba(148,163,184,.06);
      }
      [data-testid="stMetricValue"] { font-size: 1.55rem; }
      .block-container { padding-top: 2.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

PAGES = [
    st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    st.Page(placeholders.transactions, title="Transactions", icon=":material/receipt_long:", url_path="transactions"),
    st.Page(import_page.render, title="Import Statements", icon=":material/upload_file:", url_path="import"),
    st.Page(accounts.render, title="Accounts", icon=":material/account_balance:", url_path="accounts"),
    st.Page(placeholders.budgets, title="Budgets", icon=":material/pie_chart:", url_path="budgets"),
    st.Page(bills.render, title="Bills", icon=":material/event:", url_path="bills"),
    st.Page(debts.render, title="Debt Payoff", icon=":material/trending_down:", url_path="debt"),
    st.Page(placeholders.savings, title="Savings & Investments", icon=":material/savings:", url_path="savings"),
    st.Page(net_worth.render, title="Net Worth", icon=":material/monitoring:", url_path="net-worth"),
    st.Page(placeholders.forecasting, title="Forecasting", icon=":material/query_stats:", url_path="forecast"),
    st.Page(placeholders.reports, title="Reports", icon=":material/description:", url_path="reports"),
    st.Page(settings.render, title="Settings", icon=":material/settings:", url_path="settings"),
]

ui.engine()  # create/upgrade the database before any page renders
nav = st.navigation(PAGES)
with st.sidebar:
    st.caption("🔒 Local only — your data never leaves this computer.")
ui.show_flash()
nav.run()
