"""Create or upgrade the database. Safe to run any number of times."""
import _bootstrap  # noqa: F401

from finance import config
from finance.db import init_db

if __name__ == "__main__":
    init_db()
    print(f"Database ready: {config.db_path()}")
