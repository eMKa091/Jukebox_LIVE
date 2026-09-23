"""The state machine. Gate G3.

Every legal transition has a test, and so does every illegal one -- the point
of this file is that a refusal is a feature, not an omission. The legacy code
had no refusals at all: starting an event silently stopped whatever else was
running.
"""

from __future__ import annotations

import threading

import pytest

from app.domain import events, rounds
from app.domain.errors import Conflict, Invalid, NotFound


# ----------------------------------------------------------------- events --
def test_event_starts_as_draft_with_its_rounds(db, event):
    assert event.state == "draft"
    assert [r.ordinal for r in rounds.for_event(db.read(), event.id)] == [1, 2]
    assert all(r.state == "pending" for r in rounds.for_event(db.read(), event.id))


@pytest.mark.parametrize("path", [
    ["ready"],
    ["ready", "live"],
    ["ready", "live", "closed"],
    ["ready", "live", "ready"],
    ["ready", "live", "closed", "ready"],
    ["ready", "draft"],
])
def test_legal_event_paths(db, event, path):
    for step in path:
        result = events.transition(db, event_id=event.id, to=step, actor="t")
        assert result.state == step


@pytest.mark.parametrize("target", ["live", "closed"])
def test_draft_cannot_skip_ahead(db, event, target):
    with pytest.raises(Conflict):
        events.transition(db, event_id=event.id, to=target, actor="t")


def test_only_one_event_can_be_live(db, live_event, catalogue):
    other = events.create(db, name="Second", starts_at="2026-10-05T18:00:00Z", actor="t")
    events.transition(db, event_id=other.id, to="ready", actor="t")
    with pytest.raises(Conflict, match="already live"):
        events.transition(db, event_id=other.id, to="live", actor="t")
    # And the first event is untouched -- the legacy code stopped it silently.
    assert events.get(db.read(), live_event.id).state == "live"


def test_leaving_live_closes_the_open_round(db, open_round):
    events.transition(db, event_id=open_round.event_id, to="closed", actor="t")
    assert rounds.get(db.read(), open_round.id).state == "closed"
    assert rounds.open_round_of(db.read(), open_round.event_id) is None


def test_a_live_event_cannot_be_deleted(db, live_event):
    with pytest.raises(Conflict):
        events.delete(db, event_id=live_event.id, actor="t")


def test_unknown_state_is_rejected(db, event):
    with pytest.raises(Invalid):
        events.transition(db, event_id=event.id, to="banana", actor="t")


def test_missing_event(db):
    with pytest.raises(NotFound):
        events.transition(db, event_id=9999, to="ready", actor="t")


def test_event_needs_a_name(db):
    with pytest.raises(Invalid):
        events.create(db, name="   ", starts_at="2026-10-04T18:00:00Z", actor="t")


def test_event_rejects_a_bad_timestamp(db):
    with pytest.raises(Invalid):
        events.create(db, name="Bad", starts_at="04.10.2026", actor="t")


# ----------------------------------------------------------------- rounds --
def test_round_cannot_open_unless_the_event_is_live(db, event):
    first = rounds.for_event(db.read(), event.id)[0]
    with pytest.raises(Conflict, match="on air"):
        rounds.transition(db, round_id=first.id, to="open", actor="t")


def test_only_one_round_open_per_event(db, open_round):
    second = rounds.for_event(db.read(), open_round.event_id)[1]
    with pytest.raises(Conflict, match="still open"):
        rounds.transition(db, round_id=second.id, to="open", actor="t")


def test_round_with_no_songs_cannot_open(db, live_event):
    second = rounds.for_event(db.read(), live_event.id)[1]  # nothing assigned
    with pytest.raises(Conflict, match="no songs"):
        rounds.transition(db, round_id=second.id, to="open", actor="t")


def test_closed_round_can_reopen(db, open_round):
    rounds.transition(db, round_id=open_round.id, to="closed", actor="t")
    reopened = rounds.transition(db, round_id=open_round.id, to="open", actor="t")
    assert reopened.state == "open"


def test_pending_cannot_jump_to_closed(db, live_event):
    second = rounds.for_event(db.read(), live_event.id)[1]
    with pytest.raises(Conflict):
        rounds.transition(db, round_id=second.id, to="closed", actor="t")


def test_max_votes_is_frozen_while_a_round_is_open(db, open_round):
    with pytest.raises(Conflict, match="Close the round"):
        rounds.set_max_votes(db, round_id=open_round.id, max_votes=8, actor="t")


def test_max_votes_bounds(db, live_event):
    second = rounds.for_event(db.read(), live_event.id)[1]
    for bad in (0, 51):
        with pytest.raises(Invalid):
            rounds.set_max_votes(db, round_id=second.id, max_votes=bad, actor="t")


def test_two_threads_opening_rounds_produce_one_winner(db, live_event, catalogue):
    """Concurrency. The database decides, not a check-then-act in Python."""
    first, second = rounds.for_event(db.read(), live_event.id)
    rounds.assign_all_songs(db, round_id=second.id, actor="t")

    from app.db import Database

    results: list[object] = []
    barrier = threading.Barrier(2)

    def attempt(round_id: int) -> None:
        # A separate Database object per thread: two genuinely independent
        # connections to the same file, which is what production looks like.
        own = Database(db.path)
        barrier.wait()
        try:
            results.append(rounds.transition(own, round_id=round_id, to="open", actor="t"))
        except Conflict as exc:
            results.append(exc)
        finally:
            own.close()

    threads = [threading.Thread(target=attempt, args=(r.id,)) for r in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    opened = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, Conflict)]
    assert len(opened) == 1, f"expected exactly one winner, got {results}"
    assert len(refused) == 1
    assert rounds.open_round_of(db.read(), live_event.id).id == opened[0].id


def test_every_transition_is_logged(db, open_round):
    from app.domain import log

    actions = [e["action"] for e in log.for_event(db.read(), open_round.event_id)]
    assert "event.created" in actions
    assert "event.live" in actions
    assert "round.open" in actions
