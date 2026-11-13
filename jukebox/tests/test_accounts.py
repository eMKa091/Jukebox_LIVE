"""Accounts on the Worker (docs/08-cloudflare-port.md, step 6).

The object has 128 MB for everything, no shell to run the CLI in, and empties
its memory whenever it sleeps. Each test here is one of those three.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.domain import identity
from app.domain.errors import NotPermitted
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER

SETUP_TOKEN = "a-long-random-setup-token"


# ------------------------------------------------------------------ 6.1 --
def test_passwords_are_hashed_with_19_mib_not_64():
    assert identity.hash_password("x" * 10).startswith("$argon2id$v=19$m=19456,t=2,p=1$")


def test_an_account_hashed_the_old_way_signs_in_and_is_rehashed(db):
    old = PasswordHasher().hash(ADMIN_PASSWORD)  # argon2-cffi's default, 64 MiB
    db.transact(lambda conn: conn.execute(
        "INSERT INTO admin_users (username, password_hash, created_at) VALUES ('old', ?, 'x')",
        (old,)))
    throttle = identity.LoginThrottle(db, max_attempts=4, window_seconds=900)

    assert identity.authenticate(db, username="old", password=ADMIN_PASSWORD,
                                 throttle=throttle) == "old"
    stored = db.read().execute(
        "SELECT password_hash FROM admin_users WHERE username = 'old'").fetchone()[0]
    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


# ------------------------------------------------------------------ 6.3 --
def test_the_throttle_outlives_the_app_that_counted(settings, db, app):
    """An object that slept starts with empty memory; the count must not."""
    with TestClient(app) as first:
        for _ in range(settings.login_max_attempts):
            first.post("/admin/login", data={"username": ADMIN_USER, "password": "wrong"})

    with TestClient(create_app(settings, db=db)) as woken:
        refused = woken.post("/admin/login", follow_redirects=False,
                             data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert refused.headers["location"] == "/admin/login"


def test_old_failures_are_forgotten(db):
    throttle = identity.LoginThrottle(db, max_attempts=2, window_seconds=900)
    db.transact(lambda conn: conn.execute(
        "INSERT INTO login_failures (client, at) VALUES ('a', 0), ('a', 1)"))
    throttle.check("a")  # far outside the window: not counted
    throttle.record_failure("b")
    assert db.read().execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 1


# ------------------------------------------------------------------ 6.2 --
@pytest.fixture
def fresh(settings, db):
    """The app as first deployed: a setup token, and no account at all."""
    with TestClient(create_app(replace(settings, setup_token=SETUP_TOKEN), db=db)) as client:
        yield client


def _setup(client, token=SETUP_TOKEN, password=ADMIN_PASSWORD, repeat=ADMIN_PASSWORD):
    return client.post("/admin/setup", follow_redirects=False, data={
        "token": token, "username": ADMIN_USER, "password": password, "repeat": repeat})


def test_the_setup_page_makes_the_first_account_and_is_then_gone(fresh, db):
    assert fresh.get("/admin/setup").status_code == 200

    made = _setup(fresh)
    assert made.headers["location"] == "/admin/login"
    assert identity.admin_count(db.read()) == 1
    signed_in = fresh.post("/admin/login", follow_redirects=False,
                           data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert signed_in.headers["location"] == "/admin"

    assert fresh.get("/admin/setup").status_code == 404
    assert _setup(fresh).status_code == 404
    assert identity.admin_count(db.read()) == 1


def test_the_setup_page_wants_the_token(fresh, db):
    refused = _setup(fresh, token="guess")
    assert refused.headers["location"] == "/admin/setup"
    assert identity.admin_count(db.read()) == 0
    assert _setup(fresh, repeat="something-else").headers["location"] == "/admin/setup"
    assert identity.admin_count(db.read()) == 0


def test_guessing_the_setup_token_is_throttled(fresh, db, settings):
    for _ in range(settings.login_max_attempts):
        _setup(fresh, token="guess")
    _setup(fresh)  # the right token, too late
    assert identity.admin_count(db.read()) == 0


def test_without_a_token_there_is_no_setup_page(settings, db):
    with TestClient(create_app(settings, db=db)) as client:
        assert client.get("/admin/setup").status_code == 404
        assert _setup(client, token="").status_code == 404


def test_a_first_account_is_refused_once_there_is_one(db):
    identity.create_admin(db, username="a", password=ADMIN_PASSWORD, first=True)
    with pytest.raises(NotPermitted):
        identity.create_admin(db, username="b", password=ADMIN_PASSWORD, first=True)
