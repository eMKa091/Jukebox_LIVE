"""Songs added after a round was built.

Reported from a gig: "when adding new songs during gig being active / in
between rounds, the songs do not appear."

They did not, and could not. A round owns its own song list -- which is what
makes per-round exclusion and "played" work -- and that list is populated only
when the event is created or when songs are carried forward from the previous
round. A song added to the master list afterwards belonged to no round, so it
could never reach a ballot, and nothing in the console said why.
"""

from __future__ import annotations

import pytest

from app.domain import ballots, events, rounds, songs
from app.domain.errors import Invalid, NotFound


def titles(rows) -> set[str]:
    return {r["title"] for r in rows}


# ------------------------------------------------------- the bug itself --
def test_a_song_added_mid_round_reaches_the_ballot(db, open_round):
    """The reported case: a guest asks for something while voting is open."""
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")

    assert "Wonderwall" not in titles(rounds.votable_songs(db.read(), open_round.id))
    gap = rounds.songs_not_in_round(db.read(), open_round.id)
    assert [r["id"] for r in gap] == [added.id]

    assert rounds.add_songs(db, round_id=open_round.id, song_ids=[added.id], actor="marek") == 1
    assert "Wonderwall" in titles(rounds.votable_songs(db.read(), open_round.id))


def test_a_song_added_between_rounds_reaches_the_next_one(db, open_round):
    """Carrying forward copies the previous round, not the master list."""
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")
    rounds.transition(db, round_id=open_round.id, to="closed", actor="marek")
    rounds.carry_forward(db, from_round=open_round.id, actor="marek")

    second = rounds.for_event(db.read(), open_round.event_id)[1]
    assert "Wonderwall" not in titles(rounds.votable_songs(db.read(), second.id))

    rounds.add_songs(db, round_id=second.id, song_ids=[added.id], actor="marek")
    assert "Wonderwall" in titles(rounds.votable_songs(db.read(), second.id))


def test_a_song_added_to_a_round_can_actually_be_voted_for(db, open_round):
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")
    rounds.add_songs(db, round_id=open_round.id, song_ids=[added.id], actor="marek")

    voter = ballots.voter_for_device(db, event_id=open_round.event_id,
                                     device_token="d", display_name="Filip")
    receipt = ballots.submit(db, round_id=open_round.id, voter_id=voter,
                             song_ids=[added.id], ballot_id="b1")
    assert receipt.accepted == 1
    assert ballots.tally(db.read(), open_round.id)[0]["title"] == "Wonderwall"


# ------------------------------------------------------------ the rules --
def test_adding_the_same_song_twice_is_a_no_op(db, open_round, catalogue):
    already = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:2]
    assert rounds.add_songs(db, round_id=open_round.id, song_ids=already, actor="m") == 0


def test_adding_does_not_resurrect_an_excluded_song(db, open_round):
    """Exclusion is a decision about this round, and adding must not undo it."""
    picks = [r["id"] for r in rounds.votable_songs(db.read(), open_round.id)][:1]
    rounds.set_excluded(db, round_id=open_round.id, song_ids=picks, excluded=True, actor="m")

    rounds.add_songs(db, round_id=open_round.id, song_ids=picks, actor="m")
    board = {s["id"]: s for s in rounds.song_board(db.read(), open_round.id)}
    assert board[picks[0]]["excluded"] is True


def test_a_retired_song_is_refused_out_loud(db, open_round):
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="m")
    songs.set_retired(db, song_id=added.id, retired=True, actor="m")
    with pytest.raises(Invalid, match="Retired"):
        rounds.add_songs(db, round_id=open_round.id, song_ids=[added.id], actor="m")


def test_a_song_that_does_not_exist_is_refused(db, open_round):
    with pytest.raises(NotFound):
        rounds.add_songs(db, round_id=open_round.id, song_ids=[999999], actor="m")


def test_retired_songs_never_show_up_as_missing(db, open_round):
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="m")
    songs.set_retired(db, song_id=added.id, retired=True, actor="m")
    assert rounds.songs_not_in_round(db.read(), open_round.id) == []


def test_the_addition_is_logged_with_whether_voting_was_open(db, open_round):
    from app.domain import log

    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")
    rounds.add_songs(db, round_id=open_round.id, song_ids=[added.id], actor="marek")

    entry = next(e for e in log.for_event(db.read(), open_round.event_id)
                 if e["action"] == "round.songs_added")
    assert entry["payload"]["added"] == 1
    assert entry["payload"]["while_open"] is True


# --------------------------------------------------------- the console --
def test_the_console_surfaces_the_gap(admin_client, db, open_round):
    songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")

    page = admin_client.get(f"/admin/events/{open_round.event_id}?tab=songs").text
    assert "not in this round" in page
    assert "Review them" in page
    # And on the tab itself, so it is visible from any other tab.
    assert 'class="badge"' in admin_client.get(
        f"/admin/events/{open_round.event_id}?tab=run"
    ).text


def test_the_missing_filter_lists_only_the_gap(admin_client, db, open_round, catalogue):
    import re

    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")
    page = admin_client.get(
        f"/admin/events/{open_round.event_id}?tab=songs&round={open_round.id}&filter=missing"
    ).text
    assert set(re.findall(r'name="song_ids" value="(\d+)"', page)) == {str(added.id)}
    assert "Wonderwall" in page


def test_adding_from_the_console_puts_it_on_the_ballot(admin_client, db, open_round):
    added = songs.add(db, title="Wonderwall", artist="Oasis", actor="marek")
    response = admin_client.post(
        f"/admin/rounds/{open_round.id}/songs",
        data={"action": "add", "song_ids": [added.id], "filter": "missing", "q": ""},
        follow_redirects=True,
    )
    assert "added to round 1" in response.text
    assert "ballot has been refreshed" in response.text
    assert "Wonderwall" in titles(rounds.votable_songs(db.read(), open_round.id))


def test_add_all_needs_no_selection(admin_client, db, open_round):
    for artist, title in [("Oasis", "Wonderwall"), ("Blur", "Parklife")]:
        songs.add(db, title=title, artist=artist, actor="marek")

    admin_client.post(f"/admin/rounds/{open_round.id}/songs", data={"action": "add_all"})
    assert rounds.songs_not_in_round(db.read(), open_round.id) == []


def test_add_all_says_so_when_there_is_nothing_to_add(admin_client, db, open_round):
    response = admin_client.post(
        f"/admin/rounds/{open_round.id}/songs",
        data={"action": "add_all"}, follow_redirects=True,
    )
    assert "already has every song" in response.text


def test_the_songs_page_warns_and_links_during_a_live_event(admin_client, db, open_round):
    """Adding to the master list mid-gig is half an answer without the link."""
    response = admin_client.post(
        "/admin/songs",
        data={"title": "Wonderwall", "artist": "Oasis"},
        follow_redirects=True,
    )
    assert "not on the ballot yet" in response.text
    assert f"filter=missing" in response.text
    assert "Add to round 1" in response.text


def test_the_songs_page_stays_quiet_when_nothing_is_live(admin_client, db, event):
    response = admin_client.post(
        "/admin/songs",
        data={"title": "Wonderwall", "artist": "Oasis"},
        follow_redirects=True,
    )
    assert "Added Wonderwall." in response.text
    assert "not on the ballot" not in response.text


def test_a_csv_import_mid_gig_warns_too(admin_client, db, open_round):
    response = admin_client.post(
        "/admin/songs/import",
        files={"file": ("new.csv", b"Artist;Title\nOasis;Wonderwall\n", "text/csv")},
        follow_redirects=True,
    )
    assert "not on the ballot yet" in response.text
    assert "Add to round 1" in response.text
