"""SQLite access and schema migration.

Why SQLite rather than a database server: this application has one writer, a
few tens of thousands of rows a year, and a hard requirement to be correct
during a twenty-minute burst a few nights a month. SQLite in WAL mode does that
with no network hop and no second service to keep alive.

The legacy system's data loss was never caused by SQLite. It was caused by
putting the file on an ephemeral disk and pushing it to GitHub by hand. Here the
file sits on a persistent volume and Litestream ships the write-ahead log to
object storage continuously -- see ../README.md.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import APP_DIR

SQL_DIR = APP_DIR / "sql"

# Migrations are applied in filename order and tracked in PRAGMA user_version.
# Alembic would be a reasonable choice at a larger size; at this size it is more
# machinery than the problem has.
MIGRATIONS = sorted(SQL_DIR.glob("*.sql"))


def utcnow() -> str:
    """Timestamps are ISO-8601 UTC with a Z suffix, so they sort as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Database:
    """A connection factory plus a migration runner.

    One connection per thread. Starlette runs sync endpoint functions in a
    threadpool, so a connection shared across threads would need
    check_same_thread=False and a lock around every use; thread-local
    connections are simpler and let SQLite's own locking do its job.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 10000")
            # NORMAL is the right durability level under WAL: a crash cannot
            # corrupt the database, only lose the last transaction or two, and
            # Litestream has already shipped them.
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """An explicit transaction. Commits on success, rolls back on any error.

        IMMEDIATE takes the write lock up front rather than on first write, so
        two concurrent writers fail fast against busy_timeout instead of
        deadlocking halfway through a transaction.
        """
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        return self.connect()

    def migrate(self) -> int:
        """Apply any migrations the database has not seen. Returns the version."""
        conn = self.connect()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index, path in enumerate(MIGRATIONS, start=1):
            if index <= version:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executescript(path.read_text(encoding="utf-8"))
                # executescript commits and ends the transaction, so the pragma
                # is set separately. It cannot be parameterised.
                conn.execute(f"PRAGMA user_version = {index}")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            version = index
        return version

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
