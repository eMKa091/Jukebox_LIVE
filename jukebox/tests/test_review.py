"""One test per finding in docs/07-review-of-the-rebuild.md.

Each test named test_r<N>_* fails if the behaviour that finding describes ever
comes back. The unnumbered ones at the end guard the smaller items of the same
review.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path

import pytest

from app.config import load_settings
from app.domain import ballots, events, log, rounds, songs
from app.domain.errors import Invalid
from app.web.hub import QUEUE_SIZE, Hub, hub, votes_topic
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER

JUKEBOX = Path(__file__).resolve().parents[1]


def _stamp_on_page(html: str) -> int:
    return int(re.search(r'data-stamp="(\d+)"', html).group(1))


# ------------------------------------------------------------------- R1 --
def test_r1_a_page_carries_the_stamp_and_a_round_change_moves_it(client, open_round, db):
    """A phone asleep while the round closes must be able to tell, on waking.

    The page says what it was rendered from; the stream says what is current.
    """
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})
    before = _stamp_on_page(client.get(f"/e/{event.slug}").text)
    assert before == log.stamp(db.read(), event.id)

    rounds.transition(db, round_id=open_round.id, to="closed", actor="t")

    assert log.stamp(db.read(), event.id) > before
    assert _stamp_on_page(client.get(f"/e/{event.slug}").text) > before


def test_r1_the_first_frame_of_a_stream_names_the_stamp():
    async def first_frame():
        stream = Hub().stream("event:1", ready={"stamp": 42})
        return await stream.__anext__()

    assert '"stamp": 42' in asyncio.run(first_frame())


def test_r1_the_client_reloads_when_the_stamps_differ():
    """The script is not run here; this pins the two lines the fix consists of."""
    script = (JUKEBOX / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "String(data.stamp) !== stamp" in script
    assert "visibilitychange" in script


def test_a_dropped_subscriber_is_disconnected_not_left_deaf():
    """A stream whose queue overflowed used to stay open and hear nothing more."""
    async def run():
        local = Hub()
        stream = local.stream("t")
        await stream.__anext__()                    # ready
        for n in range(QUEUE_SIZE + 5):
            local.publish("t", n=n)
        frames = [frame async for frame in stream]  # ends by itself
        return len(frames), local.subscriber_count("t")

    drained, still_subscribed = asyncio.run(run())
    assert drained <= QUEUE_SIZE and still_subscribed == 0


# ------------------------------------------------------------------- R2 --
def test_r2_requests_run_on_a_few_threads(client, settings):
    import anyio.to_thread

    tokens = client.portal.call(lambda: anyio.to_thread.current_default_thread_limiter().total_tokens)
    assert tokens == settings.worker_threads == 4


def test_r2_a_vote_is_announced_to_the_band_not_to_the_phones(client, open_round, db, monkeypatch):
    event = events.get(db.read(), open_round.event_id)
    told: list[str] = []
    monkeypatch.setattr(hub, "publish", lambda topic, **payload: told.append(topic))

    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})
    pick = rounds.votable_songs(db.read(), open_round.id)[0]["id"]
    client.post(f"/e/{event.slug}/ballot",
                data={"ballot_id": "a", "round_id": open_round.id, "song_ids": [pick]})

    assert told == [votes_topic(event.id)]


def test_r2_phones_spread_their_reload(client, open_round, db):
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})
    assert 'data-jitter="3000"' in client.get(f"/e/{event.slug}").text


# ------------------------------------------------------------------- R3 --
def test_r3_litestream_is_given_its_config():
    """Cannot be run here (no container). This pins the wiring that was missing:
    the config is installed where litestream looks, and nothing relies on a
    LITESTREAM_REPLICA_URL variable that litestream never read."""
    dockerfile = (JUKEBOX / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (JUKEBOX / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    config = (JUKEBOX / "deploy" / "litestream.yml").read_text(encoding="utf-8")

    assert "COPY deploy/litestream.yml /etc/litestream.yml" in dockerfile
    assert "LITESTREAM_REPLICA_URL" not in dockerfile + entrypoint + config
    assert "endpoint: ${LITESTREAM_ENDPOINT}" in config
    assert "path: ${JUKEBOX_DB}" in config


# ------------------------------------------------------------------- R4 --
def test_r4_the_connection_ceiling_fits_the_room():
    limit = int(re.search(r"hard_limit = (\d+)", (JUKEBOX / "fly.toml").read_text()).group(1))
    assert limit >= 2 * 500 + 100      # every phone twice at a round change, plus staff


# ------------------------------------------------------------------- R5 --
def test_r5_a_played_song_stays_off_a_round_that_was_filled_first(db, open_round):
    conn = db.read()
    first, second = rounds.for_event(conn, open_round.event_id)
    rounds.carry_forward(db, from_round=first.id, actor="t")        # round 2 prepared early
    song = rounds.votable_songs(conn, first.id)[0]["id"]
    rounds.transition(db, round_id=first.id, to="closed", actor="t")

    rounds.set_played(db, round_id=first.id, song_ids=[song], played=True, actor="t")

    assert song not in {r["id"] for r in rounds.votable_songs(conn, second.id)}
    assert song not in {r["id"] for r in ballots.tally(conn, second.id)}
    board = {s["id"]: s["status"] for s in rounds.song_board(conn, second.id)}
    assert board[song] == "played"


def test_r5_unmarking_from_any_round_brings_the_song_back(db, open_round):
    conn = db.read()
    first, second = rounds.for_event(conn, open_round.event_id)
    rounds.carry_forward(db, from_round=first.id, actor="t")
    song = rounds.votable_songs(conn, first.id)[0]["id"]
    rounds.set_played(db, round_id=first.id, song_ids=[song], played=True, actor="t")

    rounds.set_played(db, round_id=second.id, song_ids=[song], played=False, actor="t")

    assert song in {r["id"] for r in rounds.votable_songs(conn, second.id)}


def test_r5_a_played_song_is_not_reported_as_missing_from_the_next_round(db, open_round):
    """Otherwise "Add all" on round 2 would put the evening's played songs back."""
    conn = db.read()
    first, second = rounds.for_event(conn, open_round.event_id)
    song = rounds.votable_songs(conn, first.id)[0]["id"]
    rounds.set_played(db, round_id=first.id, song_ids=[song], played=True, actor="t")
    rounds.carry_forward(db, from_round=first.id, actor="t")

    assert song not in {r["id"] for r in rounds.songs_not_in_round(conn, second.id)}


# ------------------------------------------------------------------- R6 --
def test_r6_after_round_one_the_big_button_starts_round_two(admin_client, db, open_round):
    first, second = rounds.for_event(db.read(), open_round.event_id)
    rounds.transition(db, round_id=first.id, to="closed", actor="t")

    page = admin_client.get(f"/admin/events/{open_round.event_id}").text

    assert re.search(rf'/admin/rounds/{second.id}/state.*?<button class="btn" type="submit">Start round 2<',
                     page, re.S)
    assert "Reopen round 1" in page and "Start round 1" not in page


def test_r6_stop_is_offered_for_the_open_round_whichever_is_selected(admin_client, db, open_round):
    first, second = rounds.for_event(db.read(), open_round.event_id)
    page = admin_client.get(f"/admin/events/{open_round.event_id}?round={second.id}").text
    assert f"/admin/rounds/{first.id}/state" in page and "Stop voting" in page
    assert "Start round" not in page


# ------------------------------------------------------------------- R7 --
def test_r7_an_apostrophe_cannot_remove_the_delete_confirmation(admin_client, db, catalogue):
    event = events.create(db, name="Rock'n'Roll párty", starts_at="2026-12-01T19:00:00Z", actor="t")
    page = admin_client.get(f"/admin/events/{event.id}?tab=data").text
    assert "onsubmit" not in page
    assert 'data-confirm="Delete Rock&#39;n&#39;Roll párty and all its votes?' in page
    script = (JUKEBOX / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "dataset.confirm" in script


# ------------------------------------------------------------------- R8 --
def test_r8_nobody_joins_an_event_that_is_not_on_air(client, db, event):
    response = client.post(f"/e/{event.slug}/join", data={"display_name": "X"}, follow_redirects=False)
    assert response.status_code == 303
    assert db.read().execute("SELECT COUNT(*) FROM voters").fetchone()[0] == 0


def test_r8_a_voter_of_another_event_cannot_vote_in_this_round(db, open_round, catalogue):
    other = events.create(db, name="Jiná akce", starts_at="2025-01-01T18:00:00Z", actor="t")
    stranger = ballots.voter_for_device(db, event_id=other.id, device_token="d" * 32, display_name="K")
    pick = rounds.votable_songs(db.read(), open_round.id)[0]["id"]

    with pytest.raises(Invalid):
        ballots.submit(db, round_id=open_round.id, voter_id=stranger, song_ids=[pick], ballot_id="b")

    assert ballots.round_stats(db.read(), open_round.id) == {"votes": 0, "voters": 0}


def test_r8_one_phone_gets_one_ballot_through_any_link(client, db, open_round, catalogue):
    live = events.get(db.read(), open_round.event_id)
    other = events.create(db, name="Stará akce", starts_at="2025-01-01T18:00:00Z", actor="t")
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:5]

    client.post(f"/e/{live.slug}/join", data={"display_name": "Kuba"})
    client.post(f"/e/{live.slug}/ballot", data={"ballot_id": "a", "round_id": open_round.id, "song_ids": picks})
    client.post(f"/e/{other.slug}/join", data={"display_name": "Kuba"})
    client.post(f"/e/{other.slug}/ballot", data={"ballot_id": "b", "round_id": open_round.id, "song_ids": picks})

    assert ballots.round_stats(db.read(), open_round.id) == {"votes": 5, "voters": 1}


# ------------------------------------------------------------------- R9 --
def test_r9_wrong_passwords_from_one_place_do_not_lock_out_another(client):
    stranger = {"cf-connecting-ip": "203.0.113.9"}
    for _ in range(6):   # the fixture's limit is 4
        client.post("/admin/login", data={"username": ADMIN_USER, "password": "wrong"}, headers=stranger)

    refused = client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
                          headers=stranger, follow_redirects=False)
    band = client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
                       headers={"cf-connecting-ip": "198.51.100.7"}, follow_redirects=False)

    assert refused.headers["location"] == "/admin/login"     # the guesser is still throttled
    assert band.headers["location"] == "/admin"              # the band is not


def test_r9_only_two_password_checks_run_at_once(db, monkeypatch):
    from app.domain import identity

    for _ in range(2):
        assert identity._hashing.acquire(blocking=False)
    try:
        throttle = identity.LoginThrottle(max_attempts=8, window_seconds=900)
        with pytest.raises(identity.NotPermitted, match="busy"):
            identity.authenticate(db, username="x", password="y", throttle=throttle, client="a")
        # Being turned away for being busy is not a failed attempt.
        assert throttle._attempts == {}
    finally:
        identity._hashing.release()
        identity._hashing.release()


# ------------------------------------------------------------------ R10 --
def test_r10_no_database_is_tracked_in_the_repository():
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "*.db"], cwd=JUKEBOX.parent, capture_output=True, text=True)
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")
    # The legacy backup is the migration's input and holds no account of the new system.
    assert [f for f in tracked.stdout.split() if "jukeboxHeroes-v2" not in f and not f.startswith("backups/")] == []


# ------------------------------------------------------------------ R11 --
def test_r11_a_voter_name_cannot_become_a_spreadsheet_formula(client, admin_client, db, open_round):
    live = events.get(db.read(), open_round.event_id)
    pick = rounds.votable_songs(db.read(), open_round.id)[0]["id"]
    client.post(f"/e/{live.slug}/join", data={"display_name": '=HYPERLINK("http://x","klik")'})
    client.post(f"/e/{live.slug}/ballot", data={"ballot_id": "a", "round_id": open_round.id, "song_ids": [pick]})

    export = admin_client.get(f"/admin/events/{live.id}/export.csv").text

    assert "1;\"'=HYPERLINK(" in export


# --------------------------------------------------------- smaller items --
def test_a_failed_migration_leaves_nothing_behind_and_says_why(tmp_path, monkeypatch):
    import app.db as dbmod

    bad = tmp_path / "001_bad.sql"
    bad.write_text("CREATE TABLE a (x); CREATE TABLE b (y); THIS IS NOT SQL;")
    monkeypatch.setattr(dbmod, "MIGRATIONS", [bad])
    database = dbmod.Database(tmp_path / "x.db")

    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        database.migrate()

    conn = database.read()
    # Not even schema_migrations: it is created in the migration's transaction.
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def test_the_ranking_lists_exactly_what_the_ballot_offers(db, open_round):
    conn = db.read()
    song = rounds.votable_songs(conn, open_round.id)[0]["id"]
    songs.set_retired(db, song_id=song, retired=True, actor="t")
    assert {r["id"] for r in ballots.tally(conn, open_round.id)} == \
           {r["id"] for r in rounds.votable_songs(conn, open_round.id)}


def test_a_start_time_is_read_in_the_bands_zone_wherever_the_server_runs(admin_client, db, catalogue, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")          # what the container runs in
    time.tzset()
    try:
        admin_client.post("/admin/events", data={"name": "Ples", "starts_at": "2026-12-05T20:00"})
        page = admin_client.get("/admin").text
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()

    assert events.list_events(db.read())[0].starts_at.startswith("2026-12-05T19:00")   # CET is UTC+1
    assert "05 Dec 2026, 20:00" in page


def test_the_qr_code_uses_the_public_address_when_one_is_set(app, admin_client, db, event):
    """Opened under a second name, the console used to print that name on the QR."""
    import dataclasses

    app.state.settings = dataclasses.replace(app.state.settings, public_url="https://hlasuj.example.cz")
    on_admin_host = {"host": "admin.example.cz"}

    share = admin_client.get(f"/admin/events/{event.id}?tab=share", headers=on_admin_host).text
    code = admin_client.get(f"/admin/events/{event.id}/qr.svg", headers=on_admin_host)

    assert f"https://hlasuj.example.cz/e/{event.slug}" in share
    assert "https://hlasuj.example.cz/band/" in share
    assert "admin.example.cz/e/" not in share
    assert code.status_code == 200


def test_the_new_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("JUKEBOX_DEV", "1")
    monkeypatch.setenv("JUKEBOX_PUBLIC_URL", "https://hlasuj.example.cz/")
    monkeypatch.setenv("JUKEBOX_THREADS", "6")
    settings = load_settings()
    assert settings.public_url == "https://hlasuj.example.cz"
    assert settings.worker_threads == 6
    assert settings.timezone == "Europe/Prague"


def test_the_draft_is_kept_until_the_ballot_is_counted(client, open_round, db):
    """A submit that fails on venue wifi must not cost the selection."""
    script = (JUKEBOX / "app" / "static" / "app.js").read_text(encoding="utf-8")
    submit_handler = script.split('form.addEventListener("submit"')[1].split("});")[0]
    assert "removeItem" not in submit_handler

    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})
    pick = rounds.votable_songs(db.read(), open_round.id)[0]["id"]
    receipt = client.post(f"/e/{event.slug}/ballot", follow_redirects=True,
                          data={"ballot_id": "a", "round_id": open_round.id, "song_ids": [pick]}).text
    assert f'data-voted-round="{open_round.id}"' in receipt


# ---------------------------------------------- docs/08, the storage seam --
def test_transact_commits_what_the_callback_did_and_returns_its_result(db):
    def work(conn):
        conn.execute("INSERT INTO songs (title, artist) VALUES ('A', 'B')")
        return conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]

    assert db.transact(work) == 1
    assert db.read().execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1


def test_transact_rolls_back_and_reraises_what_the_callback_raised(db):
    def work(conn):
        conn.execute("INSERT INTO songs (title, artist) VALUES ('A', 'B')")
        raise Invalid("no")

    with pytest.raises(Invalid):
        db.transact(work)
    assert db.read().execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 0


def test_migrations_are_recorded_by_name_and_applied_once(tmp_path):
    from app.db import MIGRATIONS, Database, applied_migrations

    database = Database(tmp_path / "x.db")
    assert database.migrate() == len(MIGRATIONS)
    assert database.migrate() == len(MIGRATIONS)
    assert applied_migrations(database.read()) == [p.name for p in MIGRATIONS]


def test_a_database_counted_in_user_version_is_recognised_as_migrated(tmp_path):
    from app.db import MIGRATIONS, Database, applied_migrations

    # Made the way the app did before schema_migrations existed.
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(MIGRATIONS[0].read_text(encoding="utf-8"))
    old.execute("INSERT INTO songs (title, artist) VALUES ('Hello', 'Adele')")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()

    database = Database(path)
    assert database.migrate() == len(MIGRATIONS)
    assert applied_migrations(database.read())[0] == MIGRATIONS[0].name
    assert database.read().execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1


def test_a_migration_is_split_on_semicolons_outside_quotes_and_comments():
    from app.db import statements

    script = (
        "-- a comment; with a semicolon and an apostrophe's\n"
        "CREATE TABLE a (x TEXT DEFAULT ';');\n"
        "/* block; comment */ INSERT INTO a VALUES ('it''s; fine');\n"
        "SELECT \"odd;name\" FROM a"
    )
    assert statements(script) == [
        "CREATE TABLE a (x TEXT DEFAULT ';')",
        "INSERT INTO a VALUES ('it''s; fine')",
        'SELECT "odd;name" FROM a',
    ]
