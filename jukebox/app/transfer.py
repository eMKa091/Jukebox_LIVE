"""The band's data in and out as one JSON document.

On the Worker there is no database file to copy and no shell to run the CLI
in (docs/08-cloudflare-port.md, step 7). This is how the legacy data gets into
the Durable Object, and how a copy of what is in it gets out: to keep, to
restore from, and to run gate G2 on after an import (scripts/transfer.py).

What travels is every row of every table below, every column, ids included,
so the foreign keys still line up. What does not: admin accounts, which are
made on each app and never carried (the legacy ones are compromised, see
scripts/migrate_legacy.py), the sign-in throttle, and the record of
migrations, which each database keeps for itself.
"""

from __future__ import annotations

import re
from typing import Any

from .db import Database
from .domain import log
from .domain.errors import Conflict, Invalid

FORMAT = "jukebox-live/1"

# In the order they can be filled: everything a row points at comes first.
TABLES = ("songs", "events", "rounds", "round_songs", "voters", "votes", "band_notes", "event_log")

_IDENTIFIER = re.compile(r"^[a-z_]+$")


def dump(conn) -> dict[str, Any]:
    """Everything in TABLES, as {"format", "tables": {name: {columns, rows}}}."""
    tables: dict[str, dict] = {}
    for table in TABLES:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        tables[table] = {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": [list(r) for r in rows],
        }
    return {"format": FORMAT, "tables": tables}


def load(db: Database, data: dict[str, Any], *, actor: str) -> dict[str, int]:
    """Fill an empty app from `dump`'s output, in one transaction.

    Refused if the app already holds songs or events: an import is for a new
    app, never a merge into one that is running. The audit log is the one
    table whose rows get new ids, because the app's own first rows (the
    account made at setup) are already there; its stamps stay in order.
    """
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise Invalid(f"That is not a Jukebox LIVE export ({FORMAT}).")
    tables = data.get("tables") or {}
    unknown = sorted(set(tables) - set(TABLES))
    if unknown:
        raise Invalid(f"Unknown table(s) in the export: {', '.join(unknown)}.")
    for table, block in tables.items():
        if not all(_IDENTIFIER.match(c) for c in block.get("columns", [])):
            raise Invalid(f"The export's columns for {table} are not column names.")

    def work(conn) -> dict[str, int]:
        for table in ("songs", "events"):
            if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                raise Conflict("This app already holds data. An import goes into an empty app only.")
        counts: dict[str, int] = {}
        for table in TABLES:
            block = tables.get(table) or {}
            columns, rows = list(block.get("columns", [])), block.get("rows", [])
            if table == "event_log" and "id" in columns:
                keep = [i for i, c in enumerate(columns) if c != "id"]
                columns = [columns[i] for i in keep]
                rows = [[row[i] for i in keep] for row in rows]
            if rows:
                conn.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)})"
                    f" VALUES ({', '.join('?' * len(columns))})",
                    rows,
                )
            counts[table] = len(rows)
        log.record(conn, actor=actor, action="data.imported", **counts)
        return counts

    return db.transact(work)
