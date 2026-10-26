"""Shared Streamlit helpers."""
from __future__ import annotations

import inspect
from contextlib import contextmanager
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance.db import init_db, session_scope
from finance.utils.money import fmt, to_cents, MoneyError

# Chart palette (works on light and dark backgrounds)
BLUE, TEAL, AMBER, RED, GREEN, SLATE = "#3B82F6", "#14B8A6", "#F59E0B", "#EF4444", "#22C55E", "#94A3B8"
SERIES = ["#3B82F6", "#14B8A6", "#F59E0B", "#A855F7", "#EC4899", "#22C55E", "#64748B", "#F97316", "#06B6D4", "#84CC16"]


@st.cache_resource(show_spinner=False)
def engine():
    return init_db()


@contextmanager
def db():
    with session_scope(engine()) as s:
        yield s


def _wide_kwargs(fn) -> dict:
    """Full-width kwargs for this Streamlit version: newer releases take
    width="stretch" and deprecate use_container_width; older ones only know the latter."""
    try:
        w = inspect.signature(fn).parameters.get("width")
    except (TypeError, ValueError):
        w = None
    if w is not None and isinstance(w.default, str):
        return {"width": "stretch"}
    return {"use_container_width": True}


def table(df: pd.DataFrame, **kwargs):
    kwargs.setdefault("hide_index", True)
    st.dataframe(df, **_wide_kwargs(st.dataframe), **kwargs)


def chart(fig: go.Figure, key: str | None = None):
    fig.update_layout(
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=13),
        hoverlabel=dict(namelength=-1),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.2)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.2)", zeroline=False)
    st.plotly_chart(fig, key=key, config={"displaylogo": False}, **_wide_kwargs(st.plotly_chart))


def money(cents: int | None, **kw) -> str:
    return fmt(cents, **kw)


def dollars(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


def money_input(label: str, *, value_cents: int | None = 0, key: str, help: str | None = None,
                allow_blank: bool = False) -> int | None:
    """Number input in dollars that returns cents (or None when blank & allowed)."""
    v = st.number_input(
        label, min_value=0.0, step=1.0, format="%.2f", key=key, help=help,
        value=None if (value_cents is None and allow_blank) else (value_cents or 0) / 100,
    )
    if v is None:
        return None
    try:
        return to_cents(str(round(v, 2)))
    except MoneyError:
        return None


def run_action(fn, success: str) -> bool:
    """Run a database change in its own transaction, then rerun the page.

    Validation errors are shown inline and nothing is saved. The rerun happens
    *after* the transaction commits (Streamlit's rerun signal would otherwise
    abort the commit).
    """
    from finance.services.accounts import ValidationError

    try:
        with db() as s:
            fn(s)
    except ValidationError as exc:
        st.error(str(exc))
        return False
    st.session_state["_flash"] = success
    st.rerun()
    return True


def show_flash():
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.toast(msg, icon=":material/check_circle:")


def page_header(title: str, subtitle: str | None = None):
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def stage_notice(stage: int, what: str):
    st.info(f"**Coming in Stage {stage}:** {what}", icon=":material/construction:")


def today() -> date:
    return date.today()


def review_badge(flag: bool) -> str:
    return "⚠ Review" if flag else ""
