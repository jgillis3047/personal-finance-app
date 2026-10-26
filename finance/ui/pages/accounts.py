"""Accounts: list, add, update balances, edit, deactivate."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance.calculations.metrics import utilization
from finance.db.models import ACCOUNT_TYPES, ASSET_TYPES, LIABILITY_TYPES
from finance.services import accounts as svc
from finance.ui import common as ui


def _rows(accts, liab: bool):
    out = []
    for a in accts:
        if a.is_liability != liab:
            continue
        r = {
            "Name": a.name, "Type": a.type_label, "Institution": a.institution or "",
            "Balance": ui.dollars(a.current_balance_cents), "As of": a.balance_as_of,
        }
        if liab:
            u = utilization(a.current_balance_cents, a.credit_limit_cents)
            r |= {"Limit": ui.dollars(a.credit_limit_cents), "Utilization": None if u is None else u * 100,
                  "APR %": a.interest_rate, "Min payment": ui.dollars(a.minimum_payment_cents)}
        r |= {"In net worth": a.include_in_net_worth, "Status": "" if a.is_active else "Inactive",
              "Review": a.review_note if a.needs_review else ""}
        out.append(r)
    return pd.DataFrame(out)


MONEY = st.column_config.NumberColumn(format="$%.2f")


def render():
    ui.page_header("Accounts", "Bank accounts, savings, investments, cards and loans. Balances keep a full history.")
    show_inactive = st.toggle("Show inactive accounts", value=False)

    with ui.db() as s:
        accts = svc.list_accounts(s, active_only=not show_inactive)
        options = {a.id: f"{a.name} · {a.type_label}" for a in accts}
        assets = sum(a.current_balance_cents for a in accts if not a.is_liability and a.include_in_net_worth and a.is_active)
        liabs = sum(a.current_balance_cents for a in accts if a.is_liability and a.include_in_net_worth and a.is_active)
        df_assets, df_liabs = _rows(accts, False), _rows(accts, True)

    c = st.columns(3)
    c[0].metric("Assets", ui.money(assets))
    c[1].metric("Liabilities", ui.money(liabs))
    c[2].metric("Net worth", ui.money(assets - liabs))

    tab_list, tab_bal, tab_add, tab_edit = st.tabs(["All accounts", "Update a balance", "Add account", "Edit account"])

    with tab_list:
        st.markdown("##### Assets")
        if df_assets.empty:
            st.caption("No asset accounts yet.")
        else:
            ui.table(df_assets, column_config={"Balance": MONEY, "As of": st.column_config.DateColumn(format="MMM D, YYYY")})
        st.markdown("##### Liabilities")
        if df_liabs.empty:
            st.caption("No debts recorded.")
        else:
            ui.table(df_liabs, column_config={
                "Balance": MONEY, "Limit": MONEY, "Min payment": MONEY,
                "As of": st.column_config.DateColumn(format="MMM D, YYYY"),
                "Utilization": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                "APR %": st.column_config.NumberColumn(format="%.2f%%"),
            })
        st.caption("Enter liability balances as the positive amount you owe.")

    with tab_bal:
        if not options:
            st.caption("Add an account first.")
        else:
            acct_id = st.selectbox("Account", list(options), format_func=options.get, key="bal_acct")
            with ui.db() as s:
                a = svc.get(s, acct_id)
                hist = [(h.as_of_date, h.balance_cents, h.source, h.note or "") for h in svc.history(s, acct_id)]
                cur, is_liab = a.current_balance_cents, a.is_liability
            with st.form("bal_form", clear_on_submit=False):
                c1, c2 = st.columns(2)
                with c1:
                    new_bal = ui.money_input("Amount owed" if is_liab else "Balance", value_cents=cur, key="bal_amt")
                with c2:
                    as_of = st.date_input("As of", value=date.today(), max_value=date.today(), key="bal_date")
                note = st.text_input("Note (optional)", key="bal_note")
                if st.form_submit_button("Save balance", type="primary"):
                    ui.run_action(lambda s: svc.set_balance(s, acct_id, new_bal, as_of=as_of, note=note or None),
                                  "Balance saved")
            if hist:
                df = pd.DataFrame(hist, columns=["Date", "Balance", "Source", "Note"])
                if len(df) > 1:
                    fig = go.Figure(go.Scatter(x=df["Date"], y=df["Balance"] / 100, mode="lines+markers",
                                               line=dict(color=ui.RED if is_liab else ui.BLUE, width=3),
                                               hovertemplate="%{x|%b %d, %Y}: $%{y:,.2f}<extra></extra>"))
                    fig.update_layout(title="Balance history", yaxis_tickprefix="$", height=300)
                    ui.chart(fig, key="bal_hist")
                df["Balance"] = df["Balance"] / 100
                ui.table(df.iloc[::-1], column_config={"Balance": MONEY,
                                                       "Date": st.column_config.DateColumn(format="MMM D, YYYY")})

    with tab_add:
        with st.form("add_acct", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Account name *", max_chars=120)
                atype = st.selectbox("Type *", list(ACCOUNT_TYPES), format_func=ACCOUNT_TYPES.get)
                inst = st.text_input("Institution")
            with c2:
                bal = ui.money_input("Current balance (amount owed for debts)", value_cents=0, key="add_bal")
                as_of = st.date_input("Balance as of", value=date.today(), max_value=date.today())
                rate = st.number_input("Interest rate % (APR/APY)", min_value=0.0, max_value=100.0, value=None,
                                       step=0.25, format="%.3f")
            with st.expander("Debt details (cards & loans)"):
                d1, d2, d3 = st.columns(3)
                with d1:
                    limit = ui.money_input("Credit limit", value_cents=None, allow_blank=True, key="add_limit")
                with d2:
                    minpay = ui.money_input("Minimum payment", value_cents=None, allow_blank=True, key="add_min")
                with d3:
                    due = st.number_input("Payment due day", min_value=1, max_value=31, value=None, step=1)
            notes = st.text_area("Notes")
            if st.form_submit_button("Add account", type="primary"):
                ui.run_action(lambda s: svc.create_account(
                    s, name=name, account_type=atype, balance_cents=bal or 0, as_of=as_of, institution=inst,
                    interest_rate=rate, credit_limit_cents=limit, minimum_payment_cents=minpay,
                    payment_due_day=int(due) if due else None, notes=notes,
                ), f"Added {name}")

    with tab_edit:
        if not options:
            st.caption("No accounts yet.")
            return
        acct_id = st.selectbox("Account to edit", list(options), format_func=options.get, key="edit_acct")
        with ui.db() as s:
            a = svc.get(s, acct_id)
            snapshot = {k: getattr(a, k) for k in svc.EDITABLE_FIELDS}
        if snapshot["needs_review"] and snapshot["review_note"]:
            st.warning(snapshot["review_note"], icon=":material/rule:")
        with st.form(f"edit_acct_{acct_id}"):
            c1, c2 = st.columns(2)
            types = list(ACCOUNT_TYPES)
            with c1:
                name = st.text_input("Name", value=snapshot["name"], max_chars=120)
                atype = st.selectbox("Type", types, index=types.index(snapshot["account_type"]),
                                     format_func=ACCOUNT_TYPES.get)
                inst = st.text_input("Institution", value=snapshot["institution"] or "")
                rate = st.number_input("Interest rate % (APR/APY)", min_value=0.0, max_value=100.0,
                                       value=snapshot["interest_rate"], step=0.25, format="%.3f")
            with c2:
                limit = ui.money_input("Credit limit", value_cents=snapshot["credit_limit_cents"], allow_blank=True,
                                       key=f"e_lim_{acct_id}")
                minpay = ui.money_input("Minimum payment", value_cents=snapshot["minimum_payment_cents"],
                                        allow_blank=True, key=f"e_min_{acct_id}")
                orig = ui.money_input("Original loan amount", value_cents=snapshot["original_balance_cents"],
                                      allow_blank=True, key=f"e_orig_{acct_id}")
                due = st.number_input("Payment due day", min_value=1, max_value=31, value=snapshot["payment_due_day"],
                                      step=1)
            incl = st.checkbox("Include in net worth", value=snapshot["include_in_net_worth"])
            reviewed = st.checkbox("Mark as reviewed", value=not snapshot["needs_review"])
            notes = st.text_area("Notes", value=snapshot["notes"] or "")
            st.caption("To change the balance, use **Update a balance** so the history is kept.")
            if st.form_submit_button("Save changes", type="primary"):
                ui.run_action(lambda s: svc.update_account(
                    s, acct_id, name=name, account_type=atype, institution=inst, interest_rate=rate,
                    credit_limit_cents=limit, minimum_payment_cents=minpay, original_balance_cents=orig,
                    payment_due_day=int(due) if due else None, include_in_net_worth=incl,
                    needs_review=not reviewed, notes=notes,
                ), "Account updated")

        c1, c2 = st.columns(2)
        with c1:
            if snapshot["is_active"]:
                if st.button("Deactivate account", help="Hides it and removes it from totals. History is kept."):
                    ui.run_action(lambda s: svc.deactivate(s, acct_id), "Account deactivated")
            elif st.button("Reactivate account"):
                ui.run_action(lambda s: svc.update_account(s, acct_id, is_active=True), "Account reactivated")
        with c2:
            confirm = st.checkbox("I understand deleting is permanent", key=f"del_ok_{acct_id}")
            if st.button("Delete permanently", disabled=not confirm, type="secondary"):
                ui.run_action(lambda s: svc.delete_account(s, acct_id), "Account deleted")
