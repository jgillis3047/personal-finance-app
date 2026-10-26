"""Import: budget workbook now; bank statements in Stage 2."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import select

from finance.db.models import ImportRecord
from finance.importers import budget_workbook as wbi
from finance.ui import common as ui

KIND_LABEL = {"income": "Income", "expenses": "Recurring expenses", "credit": "Credit cards",
              "balances": "Account balances", "receivables": "Money owed to you"}


def render():
    ui.page_header("Import Statements")
    st.subheader("Budget workbook (.xlsx)")
    st.caption("Bring in a personal budget spreadsheet with tables like Income, Expenses, Credit cards and balances. "
               "Re-import an updated copy any time — amounts update and balance history is kept; nothing is deleted.")
    up = st.file_uploader("Choose workbook", type=["xlsx"], key="wb_upload")
    if up is not None:
        data = up.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "upload.xlsx"
            p.write_bytes(data)
            try:
                blocks = wbi.parse_workbook(p)
            except Exception as exc:
                st.error(f"Couldn't read that workbook: {exc}")
                blocks = []
            if blocks:
                st.markdown("**Preview — tables found:**")
                for b in blocks:
                    with st.expander(f"{KIND_LABEL[b.kind]} · sheet '{b.sheet}' · {len(b.rows)} rows"):
                        df = pd.DataFrame(b.rows, columns=[h.title() for h in b.headers]).astype(str)
                        ui.table(df.replace({"None": ""}))
                with ui.db() as s:
                    prior = s.scalar(select(ImportRecord).where(ImportRecord.file_sha256 == sha))
                force = False
                if prior:
                    st.info(f"This exact file was already imported on {prior.imported_at:%b %d, %Y %I:%M %p}.")
                    force = st.checkbox("Import it again anyway")
                if st.button("Import workbook", type="primary", disabled=bool(prior) and not force):
                    try:
                        with ui.db() as s:
                            res = wbi.import_workbook(s, p, force=force, display_name=up.name)
                    except wbi.WorkbookImportError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["_last_import"] = res.as_text()
                        st.session_state["_flash"] = f"Imported: {len(res.created)} created, {len(res.updated)} updated"
                        st.rerun()
            elif blocks == [] and up is not None:
                st.warning("No recognisable tables found. The importer looks for header rows such as "
                           "'Income | Amount', 'Expenses | Amount', 'Type | Allowed Amount | Owe', 'Type | Amount'.")

    if st.session_state.get("_last_import"):
        with st.expander("Last import summary", expanded=True):
            st.code(st.session_state["_last_import"], language=None)

    st.divider()
    st.subheader("Bank & card statements (CSV, Excel, PDF)")
    ui.stage_notice(2, "CSV/Excel statement import with column detection and mapping, saved bank templates, "
                       "duplicate detection, merchant clean-up, auto-categorization and transfer detection. "
                       "Text-based PDF statements follow in Stage 5.")

    st.divider()
    st.subheader("Import history")
    with ui.db() as s:
        hist = [{"When": r.imported_at, "File": r.filename, "Type": r.source_type, "Changes": r.rows_imported}
                for r in s.scalars(select(ImportRecord).order_by(ImportRecord.id.desc()))]
    if hist:
        ui.table(pd.DataFrame(hist), column_config={"When": st.column_config.DatetimeColumn(format="MMM D, YYYY h:mm a")})
    else:
        st.caption("No imports yet.")
