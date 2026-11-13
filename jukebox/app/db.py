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
from collections.abc import Callable
from typing import TypeVar
from datetime import datetime, timezone
from pathlib import Path

from .config import APP_DIR

SQL_DIR = APP_DIR / "sql"

T = TypeVar("T")

# What the rules catch when a constraint refuses a write. Named here, not
# taken from sqlite3 where it is used, so that a second backend -- the Durable
# Object's built-in SQLite, docs/08-cloudflare-port.md -- can raise the same
# thing without the rules knowing which database they are talking to.
IntegrityError = sqlite3.IntegrityError

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

    def transact(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run `fn(conn)` inside one transaction and return what it returns.

        Whatever `fn` raises rolls the transaction back and is raised again.
        `fn` must not be async: the whole of it is one uninterrupted unit.

        A callback rather than a `with` block because the Durable Object's
        SQLite only offers transactions as a callback, and the rules should
        read the same on both (docs/08-cloudflare-port.md, step 2).

        IMMEDIATE takes the write lock up front rather than on first write, so
        two concurrent writers fail fast against busy_timeout instead of
        deadlocking halfway through a transaction.
        """
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = fn(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return result

    def read(self) -> sqlite3.Connection:
        return self.connect()

    def migrate(self) -> int:
        """Apply any migrations the database has not seen. Returns the version."""
        conn = self.connect()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index, path in enumerate(MIGRATIONS, start=1):
            if index <= version:
                continue
            # One transaction, opened and closed inside the script itself:
            # executescript commits whatever is open before it starts, so a
            # BEGIN issued from Python never covered the script. The version
            # bump is in the same transaction -- either the whole migration
            # is there and counted, or none of it is. (The pragma cannot be
            # parameterised.)
            script = (
                "BEGIN IMMEDIATE;\n"
                f"{path.read_text(encoding='utf-8')}\n"
                f"PRAGMA user_version = {index};\n"
                "COMMIT;"
            )
            try:
                conn.executescript(script)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            version = index
        return version

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
