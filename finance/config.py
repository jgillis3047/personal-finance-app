"""Where the app keeps its data.

Resolution order for the database file:
1. ``FINANCE_APP_DB``        – full path to a .db file (used by tests and demo mode)
2. ``FINANCE_APP_DATA_DIR``  – a folder; the database is ``finance.db`` inside it
3. Default per-user folder that is *not* synced to the cloud:
   - Windows: ``%LOCALAPPDATA%\\PersonalFinanceApp``
   - Other:   ``~/.personal_finance_app``

The default deliberately avoids OneDrive/Desktop folders so the database
stays on this computer only.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "PersonalFinanceApp"


def data_dir() -> Path:
    db_override = os.environ.get("FINANCE_APP_DB")
    if db_override:
        path = Path(db_override).expanduser().resolve().parent
    elif os.environ.get("FINANCE_APP_DATA_DIR"):
        path = Path(os.environ["FINANCE_APP_DATA_DIR"]).expanduser().resolve()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        path = Path(os.environ["LOCALAPPDATA"]) / APP_DIR_NAME
    else:
        path = Path.home() / ".personal_finance_app"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    db_override = os.environ.get("FINANCE_APP_DB")
    if db_override:
        p = Path(db_override).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return data_dir() / "finance.db"


def backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_cloud_synced(path: Path) -> bool:
    """Best-effort check for common cloud-sync folders."""
    s = str(path).lower()
    return any(k in s for k in ("onedrive", "dropbox", "google drive", "icloud"))
