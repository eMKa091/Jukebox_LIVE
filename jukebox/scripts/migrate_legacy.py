#!/usr/bin/env python3
"""Load the legacy Streamlit database into the new schema.

Usage:
    python scripts/migrate_legacy.py OLD.db NEW.db [--force]

Reads ../jukeboxHeroes-v2/backups/backup-votes.db -- the SQLite blob the old
app committed to GitHub -- and writes a fresh Jukebox LIVE database.

Idempotent: running it twice against the same pair of files produces the same
result, because it always starts from an empty target unless --force is given.

The mapping decisions, all of them recorded in docs/06-migration-plan.md:

  legacy                              new
  ---------------------------------   ------------------------------------
  votes.user_id (free text)           one voter row per DISTINCT RAW STRING
                                      per event. 'Martin' and 'Martin ' stay
                                      two voters -- see the note below
  votes.round_id (a round *number*)   rounds.id of that event's round 1
  votes.song (TEXT holding an int)    votes.song_id (INTEGER FK)
  events.date 'DD.MM.YYYY'            starts_at, at 20:00 Europe/Prague, in UTC
  event_songs.round_id = NULL         round_songs on the synthesised round 1
  events.round_status='completed'     events.state='closed'
  played_songs (0 rows)               dropped
  admin_settings (0 rows)             dropped
  admin_users (unsalted sha256)       NOT migrated -- see the note at the end

Every legacy event in the real data is single-round, so exactly one round is
synthesised per event. Multi-round events would need a decision about which
round each vote belonged to, and the legacy data does not record it.

On not merging names
--------------------
An earlier version of this script treated 'Martin' and 'Martin ' inside one
event as the same person, on the grounds that they probably were. That is a
guess about who someone was, applied to data that cannot confirm it -- and it
is destructive, because two merged voters who both picked the same song collide
on UNIQUE (round_id, voter_id, song_id) and one vote silently disappears.
Against a production-scale database that cost 1,199 of 16,350 votes and moved
1,093 song tallies.

The rule now is: historical data is reproduced, not improved. Each distinct raw
string becomes its own voter, so every tally the band saw is the tally they
still see. Names that differ only by whitespace or case are reported at the end
as `ambiguous_names` so the operator knows they exist.

Real voter identity -- one ballot per device -- starts with the first event run
on the new system, where there is an actual device token to key on. It cannot
be back-dated onto data that never had one.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Database, utcnow  # noqa: E402
from app.domain.events import slugify  # noqa: E402

BAND_TZ = ZoneInfo("Europe/Prague")
DEFAULT_START = time(20, 0)
DEFAULT_MAX_VOTES = 5  # what every live event actually ran on: no rounds row
                       # existed, so voting.py fell back to its hardcoded 5.


def parse_legacy_date(raw: str) -> str:
    """'29.11.2025' -> ISO-8601 UTC at 20:00 local.

    The legacy schema stored no time at all. 20:00 Europe/Prague is a stated
    assumption, not a recovery -- it is recorded here and in the plan so nobody
    later mistakes it for data.
    """
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            day = datetime.strptime(raw.strip(), fmt).date()
            break
        except ValueError:
            continue
    else:
        day = datetime.now(BAND_TZ).date()
    local = datetime.combine(day, DEFAULT_START, tzinfo=BAND_TZ)
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def migrate(old_path: Path, new_path: Path, *, force: bool) -> dict:
    if not old_path.exists():
        raise SystemExit(f"Legacy database not found: {old_path}")
    if new_path.exists() and not force:
        raise SystemExit(f"{new_path} already exists. Pass --force to replace it.")
    if new_path.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(new_path) + suffix).unlink(missing_ok=True)

    old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row

    db = Database(new_path)
    db.migrate()

    counts: dict[str, int] = defaultdict(int)
    song_map: dict[int, int] = {}      # legacy songs.id -> new songs.id
    round_map: dict[int, int] = {}     # legacy event id  -> new round id
    event_map: dict[int, int] = {}

    with db.write() as conn:
        # -- songs -------------------------------------------------------
        for row in old.execute("SELECT id, title, artist FROM songs ORDER BY id"):
            title = (row["title"] or "").strip()
            artist = (row["artist"] or "").strip()
            if not title or not artist:
                counts["songs_skipped"] += 1
                continue
            existing = conn.execute(
                "SELECT id FROM songs WHERE lower(artist)=lower(?) AND lower(title)=lower(?)",
                (artist, title),
            ).fetchone()
            if existing:
                song_map[row["id"]] = existing["id"]
                counts["songs_merged"] += 1
                continue
            cur = conn.execute("INSERT INTO songs (title, artist) VALUES (?, ?)", (title, artist))
            song_map[row["id"]] = int(cur.lastrowid)
            counts["songs"] += 1

        # -- events, each with one synthesised round ---------------------
        slugs: set[str] = set()
        for row in old.execute("SELECT * FROM events ORDER BY id"):
            base = slugify(row["name"] or f"event-{row['id']}")
            slug, n = base, 2
            while slug in slugs:
                slug, n = f"{base}-{n}", n + 1
            slugs.add(slug)

            cur = conn.execute(
                "INSERT INTO events (name, slug, venue, starts_at, state, created_at)"
                " VALUES (?, ?, '', ?, 'closed', ?)",
                (row["name"], slug, parse_legacy_date(row["date"] or ""), utcnow()),
            )
            event_id = int(cur.lastrowid)
            event_map[row["id"]] = event_id
            counts["events"] += 1

            max_votes = DEFAULT_MAX_VOTES
            legacy_round = old.execute(
                "SELECT max_votes FROM rounds WHERE event_id = ? ORDER BY round_number LIMIT 1",
                (row["id"],),
            ).fetchone()
            if legacy_round and legacy_round["max_votes"]:
                max_votes = int(legacy_round["max_votes"])

            cur = conn.execute(
                "INSERT INTO rounds (event_id, ordinal, state, max_votes, opened_at, closed_at)"
                " VALUES (?, 1, 'closed', ?, ?, ?)",
                (event_id, max_votes, utcnow(), utcnow()),
            )
            round_map[row["id"]] = int(cur.lastrowid)

            conn.execute(
                "INSERT INTO band_notes (event_id, body, updated_at) VALUES (?, '', ?)",
                (event_id, utcnow()),
            )

        # -- round_songs -------------------------------------------------
        for row in old.execute("SELECT event_id, song_id, played, removed FROM event_songs"):
            round_id = round_map.get(row["event_id"])
            song_id = song_map.get(row["song_id"])
            if round_id is None or song_id is None:
                counts["round_songs_orphaned"] += 1
                continue
            conn.execute(
                "INSERT INTO round_songs (round_id, song_id, excluded, played_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (round_id, song_id) DO NOTHING",
                (round_id, song_id, 1 if row["removed"] else 0, utcnow() if row["played"] else None),
            )
            counts["round_songs"] += 1

        # -- voters, reconstructed from the free-text names ---------------
        # The legacy schema has no voter table: a voter is whatever string
        # someone typed. One row per distinct raw string, so the tallies are
        # reproduced exactly. See "On not merging names" above.
        voter_map: dict[tuple[int, str], str] = {}
        seen_normalised: dict[tuple[int, str], str] = {}
        for row in old.execute(
            "SELECT DISTINCT event_id, user_id FROM votes ORDER BY event_id, user_id"
        ):
            event_id = event_map.get(row["event_id"])
            raw = row["user_id"] or ""
            if event_id is None or not raw.strip():
                continue

            key = (row["event_id"], raw)
            if key in voter_map:
                continue

            # Flag, but do not act on, names that differ only in whitespace or
            # case. The operator can see them; the migration does not decide.
            normalised = (row["event_id"], raw.strip().lower())
            if normalised in seen_normalised:
                counts["ambiguous_names"] += 1
            else:
                seen_normalised[normalised] = raw

            voter_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO voters (id, event_id, display_name, device_token, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                # No device ever existed for these people. A synthetic token
                # keeps UNIQUE (event_id, device_token) honest without
                # pretending the identity is real.
                (voter_id, event_id, raw.strip(), f"legacy:{uuid.uuid4().hex}", utcnow()),
            )
            voter_map[key] = voter_id
            counts["voters"] += 1

        # -- votes --------------------------------------------------------
        # votes.song is TEXT holding an integer. The legacy results screen only
        # worked because SQLite coerces across the join; here the cast is
        # explicit and anything that fails to convert is reported, not silently
        # dropped (F14).
        for row in old.execute("SELECT * FROM votes ORDER BY id"):
            round_id = round_map.get(row["event_id"])
            voter_id = voter_map.get((row["event_id"], row["user_id"] or ""))
            try:
                legacy_song_id = int(str(row["song"]).strip())
            except (TypeError, ValueError):
                counts["votes_unparseable"] += 1
                continue
            song_id = song_map.get(legacy_song_id)
            if round_id is None or voter_id is None or song_id is None:
                counts["votes_orphaned"] += 1
                continue
            conn.execute(
                "INSERT INTO votes (round_id, voter_id, song_id, ballot_id, cast_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (round_id, voter_id, song_id) DO NOTHING",
                (round_id, voter_id, song_id, f"legacy-{row['id']}", f"{row['date']}T20:00:00.000Z"),
            )
            counts["votes"] += 1

        # -- band page content -------------------------------------------
        content = old.execute(
            "SELECT content FROM band_page_content ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if content and content["content"]:
            for event_id in event_map.values():
                conn.execute(
                    "UPDATE band_notes SET body = ? WHERE event_id = ?",
                    (content["content"], event_id),
                )
                counts["band_notes"] += 1

        conn.execute(
            "INSERT INTO event_log (at, actor, action, payload)"
            " VALUES (?, 'system', 'legacy.migrated', ?)",
            (utcnow(), f'{{"source": "{old_path.name}"}}'),
        )

    old.close()
    db.close()
    return dict(counts)


def verify(old_path: Path, new_path: Path) -> list[str]:
    """Gate G2. Returns a list of failures; empty means the migration passed."""
    old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    new = sqlite3.connect(f"file:{new_path}?mode=ro", uri=True)
    problems: list[str] = []

    def one(conn, sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    # 1. Every event survived.
    old_events = one(old, "SELECT COUNT(*) FROM events")
    new_events = one(new, "SELECT COUNT(*) FROM events")
    if old_events != new_events:
        problems.append(f"events: {old_events} -> {new_events}")

    # 2. Every vote that pointed at a real song survived.
    #
    # Counted DISTINCT over (voter, song, event, round). The legacy app's
    # submit_votes() refused to write the same tuple twice, and the production
    # blob indeed holds none -- but a blob written by an older build, or edited
    # by hand, could. Such rows are duplicates of each other, not distinct
    # votes, and collapsing them is correct; counting raw rows would report
    # that correct behaviour as data loss.
    resolvable = (
        "FROM votes v JOIN songs s ON CAST(v.song AS INTEGER) = s.id"
        " WHERE v.event_id IN (SELECT id FROM events)"
        "   AND trim(COALESCE(v.user_id,'')) <> ''"
    )
    old_rows = one(old, f"SELECT COUNT(*) {resolvable}")
    old_votes = one(
        old,
        f"SELECT COUNT(*) FROM (SELECT DISTINCT v.user_id, v.song, v.event_id, v.round_id {resolvable})",
    )
    new_votes = one(new, "SELECT COUNT(*) FROM votes")
    if old_rows != old_votes:
        problems.append(
            f"NOTE {old_rows - old_votes} duplicate row(s) in the legacy votes table"
            " were collapsed; the legacy app should not have been able to write them"
        )
    if old_votes != new_votes:
        problems.append(f"votes: {old_votes} distinct -> {new_votes} migrated")

    # 3. Zero orphans: every vote joins to a song and a voter.
    orphans = one(
        new,
        "SELECT COUNT(*) FROM votes v LEFT JOIN songs s ON s.id = v.song_id"
        " LEFT JOIN voters vo ON vo.id = v.voter_id"
        " WHERE s.id IS NULL OR vo.id IS NULL",
    )
    if orphans:
        problems.append(f"{orphans} orphaned vote(s)")

    # 4. Per-event tallies are identical to what the legacy results screen
    #    produced. This is the check that actually matters: the numbers the
    #    band saw must be the numbers they still see.
    old_tally = {
        (r[0], r[1], r[2]): r[3]
        for r in old.execute(
            "SELECT e.name, s.artist, s.title, COUNT(DISTINCT v.user_id) FROM votes v"
            " JOIN events e ON e.id = v.event_id"
            " JOIN songs s ON CAST(v.song AS INTEGER) = s.id"
            " WHERE trim(COALESCE(v.user_id,'')) <> ''"
            " GROUP BY e.name, s.artist, s.title"
        )
    }
    new_tally = {
        (r[0], r[1], r[2]): r[3]
        for r in new.execute(
            "SELECT e.name, s.artist, s.title, COUNT(v.id) FROM votes v"
            " JOIN rounds rd ON rd.id = v.round_id"
            " JOIN events e ON e.id = rd.event_id"
            " JOIN songs s ON s.id = v.song_id"
            " GROUP BY e.name, s.artist, s.title"
        )
    }
    if old_tally != new_tally:
        only_old = set(old_tally) - set(new_tally)
        only_new = set(new_tally) - set(old_tally)
        differing = {k for k in set(old_tally) & set(new_tally) if old_tally[k] != new_tally[k]}
        problems.append(
            f"tallies differ: {len(only_old)} lost, {len(only_new)} new, {len(differing)} changed"
        )

    old.close()
    new.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", type=Path, help="legacy backup-votes.db")
    parser.add_argument("new", type=Path, help="destination jukebox.db")
    parser.add_argument("--force", action="store_true", help="replace the destination if it exists")
    args = parser.parse_args()

    counts = migrate(args.old, args.new, force=args.force)
    print(f"Migrated {args.old} -> {args.new}\n")
    for key in sorted(counts):
        print(f"  {key:24} {counts[key]}")

    problems = verify(args.old, args.new)
    notes = [p for p in problems if p.startswith("NOTE ")]
    failures = [p for p in problems if not p.startswith("NOTE ")]

    print()
    for note in notes:
        print(f"  note: {note[5:]}")
    if notes:
        print()
    if failures:
        print("GATE G2 FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("GATE G2 PASSED: events, votes and per-song tallies all match.")
    print()
    if counts.get("ambiguous_names"):
        print(f"Note: {counts['ambiguous_names']} voter name(s) differ from another")
        print("only by whitespace or capitalisation. They were kept separate, because")
        print("merging them would change tallies the band has already seen. Nothing")
        print("to do unless you want them merged by hand.")
        print()
    print("Admin accounts were NOT migrated. The legacy hashes are unsalted")
    print("SHA-256 from a database file that sat in a public GitHub repository,")
    print("so they are treated as compromised. Create accounts with:")
    print("    python -m app.cli create-admin <username>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
