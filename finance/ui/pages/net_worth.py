"""Net worth: breakdown and history from balance snapshots."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance.services import accounts as acct_svc
from finance.services import dashboard
from finance.ui import common as ui


def render():
    ui.page_header("Net Worth", "Total assets minus total liabilities, from your recorded balances.")
    with ui.db() as s:
        accts = [a for a in acct_svc.list_accounts(s) if a.include_in_net_worth]
        series = dashboard.net_worth_series(s)
        by_type: dict[tuple[str, bool], int] = defaultdict(int)
        for a in accts:
            by_type[(a.type_label, a.is_liability)] += a.current_balance_cents
    assets = sum(v for (t, liab), v in by_type.items() if not liab)
    liabs = sum(v for (t, liab), v in by_type.items() if liab)
    c = st.columns(3)
    c[0].metric("Assets", ui.money(assets))
    c[1].metric("Liabilities", ui.money(liabs))
    c[2].metric("Net worth", ui.money(assets - liabs))

    left, right = st.columns(2)
    with left:
        items = sorted(by_type.items(), key=lambda kv: (kv[0][1], -kv[1]))
        if items:
            fig = go.Figure(go.Bar(
                x=[ui.dollars(v) * (-1 if liab else 1) for (t, liab), v in items],
                y=[t for (t, _), _ in items], orientation="h",
                marker_color=[ui.RED if liab else ui.BLUE for (_, liab), _ in items],
                hovertemplate="%{y}: $%{x:,.2f}<extra></extra>"))
            fig.update_layout(title="Assets (blue) and liabilities (red) by type", xaxis_tickprefix="$", height=360)
            ui.chart(fig, key="nw_types")
    with right:
        if series:
            df = pd.DataFrame(series, columns=["date", "assets", "liabilities", "net"])
            fig = go.Figure()
            fig.add_scatter(x=df["date"], y=df["assets"] / 100, name="Assets", line=dict(color=ui.BLUE))
            fig.add_scatter(x=df["date"], y=df["liabilities"] / 100, name="Liabilities", line=dict(color=ui.RED))
            fig.add_scatter(x=df["date"], y=df["net"] / 100, name="Net worth", line=dict(color=ui.GREEN, width=3))
            fig.update_traces(mode="lines+markers", hovertemplate="%{x|%b %d, %Y}: $%{y:,.2f}<extra></extra>")
            fig.update_layout(title="History", yaxis_tickprefix="$", height=360)
            ui.chart(fig, key="nw_hist")
            if len(df) == 1:
                st.caption("One data point so far. Update balances on the Accounts page (e.g. monthly) to build the trend.")
