"""Import a budget workbook from the command line.

    .venv\\Scripts\\python scripts\\import_workbook.py "C:\\path\\to\\Finances.xlsx" [--force]
"""
import _bootstrap  # noqa: F401

import argparse
import sys

from finance import config
from finance.db import init_db, session_scope
from finance.importers.budget_workbook import WorkbookImportError, import_workbook

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--force", action="store_true", help="import even if this exact file was imported before")
    args = ap.parse_args()
    engine = init_db()
    try:
        with session_scope(engine) as s:
            res = import_workbook(s, args.path, force=args.force)
    except (WorkbookImportError, FileNotFoundError) as exc:
        print(f"Import failed: {exc}")
        sys.exit(1)
    if res.already_imported:
        print("This exact file was already imported. Use --force to import it again.")
    else:
        print(res.as_text())
        print(f"\nDatabase: {config.db_path()}")
