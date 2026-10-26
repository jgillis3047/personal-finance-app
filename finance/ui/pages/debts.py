"""Debt overview (payoff calculator and strategies arrive in Stage 4)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from finance.calculations.metrics import utilization
from finance.services import accounts as acct_svc
from finance.ui import common as ui

MONEY = st.column_config.NumberColumn(format="$%.2f")


def render():
    ui.page_header("Debt Payoff", "Current balances owed, as entered or imported (not live lender balances).")
    with ui.db() as s:
        debts = [a for a in acct_svc.list_accounts(s) if a.is_liability]
        rows = [{
            "Debt": a.name, "Type": a.type_label, "Balance owed": ui.dollars(a.current_balance_cents),
            "APR %": a.interest_rate, "Min payment": ui.dollars(a.minimum_payment_cents),
            "Due day": a.payment_due_day,
            "Utilization": (lambda u: None if u is None else u * 100)(utilization(a.current_balance_cents, a.credit_limit_cents)),
            "Balance as of": a.balance_as_of,
            "Missing": ", ".join(x for x, ok in (("APR", a.interest_rate is not None),
                                                  ("min payment", a.minimum_payment_cents is not None)) if not ok),
        } for a in debts]
        total = sum(a.current_balance_cents for a in debts)
        mins = sum(a.minimum_payment_cents or 0 for a in debts)
    c = st.columns(3)
    c[0].metric("Total owed", ui.money(total))
    c[1].metric("Known minimum payments / month", ui.money(mins))
    c[2].metric("Debts missing an APR", str(sum(1 for r in rows if "APR" in r["Missing"])))
    if rows:
        ui.table(pd.DataFrame(rows), column_config={
            "Balance owed": MONEY, "Min payment": MONEY, "APR %": st.column_config.NumberColumn(format="%.2f%%"),
            "Utilization": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            "Balance as of": st.column_config.DateColumn(format="MMM D, YYYY"),
        })
        st.caption("Add APRs and minimum payments on **Accounts → Edit account** so payoff estimates can be calculated.")
    else:
        st.caption("No debts recorded.")
    ui.stage_notice(4, "amortization schedules, payoff dates, interest estimates, snowball vs. avalanche, and an "
                       "extra-payment calculator.")
