"""The Durable Object's SQLite, behind the same interface as app.db.Database.

The rules (app.domain) take a `Database` and call `read()`, `transact(fn)` and,
on the connection they are handed, `execute` and `executemany`. This module
gives them exactly that over the object's own storage, `ctx.storage.sql`, so
not one rule knows which database it is talking to (docs/08-cloudflare-port.md,
step 5).

What differs underneath, each found by running it (docs/08, section 4):

  * Transactions are a callback, `ctx.storage.transactionSync(fn)`; `BEGIN`
    is refused. Whatever the callback raises rolls back and arrives as itself.
  * The cursor has no `lastrowid` and no `rowcount`. After a write this asks
    `last_insert_rowid()` and `changes()`, which SQLite answers for the last
    statement on the connection, which in one object is this one.
  * A cursor left half-read blocks the next schema change, so every result is
    read in full at once. The results here are a few hundred rows at most.
  * A constraint failure arrives as a JavaScript error whose message names it;
    it is raised again as app.db.IntegrityError, which is what the rules catch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, TypeVar

from .db import IntegrityError, apply_migrations

try:
    from pyodide.ffi import create_proxy
except ImportError:  # the tests drive this module with a stand-in storage
    create_proxy = None

T = TypeVar("T")

# Statements after which `lastrowid` and `rowcount` mean something.
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


class Row:
    """One result row, readable by column name and by position, like sqlite3.Row."""

    __slots__ = ("_values", "_index")

    def __init__(self, values: Sequence[Any], index: dict[str, int]) -> None:
        self._values = tuple(values)
        self._index = index

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return list(self._index)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._index, self._values))!r})"


class Cursor:
    """What `execute` returns: the rows, already read, and what the write did."""

    def __init__(self, rows: list[Row], *, lastrowid: int | None, rowcount: int) -> None:
        self._rows = rows
        self._next = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> Row | None:
        if self._next >= len(self._rows):
            return None
        row = self._rows[self._next]
        self._next += 1
        return row

    def fetchall(self) -> list[Row]:
        rows, self._next = self._rows[self._next:], len(self._rows)
        return rows

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Connection:
    """sqlite3.Connection's `execute` and `executemany`, over `sql.exec`."""

    def __init__(self, sql) -> None:
        self._sql = sql

    def _exec(self, query: str, params: Sequence[Any]):
        try:
            return self._sql.exec(query, *params)
        except Exception as exc:
            if "SQLITE_CONSTRAINT" in str(exc):
                raise IntegrityError(str(exc)) from exc
            raise

    def execute(self, query: str, params: Sequence[Any] = ()) -> Cursor:
        cursor = self._exec(query, params)
        columns = list(cursor.columnNames)
        index = {name: i for i, name in enumerate(columns)}
        rows = [Row(values, index) for values in cursor.raw().toArray()]
        lastrowid, rowcount = None, -1
        if query.lstrip()[:7].upper().startswith(_WRITES):
            after = self._exec("SELECT last_insert_rowid(), changes()", ()).raw().toArray()[0]
            lastrowid, rowcount = int(after[0]), int(after[1])
        return Cursor(rows, lastrowid=lastrowid, rowcount=rowcount)

    def executemany(self, query: str, seq_of_params: Iterable[Sequence[Any]]) -> Cursor:
        total, last = 0, None
        for params in seq_of_params:
            cursor = self.execute(query, params)
            total += max(cursor.rowcount, 0)
            last = cursor.lastrowid
        return Cursor([], lastrowid=last, rowcount=total)


class DurableDatabase:
    """`app.db.Database`, for a Durable Object. `storage` is `ctx.storage`."""

    def __init__(self, storage) -> None:
        self._storage = storage
        self._conn = Connection(storage.sql)

    def read(self) -> Connection:
        return self._conn

    def transact(self, fn: Callable[[Connection], T]) -> T:
        """Run `fn(conn)` inside one transaction and return what it returns.

        Whatever `fn` raises rolls the transaction back and is raised again.
        The result is kept on this side rather than passed back through
        JavaScript, so it arrives as the Python object `fn` returned.
        """
        result: list[T] = []

        def run() -> None:
            result.append(fn(self._conn))

        callback = create_proxy(run) if create_proxy is not None else run
        try:
            self._storage.transactionSync(callback)
        finally:
            if create_proxy is not None:
                callback.destroy()
        return result[0]

    def migrate(self) -> int:
        """Apply any migrations the object's database has not seen."""
        return apply_migrations(self)

    def close(self) -> None:
        """Nothing to close: the storage belongs to the object."""
