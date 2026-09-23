"""The restructured admin console.

Structure only. The rules underneath are unchanged and are tested in
test_transitions.py and test_ballots.py -- app/domain/ was not touched by this
work, which is the point.
"""

from __future__ import annotations

import pytest

from app.domain import ballots, events, rounds


def ids_in(html: str) -> set[str]:
    import re

    return set(re.findall(r'name="song_ids" value="(\d+)"', html))


# ------------------------------------------------------------- dashboard --
def test_the_dashboard_groups_by_what_you_need_to_do(admin_client, db, catalogue):
    """Coming up, on air, done -- not one undifferentiated list."""
    soon = events.create(db, name="Next week", starts_at="2026-12-01T19:00:00Z", actor="t")
    done = events.create(db, name="Last month", starts_at="2026-08-01T19:00:00Z", actor="t")
    for step in ("ready", "live", "closed"):
        events.transition(db, event_id=done.id, to=step, actor="t")

    page = admin_client.get("/admin").text
    coming_at = page.index("Coming up")
    done_at = page.index(">Done<")
    assert coming_at < page.index("Next week") < done_at
    assert page.index("Last month") > done_at
    assert soon.name in page


def test_a_live_event_is_surfaced_above_everything(admin_client, db, open_round):
    page = admin_client.get("/admin").text
    assert "On air" in page
    assert page.index("On air") < page.index("Coming up")
    assert "Open console" in page


def test_past_events_are_paged(admin_client, db, catalogue):
    for n in range(15):
        e = events.create(db, name=f"Gig {n:02d}", starts_at=f"2026-0{1 + n % 9}-01T19:00:00Z", actor="t")
        # Only one event may be live at a time, so each goes up and straight
        # back down before the next one starts.
        for step in ("ready", "live", "closed"):
            events.transition(db, event_id=e.id, to=step, actor="t")

    first = admin_client.get("/admin").text
    assert "Show 3 more" in first          # 15 past, 12 per page

    everything = admin_client.get("/admin?limit=100").text
    assert "Show" not in everything.split("Done")[1][:400]


def test_the_dashboard_searches(admin_client, db, catalogue):
    events.create(db, name="Krpole", venue="Ostrava", starts_at="2026-11-01T19:00:00Z", actor="t")
    events.create(db, name="Hyskov", venue="Sokolovna", starts_at="2026-11-02T19:00:00Z", actor="t")

    hit = admin_client.get("/admin?q=sokol").text
    assert "Hyskov" in hit and "Krpole" not in hit


def test_creating_moved_to_its_own_page(admin_client, catalogue):
    """The form was permanent clutter on the list."""
    assert "New event" in admin_client.get("/admin").text
    assert admin_client.get("/admin/events/new").status_code == 200
    # POST target is unchanged, so nothing downstream had to move.
    assert 'action="/admin/events"' in admin_client.get("/admin/events/new").text


# --------------------------------------------------------------- console --
@pytest.mark.parametrize("tab", ["run", "songs", "share", "data"])
def test_every_tab_renders(admin_client, db, open_round, tab):
    response = admin_client.get(f"/admin/events/{open_round.event_id}?tab={tab}")
    assert response.status_code == 200


def test_an_unknown_tab_falls_back_to_run(admin_client, db, open_round):
    page = admin_client.get(f"/admin/events/{open_round.event_id}?tab=nonsense").text
    assert "Live results" in page


def test_the_header_is_the_same_on_every_tab(admin_client, db, open_round):
    """What is on air, which round, how many people -- never more than a glance."""
    for tab in ("run", "songs", "share", "data"):
        page = admin_client.get(f"/admin/events/{open_round.event_id}?tab={tab}").text
        assert "Round 1" in page, tab          # the round strip
        assert "voters" in page, tab           # the live counts
        assert "screens" in page, tab


def test_the_console_opens_on_the_round_that_matters(admin_client, db, live_event):
    """The open round, else the last one that ran, else the first."""
    first, second = rounds.for_event(db.read(), live_event.id)
    rounds.assign_all_songs(db, round_id=second.id, actor="t")

    # Nothing open yet -> round 1.
    page = admin_client.get(f"/admin/events/{live_event.id}").text
    assert "Start round 1" in page

    rounds.transition(db, round_id=second.id, to="open", actor="t")
    page = admin_client.get(f"/admin/events/{live_event.id}").text
    assert "Round 2 is taking votes" in page


def test_switching_round_keeps_the_tab(admin_client, db, live_event):
    second = rounds.for_event(db.read(), live_event.id)[1]
    page = admin_client.get(f"/admin/events/{live_event.id}?tab=songs").text
    assert f"tab=songs&amp;round={second.id}" in page


# ----------------------------------------------------------- songs tab ---
def test_the_song_filters_partition_the_round(admin_client, db, open_round, catalogue):
    everything = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)]
    rounds.set_excluded(db, round_id=open_round.id, song_ids=everything[:2], excluded=True, actor="t")
    rounds.set_played(db, round_id=open_round.id, song_ids=everything[2:4], played=True, actor="t")

    base = f"/admin/events/{open_round.event_id}?tab=songs&round={open_round.id}"
    available = ids_in(admin_client.get(f"{base}&filter=available").text)
    excluded = ids_in(admin_client.get(f"{base}&filter=excluded").text)
    played = ids_in(admin_client.get(f"{base}&filter=played").text)
    every = ids_in(admin_client.get(f"{base}&filter=all").text)

    assert excluded == {str(i) for i in everything[:2]}
    assert played == {str(i) for i in everything[2:4]}
    assert available == {str(i) for i in everything[4:]}
    # The three are a partition of the whole, with nothing lost or double-counted.
    assert available | excluded | played == every
    assert not (available & excluded) and not (available & played) and not (excluded & played)


def test_the_song_search_narrows_the_round(admin_client, db, open_round):
    base = f"/admin/events/{open_round.event_id}?tab=songs&round={open_round.id}"
    page = admin_client.get(f"{base}&filter=all&q=bohemian").text
    assert "Bohemian Rhapsody" in page
    assert "Mamma Mia" not in page


def test_a_bulk_action_returns_you_to_where_you_were(admin_client, db, open_round):
    """Filter, search and round all survive the round trip."""
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:1]
    response = admin_client.post(
        f"/admin/rounds/{open_round.id}/songs",
        data={"action": "exclude", "song_ids": picks, "filter": "played", "q": "queen"},
        follow_redirects=False,
    )
    location = response.headers["location"]
    assert "tab=songs" in location
    assert "filter=played" in location
    assert "q=queen" in location
    assert f"round={open_round.id}" in location


def test_carry_forward_lands_on_the_songs_tab(admin_client, db, open_round):
    response = admin_client.post(
        f"/admin/rounds/{open_round.id}/carry-forward", follow_redirects=False
    )
    assert "tab=songs" in response.headers["location"]


# ------------------------------------------------------------ songs page --
def test_the_master_list_separates_active_from_retired(admin_client, db, catalogue):
    from app.domain import songs

    songs.set_retired(db, song_id=catalogue[0].id, retired=True, actor="t")

    active = admin_client.get("/admin/songs").text
    assert catalogue[0].title not in active
    assert catalogue[1].title in active

    retired = admin_client.get("/admin/songs?show=retired").text
    assert catalogue[0].title in retired
    assert catalogue[1].title not in retired


def test_the_master_list_searches(admin_client, db, catalogue):
    page = admin_client.get("/admin/songs?q=abba").text
    assert "Mamma Mia" in page
    assert "Bohemian Rhapsody" not in page


def test_search_survives_the_active_retired_switch(admin_client, db, catalogue):
    page = admin_client.get("/admin/songs?q=queen").text
    assert "show=retired&amp;q=queen" in page
