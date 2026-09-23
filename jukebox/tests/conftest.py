"""Shared fixtures.

Every test gets its own database file, so nothing leaks between tests and the
whole suite can run in parallel later if it ever needs to.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.domain import events, identity, rounds, songs  # noqa: E402

LEGACY_DB = Path(__file__).resolve().parents[2] / "jukeboxHeroes-v2" / "backups" / "backup-votes.db"

ADMIN_USER = "marek"
ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_path=tmp_path / "jukebox.db",
        secret_key="test-secret-not-used-anywhere-real",
        session_max_age=3600,
        login_max_attempts=4,
        login_window_seconds=900,
        dev_mode=True,
    )


@pytest.fixture
def db(settings) -> Database:
    database = Database(settings.database_path)
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def catalogue(db) -> list:
    """Twelve songs, enough to exercise a five-vote limit with room to spare."""
    for artist, title in [
        ("Adele", "Hello"), ("Queen", "Bohemian Rhapsody"), ("ABBA", "Mamma Mia"),
        ("Kabát", "Pohoda"), ("Wanastowi Vjecy", "Mimo mísu"), ("Elton John", "Your Song"),
        ("Toto", "Africa"), ("a-ha", "Take On Me"), ("Blur", "Song 2"),
        ("Lucie", "Medvídek"), ("Chinaski", "Vedle sebe"), ("Olympic", "Jasná zpráva"),
    ]:
        songs.add(db, title=title, artist=artist, actor="test")
    return songs.list_songs(db.read())


@pytest.fixture
def event(db, catalogue):
    """A two-round event, ready to go live, with round 1 fully stocked."""
    created = events.create(
        db, name="Krpole", starts_at="2026-10-04T18:00:00Z", round_count=2,
        max_votes=5, actor="test",
    )
    first = rounds.for_event(db.read(), created.id)[0]
    rounds.assign_all_songs(db, round_id=first.id, actor="test")
    return created


@pytest.fixture
def live_event(db, event):
    events.transition(db, event_id=event.id, to="ready", actor="test")
    return events.transition(db, event_id=event.id, to="live", actor="test")


@pytest.fixture
def open_round(db, live_event):
    first = rounds.for_event(db.read(), live_event.id)[0]
    return rounds.transition(db, round_id=first.id, to="open", actor="test")


@pytest.fixture
def app(settings, db):
    from app.main import create_app

    application = create_app(settings)
    application.state.db = db  # share the fixture's connection and migrations
    identity.create_admin(db, username=ADMIN_USER, password=ADMIN_PASSWORD)
    return application


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    response = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, "admin fixture could not sign in"
    return client
