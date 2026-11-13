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

# Migrations are applied in filename order, and each is recorded by name in
# schema_migrations in the same transaction that applies it. Not in PRAGMA
# user_version, which is what this file used first: the Durable Object's
# SQLite refuses that pragma outright (docs/08, U4). Alembic would be a
# reasonable choice at a larger size; at this size it is more machinery than
# the problem has.
MIGRATIONS = sorted(SQL_DIR.glob("*.sql"))

SCHEMA_MIGRATIONS = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
)


def utcnow() -> str:
    """Timestamps are ISO-8601 UTC with a Z suffix, so they sort as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def statements(script: str) -> list[str]:
    """Split a migration into its statements, dropping the comments.

    Needed because a transaction here is a callback that runs one statement at
    a time (see `transact`), and neither backend runs a script inside one.
    Quotes are respected, so a semicolon or `--` inside a string is not a
    split. A trigger body holds semicolons of its own and would be cut apart;
    there are no triggers, and the test that runs every migration says so the
    day one is added.
    """
    out: list[str] = []
    current: list[str] = []
    i, n = 0, len(script)
    while i < n:
        ch = script[i]
        if script.startswith("--", i):
            i = script.find("\n", i)
            i = n if i == -1 else i
            continue
        if script.startswith("/*", i):
            end = script.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in ("'", '"'):
            end = i + 1
            while end < n:
                if script[end] == ch:
                    if script.startswith(ch * 2, end):  # '' is a quote inside
                        end += 2
                        continue
                    break
                end += 1
            current.append(script[i : end + 1])
            i = end + 1
            continue
        if ch == ";":
            statement = "".join(current).strip()
            if statement:
                out.append(statement)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        out.append(tail)
    return out


def applied_migrations(conn) -> list[str]:
    """The names recorded in schema_migrations; none before it exists."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return []
    return [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]


def apply_migrations(db, *, counted_before: int = 0) -> int:
    """Apply what the database has not seen. Returns how many it now has.

    `db` is either backend: anything with `read()` and `transact(fn)`.
    `counted_before` is for a database made while the count lived in PRAGMA
    user_version: that many migrations are already in it, and are recorded as
    applied rather than run again.
    """
    done = set(applied_migrations(db.read()))
    if not done and counted_before:
        def adopt(conn) -> None:
            conn.execute(SCHEMA_MIGRATIONS)
            for path in MIGRATIONS[:counted_before]:
                conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (path.name, utcnow()),
                )

        db.transact(adopt)
        done = {path.name for path in MIGRATIONS[:counted_before]}

    for path in MIGRATIONS:
        if path.name in done:
            continue
        script = path.read_text(encoding="utf-8")

        # One transaction holds the migration and the row that records it:
        # either the whole migration is there and counted, or none of it is.
        def work(conn, name=path.name, script=script) -> None:
            conn.execute(SCHEMA_MIGRATIONS)
            for statement in statements(script):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (name, utcnow()),
            )

        db.transact(work)
        done.add(path.name)
    return len(done)


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
        """Apply any migrations the database has not seen. Returns how many it has."""
        # A file made before schema_migrations counted its migrations here.
        counted = self.connect().execute("PRAGMA user_version").fetchone()[0]
        return apply_migrations(self, counted_before=counted)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
