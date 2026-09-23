"""Round lifecycle and the per-round song list.

    pending ──► open ──► closed

A round owns its own song list (`round_songs`). Carrying songs forward to the
next round is an explicit action, not a side effect of a screen the admin
happened to visit -- which is how the legacy `current_round` counter advanced.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..db import Database, utcnow
from . import log
from .errors import Conflict, Invalid, NotFound

STATES = ("pending", "open", "closed")

ALLOWED: dict[str, set[str]] = {
    "pending": {"open"},
    "open": {"closed"},
    "closed": {"open"},  # reopening a round is allowed, and logged
}


@dataclass(frozen=True)
class Round:
    id: int
    event_id: int
    ordinal: int
    state: str
    max_votes: int
    opened_at: str | None
    closed_at: str | None

    @property
    def is_open(self) -> bool:
        return self.state == "open"


def _row(r: sqlite3.Row) -> Round:
    return Round(
        id=r["id"],
        event_id=r["event_id"],
        ordinal=r["ordinal"],
        state=r["state"],
        max_votes=r["max_votes"],
        opened_at=r["opened_at"],
        closed_at=r["closed_at"],
    )


def get(conn: sqlite3.Connection, round_id: int) -> Round:
    r = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    if r is None:
        raise NotFound(f"Round {round_id} does not exist.")
    return _row(r)


def for_event(conn: sqlite3.Connection, event_id: int) -> list[Round]:
    return [
        _row(r)
        for r in conn.execute(
            "SELECT * FROM rounds WHERE event_id = ? ORDER BY ordinal", (event_id,)
        )
    ]


def open_round_of(conn: sqlite3.Connection, event_id: int) -> Round | None:
    """The round currently accepting votes, if any.

    At most one exists -- the database enforces it via `one_open_round`.
    """
    r = conn.execute(
        "SELECT * FROM rounds WHERE event_id = ? AND state = 'open'", (event_id,)
    ).fetchone()
    return _row(r) if r else None


def add_round(db: Database, *, event_id: int, actor: str) -> Round:
    """Append a round to an event, carrying forward the unplayed songs."""
    with db.write() as conn:
        rows = conn.execute(
            "SELECT ordinal, id FROM rounds WHERE event_id = ? ORDER BY ordinal DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if rows is None:
            raise NotFound(f"Event {event_id} does not exist, or has no rounds.")
        if rows["ordinal"] >= 10:
            raise Invalid("An event has at most 10 rounds.")
        previous_id, ordinal = rows["id"], rows["ordinal"] + 1
        max_votes = conn.execute(
            "SELECT max_votes FROM rounds WHERE id = ?", (previous_id,)
        ).fetchone()["max_votes"]
        cur = conn.execute(
            "INSERT INTO rounds (event_id, ordinal, state, max_votes)"
            " VALUES (?, ?, 'pending', ?)",
            (event_id, ordinal, max_votes),
        )
        round_id = int(cur.lastrowid)
        _carry_forward(conn, from_round=previous_id, to_round=round_id)
        log.record(
            conn, actor=actor, action="round.added", event_id=event_id, ordinal=ordinal
        )
        return get(conn, round_id)


def set_max_votes(db: Database, *, round_id: int, max_votes: int, actor: str) -> Round:
    if not 1 <= max_votes <= 50:
        raise Invalid("Votes per round must be between 1 and 50.")
    with db.write() as conn:
        rnd = get(conn, round_id)
        if rnd.state == "open":
            # Changing the limit mid-round would mean some ballots were cast
            # under one rule and some under another.
            raise Conflict("Close the round before changing how many votes it allows.")
        conn.execute("UPDATE rounds SET max_votes = ? WHERE id = ?", (max_votes, round_id))
        log.record(
            conn,
            actor=actor,
            action="round.max_votes",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            max_votes=max_votes,
        )
        return get(conn, round_id)


def transition(db: Database, *, round_id: int, to: str, actor: str) -> Round:
    """Open or close a round.

    Two admins tapping "Open" at the same moment produce one success and one
    Conflict. The legacy equivalent produced two successes and a warning.
    """
    if to not in STATES:
        raise Invalid(f"{to!r} is not a round state.")
    with db.write() as conn:
        rnd = get(conn, round_id)
        if rnd.state == to:
            return rnd
        if to not in ALLOWED[rnd.state]:
            raise Conflict(f"A round that is {rnd.state} cannot go to {to}.")

        if to == "open":
            event = conn.execute(
                "SELECT state, name FROM events WHERE id = ?", (rnd.event_id,)
            ).fetchone()
            if event["state"] != "live":
                raise Conflict(
                    f"'{event['name']}' is {event['state']}. Put the event on air "
                    "before opening a round."
                )
            other = open_round_of(conn, rnd.event_id)
            if other is not None:
                raise Conflict(f"Round {other.ordinal} is still open. Close it first.")
            if not votable_songs(conn, round_id):
                raise Conflict("This round has no songs left to vote on.")
            try:
                conn.execute(
                    "UPDATE rounds SET state = 'open', opened_at = ?, closed_at = NULL"
                    " WHERE id = ?",
                    (utcnow(), round_id),
                )
            except sqlite3.IntegrityError as exc:
                # one_open_round fired. Reachable only if another writer
                # committed between the check above and this statement;
                # BEGIN IMMEDIATE makes that vanishingly unlikely, but the
                # index -- not the check -- is what actually guarantees it.
                raise Conflict("Another round is already open.") from exc
        else:
            conn.execute(
                "UPDATE rounds SET state = 'closed', closed_at = ? WHERE id = ?",
                (utcnow(), round_id),
            )

        log.record(
            conn,
            actor=actor,
            action=f"round.{to}",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            round_id=round_id,
        )
        return get(conn, round_id)


# --------------------------------------------------------------------------
# Song assignment
# --------------------------------------------------------------------------

def assign_all_songs(db: Database, *, round_id: int, actor: str) -> int:
    """Put every song from the master list into this round."""
    with db.write() as conn:
        rnd = get(conn, round_id)
        cur = conn.execute(
            "INSERT INTO round_songs (round_id, song_id)"
            " SELECT ?, id FROM songs WHERE retired_at IS NULL"
            " ON CONFLICT (round_id, song_id) DO NOTHING",
            (round_id,),
        )
        log.record(
            conn,
            actor=actor,
            action="round.songs_assigned",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            added=cur.rowcount,
        )
        return cur.rowcount


def set_excluded(db: Database, *, round_id: int, song_ids: list[int], excluded: bool, actor: str) -> int:
    """Take songs out of a round, or put them back.

    Exclusion is per round, so a song removed from round 1 can return in
    round 2 without touching the master list.
    """
    if not song_ids:
        return 0
    with db.write() as conn:
        rnd = get(conn, round_id)
        placeholders = ",".join("?" * len(song_ids))
        cur = conn.execute(
            f"UPDATE round_songs SET excluded = ? WHERE round_id = ?"
            f" AND song_id IN ({placeholders})",
            (1 if excluded else 0, round_id, *song_ids),
        )
        log.record(
            conn,
            actor=actor,
            action="round.excluded" if excluded else "round.included",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            songs=len(song_ids),
        )
        return cur.rowcount


def set_played(db: Database, *, round_id: int, song_ids: list[int], played: bool, actor: str) -> int:
    """Mark songs the band actually played.

    A played song does not come back in later rounds -- that is the whole
    feature. Note there is exactly one function with this name in the codebase;
    the legacy version had two with different signatures writing to different
    tables, and which one ran depended on import order (F11).
    """
    if not song_ids:
        return 0
    with db.write() as conn:
        rnd = get(conn, round_id)
        placeholders = ",".join("?" * len(song_ids))
        cur = conn.execute(
            f"UPDATE round_songs SET played_at = ? WHERE round_id = ?"
            f" AND song_id IN ({placeholders})",
            (utcnow() if played else None, round_id, *song_ids),
        )
        log.record(
            conn,
            actor=actor,
            action="round.played" if played else "round.unplayed",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            songs=len(song_ids),
        )
        return cur.rowcount


def _carry_forward(conn: sqlite3.Connection, *, from_round: int, to_round: int) -> int:
    """Copy the still-available songs from one round into the next.

    Excluded and played songs do not travel. Exclusion is per round, so this is
    the only place the decision to drop a song is allowed to propagate.
    """
    cur = conn.execute(
        "INSERT INTO round_songs (round_id, song_id)"
        " SELECT ?, rs.song_id FROM round_songs rs"
        " JOIN songs s ON s.id = rs.song_id"
        " WHERE rs.round_id = ? AND rs.excluded = 0 AND rs.played_at IS NULL"
        "   AND s.retired_at IS NULL"
        " ON CONFLICT (round_id, song_id) DO NOTHING",
        (to_round, from_round),
    )
    return cur.rowcount


def carry_forward(db: Database, *, from_round: int, actor: str) -> int:
    """Populate the next round from this one. Used from the admin console."""
    with db.write() as conn:
        rnd = get(conn, from_round)
        nxt = conn.execute(
            "SELECT id FROM rounds WHERE event_id = ? AND ordinal = ?",
            (rnd.event_id, rnd.ordinal + 1),
        ).fetchone()
        if nxt is None:
            raise Conflict(f"Round {rnd.ordinal} is the last round of this event.")
        moved = _carry_forward(conn, from_round=from_round, to_round=nxt["id"])
        log.record(
            conn,
            actor=actor,
            action="round.carried_forward",
            event_id=rnd.event_id,
            ordinal=rnd.ordinal,
            songs=moved,
        )
        return moved


def votable_songs(conn: sqlite3.Connection, round_id: int) -> list[sqlite3.Row]:
    """What the attendee ballot shows: assigned, not excluded, not yet played."""
    return conn.execute(
        "SELECT s.id, s.title, s.artist FROM round_songs rs"
        " JOIN songs s ON s.id = rs.song_id"
        " WHERE rs.round_id = ? AND rs.excluded = 0 AND rs.played_at IS NULL"
        "   AND s.retired_at IS NULL"
        " ORDER BY s.artist COLLATE NOCASE, s.title COLLATE NOCASE",
        (round_id,),
    ).fetchall()


def song_board(conn: sqlite3.Connection, round_id: int) -> list[dict]:
    """Every song in the round with its status, for the admin console."""
    rows = conn.execute(
        "SELECT s.id, s.title, s.artist, rs.excluded, rs.played_at,"
        "       (SELECT COUNT(*) FROM votes v"
        "         WHERE v.round_id = rs.round_id AND v.song_id = s.id) AS votes"
        " FROM round_songs rs JOIN songs s ON s.id = rs.song_id"
        " WHERE rs.round_id = ?"
        " ORDER BY votes DESC, s.artist COLLATE NOCASE, s.title COLLATE NOCASE",
        (round_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "artist": r["artist"],
            "excluded": bool(r["excluded"]),
            "played": r["played_at"] is not None,
            "votes": r["votes"],
            "status": "played" if r["played_at"] else ("excluded" if r["excluded"] else "open"),
        }
        for r in rows
    ]
