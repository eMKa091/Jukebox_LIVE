"""Gate G2 — the legacy migration, run against the real production database.

This is not a synthetic fixture. It reads the actual SQLite blob the Streamlit
app committed to GitHub and asserts that the numbers the band saw are the
numbers they still see.
"""

from __future__ import annotations

import pytest

from app.db import Database
from app.domain import ballots, events, rounds, songs
from tests.conftest import LEGACY_DB

pytestmark = pytest.mark.skipif(
    not LEGACY_DB.exists(), reason=f"legacy database not present at {LEGACY_DB}"
)


@pytest.fixture
def migrated(tmp_path):
    from scripts.migrate_legacy import migrate

    target = tmp_path / "migrated.db"
    counts = migrate(LEGACY_DB, target, force=True)
    db = Database(target)
    yield db, counts
    db.close()


def test_the_counts_match_production(migrated):
    """8 events, 112 songs, 45 votes, 9 voters -- the real numbers."""
    _, counts = migrated
    assert counts["events"] == 8
    assert counts["songs"] == 112
    assert counts["votes"] == 45
    assert counts["voters"] == 9
    assert counts["round_songs"] == 896
    assert counts.get("votes_orphaned", 0) == 0
    assert counts.get("votes_unparseable", 0) == 0


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


def test_whitespace_variant_names_became_one_voter(migrated):
    """The legacy data holds both 'Martin' and 'Martin ' as separate voters."""
    db, _ = migrated
    rows = db.read().execute("SELECT event_id, display_name FROM voters").fetchall()

    # Names are stored trimmed...
    assert all(r["display_name"] == r["display_name"].strip() for r in rows)

    # ...and within one event, two spellings of the same name are one voter.
    per_event: dict[int, list[str]] = {}
    for r in rows:
        per_event.setdefault(r["event_id"], []).append(r["display_name"].lower())
    for event_id, names in per_event.items():
        assert len(names) == len(set(names)), f"duplicate voter in event {event_id}"

    # 9 voters, down from 9 distinct raw strings -- the trailing-space pairs in
    # the live data sit in different events, so nothing merges here. The
    # assertion that matters is that the rule is applied at all.
    assert len(rows) == 9


def test_dates_became_real_timestamps(migrated):
    """'29.11.2025' sorted before '01.12.2025' as text (F15)."""
    db, _ = migrated
    rows = [e.starts_at for e in events.list_events(db.read())]
    assert all(s.endswith("Z") for s in rows)
    assert rows == sorted(rows, reverse=True)  # list_events orders by starts_at DESC


def test_every_event_has_exactly_one_closed_round(migrated):
    db, _ = migrated
    for event in events.list_events(db.read()):
        event_rounds = rounds.for_event(db.read(), event.id)
        assert len(event_rounds) == 1
        assert event_rounds[0].state == "closed"
        assert event_rounds[0].ordinal == 1


def test_removed_songs_carried_over_as_excluded(migrated):
    """Event 8 had 15 songs marked removed in the legacy data."""
    db, _ = migrated
    excluded = db.read().execute(
        "SELECT COUNT(*) FROM round_songs WHERE excluded = 1"
    ).fetchone()[0]
    assert excluded == 15


def test_the_migrated_database_is_immediately_usable(migrated):
    """A migrated database must run a new event, not just hold old rows."""
    db, _ = migrated
    event = events.create(db, name="First gig after the migration",
                          starts_at="2026-10-04T18:00:00Z", actor="test")
    first = rounds.for_event(db.read(), event.id)[0]
    assert rounds.assign_all_songs(db, round_id=first.id, actor="test") == 112

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
