"""Settings: data location, backups, categories, audit log."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

from finance import __version__, config
from finance.db.migrations import latest_version
from finance.services import audit, backup
from finance.services.categories import all_categories, category_label
from finance.ui import common as ui


def render():
    ui.page_header("Settings")

    st.subheader("Your data")
    path = config.db_path()
    st.write(f"Database file: `{path}`")
    if config.is_cloud_synced(path):
        st.warning("This database is inside a cloud-synced folder, so copies will leave this computer. "
                   "Remove FINANCE_APP_DB / FINANCE_APP_DATA_DIR to use the local default.")
    else:
        st.caption("Stored only on this computer (outside OneDrive/Dropbox). Nothing is sent anywhere.")
    with ui.db() as s:
        v = s.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
    st.caption(f"App version {__version__} · database schema v{v} (latest v{latest_version()})")

    st.subheader("Backups")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Create backup now", type="primary"):
            p = backup.create_backup()
            st.success(f"Saved {p.name}")
    with c2:
        st.download_button("Download a backup copy", data=backup.backup_bytes(),
                           file_name=f"finance-backup-{datetime.now():%Y%m%d}.db",
                           mime="application/octet-stream")
    files = backup.list_backups()
    if files:
        ui.table(pd.DataFrame([{"Backup": f.name, "Size (KB)": round(f.stat().st_size / 1024, 1),
                                "Created": datetime.fromtimestamp(f.stat().st_mtime)} for f in files[:20]]))
        st.caption(f"Backup folder: `{config.backup_dir()}`. To restore, close the app and copy a backup over "
                   f"`{path.name}` (restore from the app arrives in Stage 5).")

    st.subheader("Appearance")
    st.caption("Switch between light and dark: menu (⋮, top right) → Settings → Theme.")

    st.subheader("Categories")
    with ui.db() as s:
        cats = [{"Category": category_label(c), "Kind": c.kind} for c in all_categories(s)]
    with st.expander(f"{len(cats)} categories"):
        ui.table(pd.DataFrame(cats))
        st.caption("Custom categories, subcategories and merchant rules can be managed in Stage 2.")

    st.subheader("Audit history")
    with ui.db() as s:
        rows = [{"When": a.ts, "What": a.entity, "ID": a.entity_id, "Action": a.action,
                 "Details": _short(a.changes)} for a in audit.recent(s, 300)]
    if rows:
        ui.table(pd.DataFrame(rows), column_config={"When": st.column_config.DatetimeColumn(format="MMM D h:mm a")})


def _short(changes: str | None) -> str:
    if not changes:
        return ""
    try:
        d = json.loads(changes)
    except ValueError:
        return changes[:200]
    return "; ".join(f"{k}: {v}" for k, v in d.items())[:300]
