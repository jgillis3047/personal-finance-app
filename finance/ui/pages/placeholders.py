"""Pages scheduled for later stages. Each says exactly what's coming."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from finance.db.models import SAVINGS_INVESTMENT_TYPES
from finance.services import accounts as acct_svc
from finance.ui import common as ui


def transactions():
    ui.page_header("Transactions")
    ui.stage_notice(2, "a searchable, editable transaction list with filters (month, year, account, category), "
                       "category overrides, splits and transfer tagging.")


def budgets():
    ui.page_header("Budgets")
    ui.stage_notice(3, "monthly category budgets with budget vs. actual, remaining, % used, over-budget alerts, "
                       "previous-month comparison and copy-forward.")
    st.caption("Your planned monthly amounts per bill are already on the Bills page and will seed your first budget.")


def savings():
    ui.page_header("Savings & Investments")
    with ui.db() as s:
        rows = [{"Account": a.name, "Type": a.type_label, "Balance": ui.dollars(a.current_balance_cents),
                 "As of": a.balance_as_of, "Rate %": a.interest_rate}
                for a in acct_svc.list_accounts(s) if a.account_type in SAVINGS_INVESTMENT_TYPES]
    if rows:
        st.metric("Total savings & investments", ui.money(sum(round(r["Balance"] * 100) for r in rows)))
        ui.table(pd.DataFrame(rows), column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")})
    ui.stage_notice(4, "savings goals with targets, contributions and estimated completion dates, plus "
                       "contribution tracking. No investment growth is assumed unless you enter one.")


def forecasting():
    ui.page_header("Forecasting")
    ui.stage_notice(5, "end-of-month cash, upcoming obligations, debt and net worth projections, and what-if "
                       "scenarios — always labelled as estimates with assumptions shown.")


def reports():
    ui.page_header("Reports")
    ui.stage_notice(5, "a formatted 12-sheet Excel workbook export and CSV export of any table.")
