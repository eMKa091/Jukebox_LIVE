"""Voting. Gate G3 and G4.

The two properties that did not exist before: submitting is idempotent, and
"have I already voted" is a database fact rather than a session variable.
"""

from __future__ import annotations

import threading

import pytest

from app.domain import ballots, rounds
from app.domain.errors import Conflict, Invalid


@pytest.fixture
def voter(db, open_round):
    return ballots.voter_for_device(
        db, event_id=open_round.event_id, device_token="device-a", display_name="Filip"
    )


def song_ids(db, round_id, n=5):
    return [r["id"] for r in rounds.votable_songs(db.read(), round_id)][:n]


def test_a_ballot_is_counted(db, open_round, voter):
    picks = song_ids(db, open_round.id)
    receipt = ballots.submit(db, round_id=open_round.id, voter_id=voter,
                             song_ids=picks, ballot_id="b1")
    assert receipt.accepted == 5
    assert receipt.replay is False
    assert ballots.round_stats(db.read(), open_round.id) == {"votes": 5, "voters": 1}


def test_the_same_ballot_twice_is_one_ballot(db, open_round, voter):
    """A double tap on bad signal must not double-count."""
    picks = song_ids(db, open_round.id)
    ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b1")
    again = ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b1")
    assert again.replay is True
    assert again.accepted == 5
    assert ballots.round_stats(db.read(), open_round.id)["votes"] == 5


def test_a_second_different_ballot_is_refused(db, open_round, voter):
    ballots.submit(db, round_id=open_round.id, voter_id=voter,
                   song_ids=song_ids(db, open_round.id, 2), ballot_id="b1")
    with pytest.raises(Conflict):
        ballots.submit(db, round_id=open_round.id, voter_id=voter,
                       song_ids=song_ids(db, open_round.id, 3), ballot_id="b2")
    assert ballots.round_stats(db.read(), open_round.id)["votes"] == 2


def test_the_vote_limit_is_enforced_server_side(db, open_round, voter):
    """The client dims extra rows; the server is what actually decides."""
    with pytest.raises(Invalid, match="nejvýše 5"):
        ballots.submit(db, round_id=open_round.id, voter_id=voter,
                       song_ids=song_ids(db, open_round.id, 6), ballot_id="b1")
    assert ballots.round_stats(db.read(), open_round.id)["votes"] == 0


def test_voting_into_a_closed_round_is_refused(db, open_round, voter):
    picks = song_ids(db, open_round.id)
    rounds.transition(db, round_id=open_round.id, to="closed", actor="t")
    with pytest.raises(Conflict, match="uzavřeno"):
        ballots.submit(db, round_id=open_round.id, voter_id=voter,
                       song_ids=picks, ballot_id="b1")


def test_voting_for_an_excluded_song_is_refused(db, open_round, voter):
    picks = song_ids(db, open_round.id)
    rounds.set_excluded(db, round_id=open_round.id, song_ids=picks[:1], excluded=True, actor="t")
    with pytest.raises(Invalid, match="nejsou k dispozici"):
        ballots.submit(db, round_id=open_round.id, voter_id=voter,
                       song_ids=picks, ballot_id="b1")


def test_an_empty_ballot_is_refused(db, open_round, voter):
    with pytest.raises(Invalid):
        ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=[], ballot_id="b1")


def test_duplicate_picks_inside_one_ballot_collapse(db, open_round, voter):
    one = song_ids(db, open_round.id, 1)
    receipt = ballots.submit(db, round_id=open_round.id, voter_id=voter,
                             song_ids=one * 4, ballot_id="b1")
    assert receipt.accepted == 1


# -------------------------------------------------------------- identity --
def test_identity_is_the_device_not_the_name(db, open_round):
    """Re-entering under a different name is the same voter (F6)."""
    first = ballots.voter_for_device(db, event_id=open_round.event_id,
                                     device_token="device-a", display_name="Martin")
    second = ballots.voter_for_device(db, event_id=open_round.event_id,
                                      device_token="device-a", display_name="Martin ")
    assert first == second
    row = ballots.voter_in_event(db.read(), event_id=open_round.event_id, device_token="device-a")
    assert row["display_name"] == "Martin"  # trimmed


def test_different_devices_are_different_voters(db, open_round):
    a = ballots.voter_for_device(db, event_id=open_round.event_id,
                                 device_token="device-a", display_name="Eva")
    b = ballots.voter_for_device(db, event_id=open_round.event_id,
                                 device_token="device-b", display_name="Eva")
    assert a != b


def test_a_name_is_required(db, open_round):
    with pytest.raises(Invalid):
        ballots.voter_for_device(db, event_id=open_round.event_id,
                                 device_token="device-c", display_name="   ")


def test_submitted_songs_survives_a_new_session(db, open_round, voter):
    """The legacy check lived in st.session_state and died on refresh."""
    picks = song_ids(db, open_round.id, 3)
    ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b1")
    assert sorted(ballots.submitted_songs(db.read(), round_id=open_round.id, voter_id=voter)) == sorted(picks)


# ---------------------------------------------------------------- counts --
def test_tally_ranks_and_ties(db, open_round):
    picks = song_ids(db, open_round.id, 3)
    for n, token in enumerate(("d1", "d2", "d3")):
        v = ballots.voter_for_device(db, event_id=open_round.event_id,
                                     device_token=token, display_name=f"v{n}")
        # picks[0] gets 3 votes, picks[1] gets 2, picks[2] gets 1
        ballots.submit(db, round_id=open_round.id, voter_id=v,
                       song_ids=picks[: 3 - n], ballot_id=f"b{n}")

    table = ballots.tally(db.read(), open_round.id)
    assert [row["votes"] for row in table[:3]] == [3, 2, 1]
    assert [row["rank"] for row in table[:3]] == [1, 2, 3]
    # Everything unvoted ties on zero and shares a rank.
    zeros = [row for row in table if row["votes"] == 0]
    assert len({row["rank"] for row in zeros}) == 1


def test_played_songs_drop_out_of_the_tally(db, open_round, voter):
    picks = song_ids(db, open_round.id, 2)
    ballots.submit(db, round_id=open_round.id, voter_id=voter, song_ids=picks, ballot_id="b1")
    rounds.set_played(db, round_id=open_round.id, song_ids=picks[:1], played=True, actor="t")
    assert picks[0] not in {row["id"] for row in ballots.tally(db.read(), open_round.id)}


def test_a_burst_of_voters_all_land(db, open_round):
    """Sixty simultaneous ballots. Nothing lost, nothing double-counted."""
    from app.db import Database

    picks = song_ids(db, open_round.id, 3)
    errors: list[Exception] = []
    barrier = threading.Barrier(60)

    def vote(n: int) -> None:
        own = Database(db.path)
        try:
            v = ballots.voter_for_device(own, event_id=open_round.event_id,
                                         device_token=f"burst-{n}", display_name=f"host{n}")
            barrier.wait()
            ballots.submit(own, round_id=open_round.id, voter_id=v,
                           song_ids=picks, ballot_id=f"burst-b{n}")
        except Exception as exc:  # noqa: BLE001 - the test is what it says
            errors.append(exc)
        finally:
            own.close()

    threads = [threading.Thread(target=vote, args=(n,)) for n in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors[:3]
    assert ballots.round_stats(db.read(), open_round.id) == {"votes": 180, "voters": 60}
