"""Local database backups using SQLite's online backup API (safe while the app runs)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from finance import config


def backup_to(dest: Path, source: Path | None = None) -> Path:
    source = source or config.db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    return dest


def create_backup(label: str = "manual") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return backup_to(config.backup_dir() / f"finance-{label}-{stamp}.db")


def backup_bytes() -> bytes:
    tmp = config.backup_dir() / ".download-tmp.db"
    backup_to(tmp)
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return data


def list_backups() -> list[Path]:
    return sorted(config.backup_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
