"""Bills & recurring payments (Stage 1 core; calendar + transaction matching in Stage 3)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from finance.db.models import BILL_KINDS, FREQUENCIES
from finance.services import accounts as acct_svc
from finance.services import bills as svc
from finance.services import income as income_svc
from finance.services.categories import all_categories, category_label
from finance.ui import common as ui
from finance.ui.pages.overview import STATUS_LABEL

MONEY = st.column_config.NumberColumn(format="$%.2f")


def _due_text(b) -> str:
    s = svc.schedule_of(b)
    if not s.is_dated:
        return "⚠ not set"
    if b.frequency in ("monthly",) and b.due_day:
        return f"Day {b.due_day}"
    if b.frequency == "twice_monthly":
        return f"Days {b.due_day or '?'} & {b.due_day_2 or '?'}"
    nd = s.next_due(date.today())
    return f"Next {nd:%b %d}" if nd else "—"


def render():
    ui.page_header("Bills", "Recurring bills, planned spending, debt payments and savings contributions.")
    today = date.today()

    with ui.db() as s:
        bills = svc.list_bills(s, active_only=False)
        active = [b for b in bills if b.is_active]
        monthly = {k: 0 for k in BILL_KINDS}
        for b in active:
            monthly[b.kind] += svc.monthly_cents(b)
        occ = svc.occurrences(s, today - timedelta(days=90), today + timedelta(days=30), today=today, bills=active)
        due = {n: sum(o.bill.amount_cents for o in occ if o.status in ("overdue", "due_today", "upcoming")
                      and o.due_date <= today + timedelta(days=n)) for n in (7, 14, 30)}
        occ_rows = [(o.bill.id, o.due_date, o.bill.name, o.bill.amount_cents, o.status, o.bill.autopay,
                     o.payment.id if o.payment else None) for o in occ]
        all_rows = [{
            "Name": b.name, "Type": BILL_KINDS[b.kind], "Category": category_label(b.category),
            "Amount": ui.dollars(b.amount_cents), "Frequency": FREQUENCIES[b.frequency],
            "Monthly equiv.": ui.dollars(svc.monthly_cents(b)), "Due": _due_text(b),
            "Autopay": b.autopay, "Pays toward": b.pays_account.name if b.pays_account else "",
            "Active": b.is_active, "Review": b.review_note if b.needs_review else "",
        } for b in bills]
        bill_opts = {b.id: b.name + ("" if b.is_active else " (inactive)") for b in bills}
        cats = {c.id: category_label(c) for c in all_categories(s)}
        accts = {a.id: f"{a.name} · {a.type_label}" for a in acct_svc.list_accounts(s)}
        incomes = [(i.id, i.name, i.kind, i.amount_cents, i.frequency, i.is_net, i.notes) for i in income_svc.list_income(s, active_only=False)]

    c = st.columns(4)
    c[0].metric("Fixed bills / month", ui.money(monthly["bill"] + monthly["debt_payment"]),
                help="Fixed bills plus debt payments (monthly equivalent).")
    c[1].metric("Planned variable spending", ui.money(monthly["planned"]))
    c[2].metric("Savings contributions", ui.money(monthly["savings"]))
    c[3].metric("Total committed / month", ui.money(sum(monthly.values())))
    c = st.columns(3)
    for col, n in zip(c, (7, 14, 30)):
        col.metric(f"Due in next {n} days", ui.money(due[n]))

    tab_up, tab_all, tab_edit, tab_inc = st.tabs(["Upcoming & paid", "All recurring items", "Add / edit", "Income"])

    with tab_up:
        window = st.segmented_control("Show", ["7 days", "14 days", "30 days"], default="30 days", key="bill_window") \
            if hasattr(st, "segmented_control") else st.radio("Show", ["7 days", "14 days", "30 days"], index=2,
                                                              horizontal=True, key="bill_window")
        days = int((window or "30 days").split()[0])
        rows = [r for r in occ_rows if r[1] <= today + timedelta(days=days)]
        open_rows = [r for r in rows if r[4] in ("overdue", "due_today", "upcoming")]
        done_rows = [r for r in rows if r[4] in ("paid", "skipped")]
        if open_rows:
            ui.table(pd.DataFrame([{"Due": r[1], "Bill": r[2], "Amount": ui.dollars(r[3]), "Status": STATUS_LABEL[r[4]],
                                    "Autopay": "Yes" if r[5] else ""} for r in open_rows]),
                     column_config={"Due": st.column_config.DateColumn(format="ddd, MMM D"), "Amount": MONEY})
            st.markdown("##### Mark a bill paid")
            choices = {i: f"{r[2]} — due {r[1]:%b %d} ({ui.money(r[3])})" for i, r in enumerate(open_rows)}
            pick = st.selectbox("Bill", list(choices), format_func=choices.get, key="mp_pick")
            with st.form(f"mark_paid_{pick}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    paid_on = st.date_input("Paid on", value=today, max_value=today)
                with c2:
                    amt = ui.money_input("Amount paid", value_cents=open_rows[pick][3] if pick is not None else 0,
                                         key=f"mp_amt_{pick}")
                with c3:
                    status = st.selectbox("Mark as", ["paid", "skipped"], format_func=str.capitalize)
                if st.form_submit_button("Save", type="primary") and pick is not None:
                    r = open_rows[pick]
                    ui.run_action(lambda s: svc.mark_paid(s, r[0], r[1], paid_date=paid_on if status == "paid" else None,
                                                          amount_cents=amt, status=status), f"{r[2]} marked {status}")
            st.caption("Bills are only marked paid when you say so — a passed due date never counts as paid.")
        else:
            st.success("Nothing unpaid in this window.", icon=":material/task_alt:")
        if done_rows:
            st.markdown("##### Recently paid")
            ui.table(pd.DataFrame([{"Due": r[1], "Bill": r[2], "Status": STATUS_LABEL[r[4]]} for r in done_rows]),
                     column_config={"Due": st.column_config.DateColumn(format="MMM D, YYYY")})
            undo = {r[6]: f"{r[2]} — {r[1]:%b %d}" for r in done_rows}
            c1, c2 = st.columns([3, 1])
            with c1:
                pid = st.selectbox("Undo a payment", list(undo), format_func=undo.get, key="undo_pick")
            with c2:
                st.write("")
                if st.button("Undo", key="undo_btn"):
                    ui.run_action(lambda s: svc.unmark(s, pid), "Payment removed")

    with tab_all:
        if all_rows:
            ui.table(pd.DataFrame(all_rows), column_config={"Amount": MONEY, "Monthly equiv.": MONEY})
        else:
            st.caption("No recurring items yet — add one on the next tab or import your workbook.")

    with tab_edit:
        mode_new = "➕ New bill"
        pick = st.selectbox("Bill", [mode_new] + list(bill_opts), format_func=lambda k: k if k == mode_new else bill_opts[k],
                            key="edit_bill_pick")
        existing = None
        if pick != mode_new:
            with ui.db() as s:
                b = svc.get(s, pick)
                existing = {k: getattr(b, k) for k in svc.EDITABLE}
            if existing["needs_review"] and existing["review_note"]:
                st.warning(existing["review_note"], icon=":material/rule:")
        e = existing or {}
        cat_ids = [None] + list(cats)
        acct_ids = [None] + list(accts)
        with st.form(f"bill_form_{pick}"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Name *", value=e.get("name") or "", max_chars=120)
                kind = st.selectbox("Type", list(BILL_KINDS), format_func=BILL_KINDS.get,
                                    index=list(BILL_KINDS).index(e.get("kind") or "bill"))
                cat = st.selectbox("Category", cat_ids, format_func=lambda k: "—" if k is None else cats[k],
                                   index=cat_ids.index(e.get("category_id")) if e.get("category_id") in cat_ids else 0)
                amount = ui.money_input("Amount *", value_cents=e.get("amount_cents") or 0, key=f"b_amt_{pick}")
                freq = st.selectbox("Frequency", list(FREQUENCIES), format_func=FREQUENCIES.get,
                                    index=list(FREQUENCIES).index(e.get("frequency") or "monthly"))
            with c2:
                due_day = st.number_input("Due day of month (monthly / twice-monthly)", min_value=1, max_value=31,
                                          value=e.get("due_day"), step=1)
                due_day_2 = st.number_input("Second due day (twice-monthly)", min_value=1, max_value=31,
                                            value=e.get("due_day_2"), step=1)
                anchor = st.date_input("First due date (weekly / biweekly / quarterly / annual)",
                                       value=e.get("anchor_date"))
                pay_acct = st.selectbox("Paid from", acct_ids, format_func=lambda k: "—" if k is None else accts[k],
                                        index=acct_ids.index(e.get("payment_account_id")) if e.get("payment_account_id") in acct_ids else 0)
                pays = st.selectbox("Pays toward (loan / card / savings account)", acct_ids,
                                    format_func=lambda k: "—" if k is None else accts[k],
                                    index=acct_ids.index(e.get("pays_account_id")) if e.get("pays_account_id") in acct_ids else 0)
            c3, c4, c5 = st.columns(3)
            autopay = c3.checkbox("Autopay", value=bool(e.get("autopay")))
            active_flag = c4.checkbox("Active", value=e.get("is_active", True) is not False)
            reviewed = c5.checkbox("Reviewed", value=not e.get("needs_review", False))
            notes = st.text_area("Notes", value=e.get("notes") or "")
            if st.form_submit_button("Save bill", type="primary"):
                fields = dict(name=name, kind=kind, category_id=cat, amount_cents=amount, frequency=freq,
                              due_day=int(due_day) if due_day else None, due_day_2=int(due_day_2) if due_day_2 else None,
                              anchor_date=anchor or None, payment_account_id=pay_acct, pays_account_id=pays,
                              autopay=autopay, is_active=active_flag, needs_review=not reviewed, notes=notes)
                if existing:
                    ui.run_action(lambda s: svc.update_bill(s, pick, **fields), f"Saved {name}")
                else:
                    ui.run_action(lambda s: svc.create_bill(s, **fields), f"Added {name}")

    with tab_inc:
        st.caption("Projected income. Actual deposits will be tracked from imported transactions (Stage 2–3).")
        if incomes:
            ui.table(pd.DataFrame([{"Source": i[1], "Type": income_svc.INCOME_KINDS[i[2]], "Amount": ui.dollars(i[3]),
                                    "Frequency": FREQUENCIES[i[4]], "Take-home": i[5], "Notes": i[6] or ""}
                                   for i in incomes]), column_config={"Amount": MONEY})
        inc_new = "➕ New income source"
        inc_opts = {i[0]: i for i in incomes}
        ipick = st.selectbox("Income source", [inc_new] + list(inc_opts),
                             format_func=lambda k: k if k == inc_new else inc_opts[k][1], key="inc_pick")
        cur = inc_opts.get(ipick)
        with st.form(f"inc_form_{ipick}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                iname = st.text_input("Name *", value=cur[1] if cur else "")
                ikind = st.selectbox("Type", list(income_svc.INCOME_KINDS), format_func=income_svc.INCOME_KINDS.get,
                                     index=list(income_svc.INCOME_KINDS).index(cur[2]) if cur else 0)
            with c2:
                iamt = ui.money_input("Amount per paycheck/period *", value_cents=cur[3] if cur else 0, key=f"i_amt_{ipick}")
                ifreq = st.selectbox("Frequency", list(FREQUENCIES), format_func=FREQUENCIES.get,
                                     index=list(FREQUENCIES).index(cur[4]) if cur else list(FREQUENCIES).index("monthly"))
            with c3:
                inet = st.checkbox("Take-home (after tax)", value=cur[5] if cur else True)
                inotes = st.text_input("Notes", value=(cur[6] or "") if cur else "")
            if st.form_submit_button("Save income", type="primary"):
                f = dict(name=iname, kind=ikind, amount_cents=iamt, frequency=ifreq, is_net=inet, notes=inotes)
                if cur:
                    ui.run_action(lambda s: income_svc.update_income(s, ipick, **f), "Income updated")
                else:
                    ui.run_action(lambda s: income_svc.create_income(s, **f), "Income added")
