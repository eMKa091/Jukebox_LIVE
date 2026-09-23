"""Gate G2 — the legacy migration, run against a real legacy database.

This is not a synthetic fixture. It reads an actual SQLite blob from the
Streamlit app and asserts that the numbers the band saw are the numbers they
still see.

Every expectation is *derived from the source file*, never hardcoded. The copy
in this repository holds 8 events and 45 votes, but the production database has
many more of both, and a test pinned to the sample would fail on the real thing
at exactly the wrong moment. Point LEGACY_DB at any vintage of the blob and
these assertions still mean what they say.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db import Database
from app.domain import ballots, events, rounds, songs
from tests.conftest import LEGACY_DB

pytestmark = pytest.mark.skipif(
    not LEGACY_DB.exists(), reason=f"legacy database not present at {LEGACY_DB}"
)


@pytest.fixture(scope="module")
def legacy():
    """Read-only handle on the source, for deriving what to expect."""
    conn = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def migrated(tmp_path):
    from scripts.migrate_legacy import migrate

    target = tmp_path / "migrated.db"
    counts = migrate(LEGACY_DB, target, force=True)
    db = Database(target)
    yield db, counts
    db.close()


def scalar(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_nothing_is_left_behind(migrated, legacy):
    """Every row the legacy database could account for arrives in the new one."""
    _, counts = migrated

    assert counts["events"] == scalar(legacy, "SELECT COUNT(*) FROM events")

    # Songs with a usable title and artist. The legacy table has no NOT NULL
    # constraints, so blank rows are possible and are counted as skipped.
    usable_songs = scalar(
        legacy,
        "SELECT COUNT(*) FROM songs"
        " WHERE trim(COALESCE(title,'')) <> '' AND trim(COALESCE(artist,'')) <> ''",
    )
    assert counts["songs"] + counts.get("songs_merged", 0) == usable_songs

    # Votes that point at a song that exists. The legacy column is TEXT holding
    # an integer, so the cast is what makes this countable at all (F14).
    resolvable = scalar(
        legacy,
        "SELECT COUNT(*) FROM votes v JOIN songs s ON CAST(v.song AS INTEGER) = s.id",
    )
    assert counts["votes"] == resolvable

    # Distinct (event, trimmed lowercase name) pairs -- the identity rule.
    expected_voters = scalar(
        legacy,
        "SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT event_id, lower(trim(user_id)) FROM votes"
        "  WHERE trim(COALESCE(user_id,'')) <> ''"
        "    AND event_id IN (SELECT id FROM events)"
        ")",
    )
    assert counts["voters"] == expected_voters

    assert counts.get("votes_orphaned", 0) == 0
    assert counts.get("votes_unparseable", 0) == 0


def test_the_sample_in_this_repository_is_what_we_think_it_is(migrated, legacy):
    """A canary, not a specification.

    Documented figures throughout docs/ describe *this* copy of the blob. If
    someone drops in the production database, this is the one test that should
    fail -- and its failure means the docs need new numbers, not that the
    migration broke. Everything else in this file is derived.
    """
    _, counts = migrated
    if scalar(legacy, "SELECT COUNT(*) FROM events") != 8:
        pytest.skip("not the sample database shipped in this repository")
    assert (counts["events"], counts["songs"], counts["votes"], counts["voters"]) == (8, 112, 45, 9)
    assert counts["round_songs"] == 896


def test_gate_g2_verification_passes(migrated, tmp_path):
    from scripts.migrate_legacy import verify

    db, _ = migrated
    assert verify(LEGACY_DB, db.path) == []


def test_every_vote_resolves_to_a_song_and_a_voter(migrated):
    """The legacy join worked only because SQLite coerced TEXT to INTEGER (F14)."""
    db, _ = migrated
    orphans = db.read().execute(
        "SELECT COUNT(*) FROM votes v"
        " LEFT JOIN songs s ON s.id = v.song_id"
        " LEFT JOIN voters vo ON vo.id = v.voter_id"
        " WHERE s.id IS NULL OR vo.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_names_that_differ_only_by_whitespace_are_kept_apart(migrated, legacy):
    """Historical data is reproduced, not improved.

    Merging 'Martin' and 'Martin ' is a guess about who someone was, and it is
    destructive: two merged voters who picked the same song collide on
    UNIQUE (round_id, voter_id, song_id) and one vote silently disappears. At
    production scale that cost 1,199 of 16,350 votes.
    """
    db, _ = migrated
    rows = db.read().execute("SELECT event_id, display_name FROM voters").fetchall()

    # One voter per distinct raw string per event -- nothing collapsed.
    expected = scalar(
        legacy,
        "SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT event_id, user_id FROM votes"
        "  WHERE trim(COALESCE(user_id,'')) <> ''"
        "    AND event_id IN (SELECT id FROM events))",
    )
    assert len(rows) == expected

    # Names are trimmed for display only.
    assert all(r["display_name"] == r["display_name"].strip() for r in rows)


def test_dates_became_real_timestamps(migrated):
    """'29.11.2025' sorted before '01.12.2025' as text (F15)."""
    db, _ = migrated
    rows = [e.starts_at for e in events.list_events(db.read())]
    assert all(s.endswith("Z") for s in rows)
    assert rows == sorted(rows, reverse=True)  # list_events orders by starts_at DESC


def test_every_event_has_exactly_one_closed_round(migrated):
    """The legacy data records no round for any vote, so one is synthesised.

    Multi-round legacy events would need a decision about which round each vote
    belonged to, and the legacy schema never recorded it -- votes.round_id held
    a round *number* that was always 1.
    """
    db, _ = migrated
    for event in events.list_events(db.read()):
        event_rounds = rounds.for_event(db.read(), event.id)
        assert len(event_rounds) == 1
        assert event_rounds[0].state == "closed"
        assert event_rounds[0].ordinal == 1


def test_removed_songs_carried_over_as_excluded(migrated, legacy):
    """Whatever the legacy marked `removed`, the new schema marks `excluded`."""
    db, _ = migrated
    expected = scalar(
        legacy,
        "SELECT COUNT(*) FROM event_songs es"
        " WHERE es.removed = 1 AND es.event_id IN (SELECT id FROM events)"
        "   AND es.song_id IN (SELECT id FROM songs)",
    )
    assert scalar(db.read(), "SELECT COUNT(*) FROM round_songs WHERE excluded = 1") == expected


def test_the_migrated_database_is_immediately_usable(migrated):
    """A migrated database must run a new event, not just hold old rows."""
    db, _ = migrated
    catalogue = len(songs.list_songs(db.read()))
    event = events.create(db, name="First gig after the migration",
                          starts_at="2026-10-04T18:00:00Z", actor="test")
    first = rounds.for_event(db.read(), event.id)[0]
    assert rounds.assign_all_songs(db, round_id=first.id, actor="test") == catalogue

    events.transition(db, event_id=event.id, to="ready", actor="test")
    events.transition(db, event_id=event.id, to="live", actor="test")
    rounds.transition(db, round_id=first.id, to="open", actor="test")

    voter = ballots.voter_for_device(db, event_id=event.id, device_token="d1",
                                     display_name="Marek")
    picks = [r["id"] for r in rounds.votable_songs(db.read(), first.id)][:5]
    assert ballots.submit(db, round_id=first.id, voter_id=voter,
                          song_ids=picks, ballot_id="b1").accepted == 5


def test_no_admin_accounts_are_carried_over(migrated):
    """The legacy hash is unsalted SHA-256 from a public repository (F8)."""
    from app.domain import identity

    db, _ = migrated
    assert identity.admin_count(db.read()) == 0


# ---------------------------------------------------------------- at scale --
def _synthesise_legacy(path, *, events_n: int, songs_n: int, seed: int = 11) -> int:
    """Write a legacy-shaped database at production scale.

    The copy of the blob in this repository has 8 events; the real one has many
    more. Deliberately messy voter names, because the real data is -- but
    respecting the legacy app's own dedup on (user_id, song, event_id,
    round_id), which its submit_votes() enforced and which the production blob
    does satisfy.
    """
    import random

    random.seed(seed)
    source = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True)
    ddl = [
        r[0] for r in source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table'"
            " AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        )
    ]
    source.close()

    db = sqlite3.connect(path)
    for statement in ddl:
        db.execute(statement)
    db.executemany(
        "INSERT INTO songs (title, artist) VALUES (?, ?)",
        [(f"Song {i:04d}", f"Artist {i % 90:02d}") for i in range(songs_n)],
    )
    song_ids = [r[0] for r in db.execute("SELECT id FROM songs")]

    total = 0
    for e in range(events_n):
        db.execute(
            "INSERT INTO events (name, date, round_count, current_round, voting_round,"
            " voting_active, round_status, last_round) VALUES (?, ?, 1, 1, 1, 0, 'completed', 1)",
            (f"Gig {e:03d}", f"{(e % 28) + 1:02d}.{(e % 12) + 1:02d}.{2024 + e // 12}"),
        )
        event_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.executemany(
            "INSERT INTO event_songs (event_id, song_id, round_id, played, removed)"
            " VALUES (?, ?, NULL, 0, ?)",
            [(event_id, s, 1 if random.random() < 0.04 else 0) for s in song_ids],
        )
        cast: dict[str, set] = {}
        for v in range(random.randint(15, 60)):
            name = random.choice(["Martin", "Martin ", "Eva", "eva", "Paža", f"host{v}"])
            already = cast.setdefault(name, set())
            picks = [s for s in random.sample(song_ids, 5) if s not in already]
            already.update(picks)
            db.executemany(
                "INSERT INTO votes (user_id, song, event_id, round_id, date)"
                " VALUES (?, ?, ?, 1, ?)",
                [(name, str(s), event_id, "2025-06-01") for s in picks],
            )
            total += len(picks)
    db.commit()
    db.close()
    return total


def test_gate_g2_holds_at_production_scale(tmp_path):
    """60 events, 420 songs, ~15k votes, 25k assignments.

    The repository's sample is small enough to hide whole classes of problem.
    The name-merging bug this file now guards against was invisible at 8 events
    and cost 7% of the votes at 60.
    """
    from scripts.migrate_legacy import migrate, verify

    source = tmp_path / "big-legacy.db"
    written = _synthesise_legacy(source, events_n=60, songs_n=420)

    target = tmp_path / "big-new.db"
    counts = migrate(source, target, force=True)

    assert counts["events"] == 60
    assert counts["songs"] == 420
    assert counts["votes"] == written
    assert counts["round_songs"] == 60 * 420
    assert counts["ambiguous_names"] > 0, "fixture should contain messy names"

    failures = [p for p in verify(source, target) if not p.startswith("NOTE ")]
    assert failures == []


def test_legacy_duplicate_rows_are_reported_not_counted_as_loss(tmp_path):
    """A blob holding rows its own app could not have written.

    Collapsing them is correct -- they are duplicates of each other, not
    distinct votes -- so verify() must say so rather than fail.
    """
    from scripts.migrate_legacy import migrate, verify

    source = tmp_path / "dupes-legacy.db"
    _synthesise_legacy(source, events_n=3, songs_n=30)

    raw = sqlite3.connect(source)
    row = raw.execute("SELECT user_id, song, event_id, round_id, date FROM votes LIMIT 1").fetchone()
    raw.execute("INSERT INTO votes (user_id, song, event_id, round_id, date) VALUES (?,?,?,?,?)", row)
    raw.commit()
    raw.close()

    migrate(source, tmp_path / "dupes-new.db", force=True)
    problems = verify(source, tmp_path / "dupes-new.db")

    assert any(p.startswith("NOTE ") and "duplicate row" in p for p in problems)
    assert [p for p in problems if not p.startswith("NOTE ")] == []
