"""Event lifecycle.

    draft ──► ready ──► live ──► closed
                ▲          │
                └──────────┘   (an admin may take a live event back off air)

Every transition below is one function, one transaction, one audit row. That is
the whole point of this module: in the legacy code `voting_active` was written
from six different call sites, three of them inline SQL in the admin page, and
`current_round` and `voting_round` were advanced by different screens (F7).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from ..db import Database, utcnow
from . import log
from .errors import Conflict, Invalid, NotFound

STATES = ("draft", "ready", "live", "closed")

# Which transitions are legal. Anything not listed here is refused, and the
# refusal is tested.
ALLOWED: dict[str, set[str]] = {
    "draft": {"ready"},
    "ready": {"live", "draft"},
    "live": {"closed", "ready"},
    "closed": {"ready"},  # reopening is deliberate and logged
}


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    slug: str
    venue: str
    starts_at: str
    state: str

    @property
    def is_live(self) -> bool:
        return self.state == "live"


def _row(r: sqlite3.Row) -> Event:
    return Event(
        id=r["id"],
        name=r["name"],
        slug=r["slug"],
        venue=r["venue"],
        starts_at=r["starts_at"],
        state=r["state"],
    )


def slugify(name: str) -> str:
    """A short, typeable slug. It ends up in the QR code target, /e/{slug}."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug[:48] or "event"


def _unique_slug(conn: sqlite3.Connection, base: str) -> str:
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM events WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def create(
    db: Database,
    *,
    name: str,
    starts_at: str,
    venue: str = "",
    round_count: int = 1,
    max_votes: int = 5,
    actor: str,
) -> Event:
    """Create an event and its rounds together.

    Rounds are created up front and are never optional: a single-round event is
    an event with exactly one round. The legacy schema allowed
    event_songs.round_id to be NULL, which silently disabled its own PRIMARY KEY
    across all 896 rows.
    """
    name = name.strip()
    if not name:
        raise Invalid("An event needs a name.")
    if not 1 <= round_count <= 10:
        raise Invalid("An event has between 1 and 10 rounds.")
    if not 1 <= max_votes <= 50:
        raise Invalid("Votes per round must be between 1 and 50.")
    try:
        datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Invalid(f"{starts_at!r} is not a valid date and time.") from exc

    with db.write() as conn:
        slug = _unique_slug(conn, slugify(name))
        cur = conn.execute(
            "INSERT INTO events (name, slug, venue, starts_at, state, created_at)"
            " VALUES (?, ?, ?, ?, 'draft', ?)",
            (name, slug, venue.strip(), starts_at, utcnow()),
        )
        event_id = int(cur.lastrowid)
        for ordinal in range(1, round_count + 1):
            conn.execute(
                "INSERT INTO rounds (event_id, ordinal, state, max_votes)"
                " VALUES (?, ?, 'pending', ?)",
                (event_id, ordinal, max_votes),
            )
        conn.execute(
            "INSERT INTO band_notes (event_id, body, updated_at) VALUES (?, '', ?)",
            (event_id, utcnow()),
        )
        log.record(
            conn,
            actor=actor,
            action="event.created",
            event_id=event_id,
            name=name,
            rounds=round_count,
        )
        return Event(id=event_id, name=name, slug=slug, venue=venue.strip(),
                     starts_at=starts_at, state="draft")


def get(conn: sqlite3.Connection, event_id: int) -> Event:
    r = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if r is None:
        raise NotFound(f"Event {event_id} does not exist.")
    return _row(r)


def by_slug(conn: sqlite3.Connection, slug: str) -> Event:
    r = conn.execute("SELECT * FROM events WHERE slug = ?", (slug,)).fetchone()
    if r is None:
        raise NotFound("That event link is not valid.")
    return _row(r)


def live_event(conn: sqlite3.Connection) -> Event | None:
    """The one event currently on air, if any.

    The database guarantees there is at most one (index `one_live_event`), so
    this cannot silently pick the first of several the way the legacy
    `SELECT ... WHERE voting_active = 1` did.
    """
    r = conn.execute("SELECT * FROM events WHERE state = 'live'").fetchone()
    return _row(r) if r else None


def list_events(conn: sqlite3.Connection) -> list[Event]:
    return [_row(r) for r in conn.execute("SELECT * FROM events ORDER BY starts_at DESC")]


def transition(db: Database, *, event_id: int, to: str, actor: str) -> Event:
    """Move an event to a new state, or refuse and say why."""
    if to not in STATES:
        raise Invalid(f"{to!r} is not an event state.")
    with db.write() as conn:
        event = get(conn, event_id)
        if event.state == to:
            return event
        if to not in ALLOWED[event.state]:
            raise Conflict(
                f"An event that is {event.state} cannot go straight to {to}."
            )
        if to == "live":
            other = live_event(conn)
            if other is not None:
                # Refuse rather than stop the other event. The legacy code
                # stopped it silently and announced it in a warning banner that
                # vanished on the next interaction.
                raise Conflict(
                    f"'{other.name}' is already live. Close it before starting "
                    f"'{event.name}'."
                )
            if not conn.execute(
                "SELECT 1 FROM rounds WHERE event_id = ?", (event_id,)
            ).fetchone():
                raise Conflict("This event has no rounds.")
        if to in ("closed", "ready", "draft"):
            # Leaving 'live' always closes any open round, so the two state
            # machines cannot disagree about whether voting is running.
            conn.execute(
                "UPDATE rounds SET state = 'closed', closed_at = ?"
                " WHERE event_id = ? AND state = 'open'",
                (utcnow(), event_id),
            )
        try:
            conn.execute("UPDATE events SET state = ? WHERE id = ?", (to, event_id))
        except sqlite3.IntegrityError as exc:
            # one_live_event fired: another event went live concurrently.
            raise Conflict("Another event is already live.") from exc
        log.record(
            conn, actor=actor, action=f"event.{to}", event_id=event_id, was=event.state
        )
        return get(conn, event_id)


def update_band_notes(db: Database, *, event_id: int, body: str, actor: str) -> None:
    with db.write() as conn:
        get(conn, event_id)
        conn.execute(
            "INSERT INTO band_notes (event_id, body, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (event_id) DO UPDATE SET body = excluded.body,"
            " updated_at = excluded.updated_at",
            (event_id, body, utcnow()),
        )
        log.record(conn, actor=actor, action="band_notes.updated", event_id=event_id)


def band_notes(conn: sqlite3.Connection, event_id: int) -> str:
    r = conn.execute("SELECT body FROM band_notes WHERE event_id = ?", (event_id,)).fetchone()
    return r["body"] if r else ""


def delete(db: Database, *, event_id: int, actor: str) -> None:
    """Delete an event and everything hanging off it.

    Refused while live, so nobody can delete the thing two hundred people are
    currently voting in.
    """
    with db.write() as conn:
        event = get(conn, event_id)
        if event.state == "live":
            raise Conflict("Close the event before deleting it.")
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        # The log row deliberately outlives the event it describes: event_id has
        # no foreign key, precisely so deletion leaves a trace.
        log.record(
            conn, actor=actor, action="event.deleted", event_id=event_id, name=event.name
        )
