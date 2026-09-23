"""The append-only audit log.

Every state transition writes one row. This is the answer to the question the
legacy system cannot answer: five of its eight events hold zero votes, and
nothing recorded whether they were run at all.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import utcnow


def record(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    event_id: int | None = None,
    **payload: Any,
) -> None:
    """Append a log row. Must be called inside the transition's transaction.

    Being in the same transaction is the point: if the transition rolls back,
    so does its log row, and the log never claims something happened that did
    not.
    """
    conn.execute(
        "INSERT INTO event_log (at, actor, action, event_id, payload)"
        " VALUES (?, ?, ?, ?, ?)",
        (utcnow(), actor, action, event_id, json.dumps(payload, ensure_ascii=False)),
    )


def for_event(conn: sqlite3.Connection, event_id: int, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT at, actor, action, payload FROM event_log"
        " WHERE event_id = ? ORDER BY id DESC LIMIT ?",
        (event_id, limit),
    ).fetchall()
    return [
        {
            "at": r["at"],
            "actor": r["actor"],
            "action": r["action"],
            "payload": json.loads(r["payload"]),
        }
        for r in rows
    ]
