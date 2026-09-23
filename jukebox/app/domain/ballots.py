"""Casting votes, and counting them.

Two properties matter here and neither existed before:

* **Submitting is idempotent.** The client generates a ballot id once and sends
  it with every retry. On bad venue wifi an attendee will tap submit twice; the
  second tap must be a no-op, not a second ballot. The legacy app told them
  "thank you" either way and their vote may or may not have landed.

* **The round's state is read inside the same transaction that writes the
  votes.** A round that closes between the page rendering and the submit
  arriving rejects the ballot cleanly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..db import Database, utcnow
from . import rounds
from .errors import Conflict, Invalid, NotFound


@dataclass(frozen=True)
class Receipt:
    """What the attendee is shown after voting."""

    accepted: int
    replay: bool           # True when this was a retry of an already-counted ballot
    songs: list[str]


def voter_for_device(
    db: Database, *, event_id: int, device_token: str, display_name: str
) -> str:
    """Find or create this device's voter record for this event.

    Identity is the httpOnly cookie, not the typed name. The name is a label on
    the ballot so the band can read the room; it is not how anyone is counted.
    Re-entering with a different name updates the label and keeps the identity,
    which is what stops a refresh from buying a second ballot (F6).
    """
    display_name = display_name.strip()
    if not display_name:
        raise Invalid("Zadej prosím své jméno.")
    if len(display_name) > 40:
        display_name = display_name[:40]

    with db.write() as conn:
        row = conn.execute(
            "SELECT id FROM voters WHERE event_id = ? AND device_token = ?",
            (event_id, device_token),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE voters SET display_name = ? WHERE id = ?",
                (display_name, row["id"]),
            )
            return row["id"]
        import uuid

        voter_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO voters (id, event_id, display_name, device_token, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (voter_id, event_id, display_name, device_token, utcnow()),
        )
        return voter_id


def voter_in_event(conn: sqlite3.Connection, *, event_id: int, device_token: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, display_name FROM voters WHERE event_id = ? AND device_token = ?",
        (event_id, device_token),
    ).fetchone()


def submitted_songs(conn: sqlite3.Connection, *, round_id: int, voter_id: str) -> list[int]:
    """Which songs this voter has already had counted in this round.

    Read from the database, not from a session variable. This is the fact that
    survives a refresh, a new tab, and a dropped websocket.
    """
    return [
        r["song_id"]
        for r in conn.execute(
            "SELECT song_id FROM votes WHERE round_id = ? AND voter_id = ?",
            (round_id, voter_id),
        )
    ]


def submit(
    db: Database,
    *,
    round_id: int,
    voter_id: str,
    song_ids: list[int],
    ballot_id: str,
) -> Receipt:
    """Record a ballot. Safe to call twice with the same ballot_id."""
    song_ids = list(dict.fromkeys(song_ids))  # de-dup, keep order
    if not song_ids:
        raise Invalid("Vyber prosím alespoň jednu píseň.")
    if not ballot_id:
        raise Invalid("Missing ballot id.")

    with db.write() as conn:
        rnd = rounds.get(conn, round_id)

        existing = conn.execute(
            "SELECT song_id, ballot_id FROM votes WHERE round_id = ? AND voter_id = ?",
            (round_id, voter_id),
        ).fetchall()
        if existing:
            if existing[0]["ballot_id"] == ballot_id:
                # The same ballot arriving again: a retry. Report what was
                # already counted rather than erroring.
                counted = titles(conn, [r["song_id"] for r in existing])
                return Receipt(accepted=len(existing), replay=True, songs=counted)
            raise Conflict("V tomto kole jsi už hlasoval/a. Děkujeme!")

        # State is checked here, inside the transaction, not when the page was
        # rendered.
        if rnd.state != "open":
            raise Conflict("Hlasování v tomto kole už je uzavřeno.")
        if len(song_ids) > rnd.max_votes:
            raise Invalid(f"Můžeš vybrat nejvýše {rnd.max_votes} písní.")

        votable = {r["id"] for r in rounds.votable_songs(conn, round_id)}
        unknown = [s for s in song_ids if s not in votable]
        if unknown:
            raise Invalid("Některé z vybraných písní už nejsou k dispozici.")

        now = utcnow()
        conn.executemany(
            "INSERT INTO votes (round_id, voter_id, song_id, ballot_id, cast_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (round_id, voter_id, song_id) DO NOTHING",
            [(round_id, voter_id, song_id, ballot_id, now) for song_id in song_ids],
        )
        return Receipt(accepted=len(song_ids), replay=False, songs=titles(conn, song_ids))


def titles(conn: sqlite3.Connection, song_ids: list[int]) -> list[str]:
    """Human-readable labels for a set of song ids, artist-sorted."""
    if not song_ids:
        return []
    placeholders = ",".join("?" * len(song_ids))
    rows = conn.execute(
        f"SELECT title, artist FROM songs WHERE id IN ({placeholders})"
        " ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE",
        song_ids,
    ).fetchall()
    return [f"{r['title']} — {r['artist']}" for r in rows]


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------

def tally(conn: sqlite3.Connection, round_id: int) -> list[dict]:
    """Ranked results for one round.

    Only songs still available are ranked; a song the band has already played
    drops out rather than sitting at the top of the list with nowhere to go.
    Ties keep the same rank, so two songs on nine votes are both rank 1.
    """
    rows = conn.execute(
        "SELECT s.id, s.title, s.artist, COUNT(v.id) AS votes"
        " FROM round_songs rs"
        " JOIN songs s ON s.id = rs.song_id"
        " LEFT JOIN votes v ON v.song_id = s.id AND v.round_id = rs.round_id"
        " WHERE rs.round_id = ? AND rs.excluded = 0 AND rs.played_at IS NULL"
        " GROUP BY s.id, s.title, s.artist"
        " ORDER BY votes DESC, s.artist COLLATE NOCASE, s.title COLLATE NOCASE",
        (round_id,),
    ).fetchall()

    out: list[dict] = []
    rank, previous_votes = 0, None
    for position, r in enumerate(rows, start=1):
        if r["votes"] != previous_votes:
            rank, previous_votes = position, r["votes"]
        out.append(
            {
                "rank": rank,
                "id": r["id"],
                "title": r["title"],
                "artist": r["artist"],
                "votes": r["votes"],
            }
        )
    return out


def event_tally(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    """Votes across every round of an event, summed per song."""
    rows = conn.execute(
        "SELECT s.id, s.title, s.artist, COUNT(v.id) AS votes"
        " FROM votes v"
        " JOIN rounds r ON r.id = v.round_id"
        " JOIN songs s ON s.id = v.song_id"
        " WHERE r.event_id = ?"
        " GROUP BY s.id, s.title, s.artist"
        " ORDER BY votes DESC, s.artist COLLATE NOCASE, s.title COLLATE NOCASE",
        (event_id,),
    ).fetchall()
    return [
        {"id": r["id"], "title": r["title"], "artist": r["artist"], "votes": r["votes"]}
        for r in rows
    ]


def round_stats(conn: sqlite3.Connection, round_id: int) -> dict:
    r = conn.execute(
        "SELECT COUNT(*) AS votes, COUNT(DISTINCT voter_id) AS voters"
        " FROM votes WHERE round_id = ?",
        (round_id,),
    ).fetchone()
    return {"votes": r["votes"], "voters": r["voters"]}


def event_stats(conn: sqlite3.Connection, event_id: int) -> dict:
    r = conn.execute(
        "SELECT COUNT(v.id) AS votes, COUNT(DISTINCT v.voter_id) AS voters"
        " FROM votes v JOIN rounds r ON r.id = v.round_id WHERE r.event_id = ?",
        (event_id,),
    ).fetchone()
    return {"votes": r["votes"], "voters": r["voters"]}
