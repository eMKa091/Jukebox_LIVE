"""A stand-in for a Durable Object's `ctx.storage`, over the stdlib's sqlite3.

It does what the real one was seen to do on the Workers runtime
(docs/08-cloudflare-port.md, section 4), so the whole suite can run through
app.db_durable without the runtime:

  * `sql.exec(query, *bindings)` returns a cursor with `columnNames`,
    `raw().toArray()` and `rowsWritten`, and nothing else;
  * `BEGIN`, `SAVEPOINT`, `COMMIT` and `ROLLBACK` are refused, and so is
    `PRAGMA user_version`;
  * a constraint failure is a generic error whose message ends in
    `SQLITE_CONSTRAINT`, not sqlite3.IntegrityError;
  * `transactionSync(fn)` runs `fn` in one transaction, rolls back if it
    raises, and lets the exception through as itself;
  * one thing at a time: an object runs one request until it waits, so a
    lock is held for every statement and every transaction. The suite's
    thread races are then what the object makes of them: one after another.

What it cannot show is anything about speed or memory; that is step 8.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

REFUSED_TRANSACTION = (
    "Error: To execute a transaction, please use the state.storage.transaction() "
    "or state.storage.transactionSync() APIs instead of the SQL BEGIN TRANSACTION "
    "or SAVEPOINT statements."
)


class JsError(Exception):
    """What pyodide.ffi.JsException looks like from Python: a message."""


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def toArray(self) -> list[list]:  # noqa: N802 - the JavaScript name
        return [list(r) for r in self._rows]


class _Cursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self.columnNames = [d[0] for d in cursor.description or ()]  # noqa: N815
        self._rows = cursor.fetchall()
        self.rowsWritten = max(cursor.rowcount, 0)  # noqa: N815

    def raw(self) -> _Rows:
        return _Rows(self._rows)


class _Sql:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def exec(self, query: str, *bindings):
        with self._lock:
            return self._exec(query, bindings)

    def _exec(self, query: str, bindings: tuple):
        head = query.lstrip().upper()
        if head.startswith(("BEGIN", "SAVEPOINT", "COMMIT", "ROLLBACK", "END", "RELEASE")):
            raise JsError(REFUSED_TRANSACTION)
        if head.startswith("PRAGMA") and "USER_VERSION" in head:
            raise JsError("Error: not authorized: SQLITE_AUTH")
        try:
            return _Cursor(self._conn.execute(query, bindings))
        except sqlite3.IntegrityError as exc:
            raise JsError(f"Error: {exc}: SQLITE_CONSTRAINT") from None
        except sqlite3.Error as exc:
            raise JsError(f"Error: {exc}: SQLITE_ERROR") from None


class StandInStorage:
    def __init__(self, path: Path) -> None:
        # The test client serves from a thread of its own; the lock, not
        # sqlite3's same-thread check, is what keeps the connection to one.
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self.sql = _Sql(self._conn, self._lock)

    def transactionSync(self, fn):  # noqa: N802 - the JavaScript name
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                result = fn()
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
            return result

    def close(self) -> None:
        self._conn.close()
