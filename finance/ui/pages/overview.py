"""Overview dashboard."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance.db.models import BILL_KINDS
from finance.services import dashboard
from finance.services import bills as bill_svc
from finance.ui import common as ui

STATUS_LABEL = {"overdue": "🔴 Overdue", "due_today": "🟠 Due today", "upcoming": "Upcoming", "paid": "✅ Paid",
                "skipped": "Skipped"}


def _offer_nearby_workbooks():
    """First-run convenience: offer to import .xlsx budget workbooks found in the folder above the app."""
    from finance.importers import budget_workbook as wbi

    app_root = Path(__file__).resolve().parents[3]
    candidates = sorted(p for p in app_root.parent.glob("*.xlsx") if not p.name.startswith("~$"))
    for p in candidates[:5]:
        try:
            kinds = {b.kind for b in wbi.parse_workbook(p)}
        except Exception:
            continue
        if not kinds:
            continue
        st.markdown(f"Found a budget workbook next to the app: **{p.name}**")
        if st.button(f"Import {p.name}", type="primary", key=f"quick_import_{p.name}"):
            try:
                with ui.db() as s:
                    res = wbi.import_workbook(s, p)
            except wbi.WorkbookImportError as exc:
                st.error(str(exc))
                return
            st.session_state["_last_import"] = res.as_text()
            st.session_state["_flash"] = f"Imported {p.name}: {len(res.created)} items created"
            st.rerun()


def render():
    with ui.db() as s:
        d = dashboard.build(s)
        nw = dashboard.net_worth_series(s)
        upcoming = bill_svc.upcoming(s, 30)
        up_rows = [{
            "Due": o.due_date, "Bill": o.bill.name, "Amount": ui.dollars(o.bill.amount_cents),
            "In": "today" if o.days_until == 0 else (f"{o.days_until} days" if o.days_until > 0 else f"{-o.days_until} days ago"),
            "Status": STATUS_LABEL[o.status], "Autopay": "Yes" if o.bill.autopay else "",
        } for o in upcoming]
        has_any = bool(d.assets_cents or d.liabilities_cents or d.income_cents or d.outflow_by_kind)

    ui.page_header("Overview", f"As of {ui.today():%A, %B %d, %Y}")

    if not has_any:
        st.info("No data yet. Add accounts on the **Accounts** page, or import your budget workbook from "
                "**Import Statements**.", icon=":material/info:")
        _offer_nearby_workbooks()
        return

    if d.review_count:
        st.warning(f"**{d.review_count} item(s) need a quick review** (missing due dates, interest rates, or "
                   "unclear categories). Look for ⚠ on the Accounts and Bills pages.", icon=":material/rule:")
    if d.overdue_count:
        st.error(f"{d.overdue_count} bill(s) are overdue — mark them paid on the Bills page if you've already paid.",
                 icon=":material/schedule:")

    # ---- Monthly plan --------------------------------------------------------
    st.subheader("This month (planned)")
    c = st.columns(4)
    c[0].metric("Monthly income", ui.money(d.income_cents), help="Sum of your active income sources, as monthly amounts.")
    c[1].metric("Monthly expenses", ui.money(d.expenses_cents),
                help="Bills + planned variable spending + debt payments. Excludes savings/investment contributions.")
    c[2].metric("Monthly cash flow", ui.money(d.cash_flow_cents, signed=True),
                help="Income minus expenses (before savings contributions).")
    rate = d.savings_rate
    c[3].metric("Savings rate", "—" if rate is None else f"{rate:.1%}",
                help="Share of income not spent: (income − expenses) ÷ income.")
    st.caption(f"After your {ui.money(d.savings_contrib_cents)} of planned savings contributions, "
               f"**{ui.money(d.left_after_plan_cents, signed=True)}** is left unassigned each month.  "
               + ("Figures are planned amounts from your bills and income — actuals appear once you import "
                  "transactions (Stage 2)." if not d.transaction_count else ""))

    # ---- Balances ------------------------------------------------------------
    st.subheader("Balances")
    c = st.columns(5)
    c[0].metric("Cash & bank accounts", ui.money(d.cash_cents), help="Checking, savings, high-yield savings and cash.")
    c[1].metric("Available after bills", ui.money(d.available_after_bills_cents),
                help="Cash & bank balances minus unpaid bills and debt payments due in the next 30 days.")
    c[2].metric("Savings & investments", ui.money(d.savings_investments_cents),
                help="Savings, high-yield savings, retirement and brokerage balances.")
    c[3].metric("Total debt", ui.money(d.liabilities_cents))
    c[4].metric("Net worth", ui.money(d.net_worth_cents), help="Total assets minus total liabilities.")
    if d.receivables_cents:
        st.caption(f"Assets include {ui.money(d.receivables_cents)} that people owe you.")

    # ---- Charts --------------------------------------------------------------
    left, right = st.columns(2)
    with left:
        kinds = ["bill", "debt_payment", "planned", "savings"]
        colors = {"bill": ui.BLUE, "debt_payment": ui.RED, "planned": ui.AMBER, "savings": ui.TEAL}
        fig = go.Figure()
        fig.add_bar(name="Income", x=["Income"], y=[ui.dollars(d.income_cents)], marker_color=ui.GREEN,
                    hovertemplate="Income: $%{y:,.2f}<extra></extra>")
        for k in kinds:
            v = d.outflow_by_kind.get(k, 0)
            if v:
                fig.add_bar(name=BILL_KINDS[k], x=["Planned outflows"], y=[ui.dollars(v)], marker_color=colors[k],
                            hovertemplate=f"{BILL_KINDS[k]}: $%{{y:,.2f}}<extra></extra>")
        fig.update_layout(barmode="stack", title="Income vs. planned outflows (monthly)", yaxis_tickprefix="$",
                          height=360)
        ui.chart(fig, key="ov_income_vs")
    with right:
        cats = d.spending_by_category
        if cats:
            fig = go.Figure(go.Pie(labels=list(cats), values=[ui.dollars(v) for v in cats.values()], hole=0.55,
                                   marker=dict(colors=ui.SERIES), sort=False, textinfo="percent",
                                   hovertemplate="%{label}: $%{value:,.2f} (%{percent})<extra></extra>"))
            fig.update_layout(title="Planned spending by category", height=360, legend=dict(orientation="v", x=1.02, y=0.5))
            ui.chart(fig, key="ov_by_cat")

    left, right = st.columns(2)
    with left:
        if d.debt_by_account:
            names = [n for n, _ in d.debt_by_account][::-1]
            vals = [ui.dollars(v) for _, v in d.debt_by_account][::-1]
            fig = go.Figure(go.Bar(x=vals, y=names, orientation="h", marker_color=ui.RED,
                                   hovertemplate="%{y}: $%{x:,.2f}<extra></extra>"))
            fig.update_layout(title="Debt by account", xaxis_tickprefix="$", height=320)
            ui.chart(fig, key="ov_debt")
    with right:
        if nw:
            df = pd.DataFrame(nw, columns=["date", "assets", "liabilities", "net"])
            fig = go.Figure()
            fig.add_scatter(x=df["date"], y=df["net"] / 100, mode="lines+markers", name="Net worth",
                            line=dict(color=ui.BLUE, width=3), hovertemplate="%{x|%b %d, %Y}: $%{y:,.2f}<extra></extra>")
            fig.update_layout(title="Net worth over time", yaxis_tickprefix="$", height=320, showlegend=False)
            ui.chart(fig, key="ov_nw")
            if len(df) == 1:
                st.caption("One data point so far — the trend fills in each time you update balances.")

    # ---- Upcoming bills & transactions ---------------------------------------
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Upcoming bills (30 days)")
        if up_rows:
            ui.table(pd.DataFrame(up_rows), column_config={
                "Due": st.column_config.DateColumn(format="ddd, MMM D"),
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
            })
            st.caption(f"Unpaid bills & debt payments due in the next 30 days: **{ui.money(d.due_30_unpaid_cents)}**")
        else:
            st.caption("Nothing due in the next 30 days.")
        if d.undated_bill_count:
            st.caption(f"{d.undated_bill_count} recurring item(s) have no due date yet, so they're not on this list. "
                       "Add due dates on the Bills page.")
    with right:
        st.subheader("Recent transactions")
        if not d.transaction_count:
            st.caption("No transactions yet. Statement imports (CSV/Excel) arrive in Stage 2.")
