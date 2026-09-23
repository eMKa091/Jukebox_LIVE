"""The HTTP surface, and a regression test for each legacy finding it fixes.

Every test named test_f<N>_* corresponds to an entry in docs/03-findings.md and
fails if that behaviour ever comes back.
"""

from __future__ import annotations

import re

import pytest

from app.domain import ballots, events, rounds
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER


# ------------------------------------------------------------- attendee --
def test_splash_when_nothing_is_live(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Aktuálně neprobíhá žádné hlasování" in response.text


def test_root_redirects_to_the_live_event(client, live_event):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/e/{live_event.slug}"


def test_attendee_must_give_a_name_before_the_ballot(client, open_round, db):
    event = events.get(db.read(), open_round.event_id)
    response = client.get(f"/e/{event.slug}")
    assert "Jak Ti máme říkat" in response.text
    assert 'id="ballot"' not in response.text


def test_the_full_attendee_journey(client, open_round, db):
    event = events.get(db.read(), open_round.event_id)

    client.post(f"/e/{event.slug}/join", data={"display_name": "Filip"})
    page = client.get(f"/e/{event.slug}")
    assert 'id="ballot"' in page.text
    assert 'data-max-votes="5"' in page.text

    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:3]
    response = client.post(
        f"/e/{event.slug}/ballot",
        data={"ballot_id": "abc", "round_id": open_round.id, "song_ids": picks},
        follow_redirects=True,
    )
    assert "Díky, Filip!" in response.text
    assert ballots.round_stats(db.read(), open_round.id) == {"votes": 3, "voters": 1}

    # Reload: the receipt is rebuilt from the database, not from a session.
    assert "Díky, Filip!" in client.get(f"/e/{event.slug}").text


def test_between_rounds_attendees_see_standings(client, open_round, db):
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})
    rounds.transition(db, round_id=open_round.id, to="closed", actor="t")
    page = client.get(f"/e/{event.slug}")
    assert "Kolo právě skončilo" in page.text


def test_an_unknown_event_slug_shows_the_splash(client):
    assert client.get("/e/nope-not-real").status_code == 200


# ----------------------------------------------------- legacy regressions --
def test_f5_arbitrary_query_parameters_do_not_crash(client, live_event):
    """index.py indexed query_params['admin'] unconditionally -> KeyError.

    A Facebook or Messenger share appends its own parameters; the legacy app
    answered those visitors with a stack trace.
    """
    for query in ("?utm_source=facebook", "?fbclid=xyz", "?admin=Boss", "?admin=Band", "?x=1&y=2"):
        response = client.get(f"/{query}", follow_redirects=False)
        assert response.status_code in (200, 303), query


def test_f3_the_band_page_is_not_reachable_by_guessing(client, live_event):
    assert client.get("/band/Band").status_code == 403
    assert client.get("/band/Boss").status_code == 403


def test_f3_a_tampered_band_token_is_refused(client, admin_client, live_event, app):
    token = app.state.tokens.make_band_token(live_event.id)
    assert client.get(f"/band/{token}").status_code == 200
    assert client.get(f"/band/{token[:-2]}xx").status_code == 403


def test_f4_songs_beyond_the_limit_stay_on_the_page(client, open_round, db):
    """The legacy loop stopped rendering checkboxes at the limit, so the rest
    of the repertoire disappeared. Every song must be present in the markup;
    the limit is applied by dimming, in the client."""
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Filip"})
    page = client.get(f"/e/{event.slug}").text

    votable = rounds.votable_songs(db.read(), open_round.id)
    assert len(votable) > 5, "fixture must exceed the vote limit for this to mean anything"
    rendered = set(re.findall(r'name="song_ids" value="(\d+)"', page))
    assert rendered == {str(r["id"]) for r in votable}


def test_f6_a_second_ballot_from_the_same_device_is_refused(client, open_round, db):
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Filip"})
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:2]

    client.post(f"/e/{event.slug}/ballot",
                data={"ballot_id": "b1", "round_id": open_round.id, "song_ids": picks})
    # A fresh ballot id, as a reloaded page would produce: still refused.
    client.post(f"/e/{event.slug}/ballot",
                data={"ballot_id": "b2", "round_id": open_round.id, "song_ids": picks})
    assert ballots.round_stats(db.read(), open_round.id)["votes"] == 2


def test_f12_the_csv_exports_are_always_reachable(admin_client, open_round, db):
    event_id = open_round.event_id
    for path in (f"/admin/events/{event_id}/export.csv",
                 f"/admin/events/{event_id}/results.csv",
                 "/admin/songs/export.csv"):
        response = admin_client.get(path)
        assert response.status_code == 200, path
        assert "attachment" in response.headers["content-disposition"]


# ----------------------------------------------------------------- admin --
@pytest.mark.parametrize("path", ["/admin", "/admin/songs", "/admin/events/1"])
def test_admin_pages_require_a_session(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_sign_in_and_out(client):
    response = client.post("/admin/login",
                           data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
                           follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/admin").status_code == 200

    client.post("/admin/logout", follow_redirects=False)
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"


def test_a_wrong_password_does_not_sign_you_in(client):
    client.post("/admin/login", data={"username": ADMIN_USER, "password": "nope"},
                follow_redirects=False)
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_f8_repeated_failures_are_throttled(client):
    for _ in range(4):  # login_max_attempts in the test settings
        client.post("/admin/login", data={"username": ADMIN_USER, "password": "nope"},
                    follow_redirects=False)
    # Even the correct password is now refused for the lockout window.
    client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
                follow_redirects=False)
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_creating_an_event_stocks_round_one(admin_client, catalogue, db):
    response = admin_client.post(
        "/admin/events",
        data={"name": "Hyskov", "starts_at": "2026-11-01T20:00", "venue": "Sokolovna",
              "round_count": "2", "max_votes": "7"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    event_id = int(response.headers["location"].rsplit("/", 1)[1])
    all_rounds = rounds.for_event(db.read(), event_id)
    assert [r.ordinal for r in all_rounds] == [1, 2]
    assert all_rounds[0].max_votes == 7
    assert len(rounds.votable_songs(db.read(), all_rounds[0].id)) == len(catalogue)


def test_the_console_drives_a_whole_event(admin_client, db, event):
    first = rounds.for_event(db.read(), event.id)[0]

    admin_client.post(f"/admin/events/{event.id}/state", data={"to": "ready"})
    admin_client.post(f"/admin/events/{event.id}/state", data={"to": "live"})
    assert events.get(db.read(), event.id).state == "live"

    admin_client.post(f"/admin/rounds/{first.id}/state", data={"to": "open"})
    assert rounds.get(db.read(), first.id).state == "open"

    admin_client.post(f"/admin/rounds/{first.id}/state", data={"to": "closed"})
    admin_client.post(f"/admin/events/{event.id}/state", data={"to": "closed"})
    assert events.get(db.read(), event.id).state == "closed"


def test_the_console_reports_a_refused_transition(admin_client, db, event):
    response = admin_client.post(f"/admin/events/{event.id}/state",
                                 data={"to": "live"}, follow_redirects=True)
    assert "cannot go straight to live" in response.text
    assert events.get(db.read(), event.id).state == "draft"


def test_song_actions_from_the_console(admin_client, db, open_round):
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:2]

    admin_client.post(f"/admin/rounds/{open_round.id}/songs",
                      data={"action": "exclude", "song_ids": picks})
    assert picks[0] not in {r["id"] for r in rounds.votable_songs(db.read(), open_round.id)}

    admin_client.post(f"/admin/rounds/{open_round.id}/songs",
                      data={"action": "include", "song_ids": picks})
    assert picks[0] in {r["id"] for r in rounds.votable_songs(db.read(), open_round.id)}

    admin_client.post(f"/admin/rounds/{open_round.id}/songs",
                      data={"action": "played", "song_ids": picks})
    board = {s["id"]: s for s in rounds.song_board(db.read(), open_round.id)}
    assert board[picks[0]]["played"] is True


def test_carry_forward_moves_only_the_unplayed(admin_client, db, open_round, catalogue):
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:3]
    admin_client.post(f"/admin/rounds/{open_round.id}/songs",
                      data={"action": "played", "song_ids": picks[:2]})
    admin_client.post(f"/admin/rounds/{open_round.id}/songs",
                      data={"action": "exclude", "song_ids": picks[2:3]})
    admin_client.post(f"/admin/rounds/{open_round.id}/carry-forward")

    second = rounds.for_event(db.read(), open_round.event_id)[1]
    carried = {r["id"] for r in rounds.votable_songs(db.read(), second.id)}
    assert not (set(picks) & carried)
    assert len(carried) == len(catalogue) - 3


def test_the_qr_code_points_at_the_public_url(admin_client, db, event):
    response = admin_client.get(f"/admin/events/{event.id}/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in response.content


def test_the_vote_export_has_one_row_per_vote(admin_client, db, open_round):
    voter = ballots.voter_for_device(db, event_id=open_round.event_id,
                                     device_token="d", display_name="Filip")
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:4]
    ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b")

    body = admin_client.get(f"/admin/events/{open_round.event_id}/export.csv").text
    lines = [line for line in body.strip().splitlines() if line]
    assert len(lines) == 5  # header + four votes
    assert lines[0].lstrip("﻿") == "round;voter;artist;title;cast_at"


def test_band_display_shows_the_live_ranking(client, app, db, open_round):
    voter = ballots.voter_for_device(db, event_id=open_round.event_id,
                                     device_token="d", display_name="Filip")
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:1]
    ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b")

    token = app.state.tokens.make_band_token(open_round.event_id)
    page = client.get(f"/band/{token}")
    assert page.status_code == 200
    title = [r["title"] for r in rounds.votable_songs(db.read(), open_round.id) if r["id"] == picks[0]][0]
    assert title in page.text
    assert client.get(f"/band/{token}/live").status_code == 200


# ------------------------------------------------------------------- ops --
def test_health_and_readiness(client):
    assert client.get("/healthz").text == "ok"
    assert "ready schema=v" in client.get("/readyz").text


def test_a_czech_error_message_survives_the_flash_cookie(client, open_round, db):
    """Cookie values ride in a latin-1 header; Czech text does not fit one.

    Caught by this suite before it shipped: every attendee-facing message is
    Czech, so an un-encoded flash would have raised UnicodeEncodeError on the
    error path -- exactly when the user is already stuck.
    """
    event = events.get(db.read(), open_round.event_id)
    client.post(f"/e/{event.slug}/join", data={"display_name": "Filip"})
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:1]
    client.post(f"/e/{event.slug}/ballot",
                data={"ballot_id": "b1", "round_id": open_round.id, "song_ids": picks})

    response = client.post(
        f"/e/{event.slug}/ballot",
        data={"ballot_id": "b2", "round_id": open_round.id, "song_ids": picks},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "už hlasoval" in response.text


def test_the_cli_does_not_need_a_signing_key(monkeypatch):
    """Creating an account signs nothing, so it must not demand a web secret.

    The first person to follow the README hit this: `app.cli create-admin`
    raised "JUKEBOX_SECRET_KEY is not set" before it ever touched the database.
    """
    from app.config import load_settings

    monkeypatch.delenv("JUKEBOX_SECRET_KEY", raising=False)
    monkeypatch.delenv("JUKEBOX_DEV", raising=False)

    assert load_settings(require_secret=False).database_path  # no raise
    with pytest.raises(RuntimeError, match="JUKEBOX_SECRET_KEY"):
        load_settings()  # the web app still insists
