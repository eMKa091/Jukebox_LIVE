"""Live updates over WebSockets (docs/08-cloudflare-port.md, step 4).

Each screen opens a socket to its page's /stream address. The first message
names the event's stamp; later ones say what changed. The same address over
plain HTTP is what the Durable Object asks before it accepts a socket itself.
"""

from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.domain import events, log, rounds
from app.web.hub import event_topic, votes_topic


def _join(client, event):
    client.post(f"/e/{event.slug}/join", data={"display_name": "Eva"})


def test_a_phone_is_told_the_stamp_first(client, live_event, db):
    _join(client, live_event)
    with client.websocket_connect(f"/e/{live_event.slug}/stream") as ws:
        ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["stamp"] == log.stamp(db.read(), live_event.id)


def test_a_round_opening_reaches_the_phones_and_asks_for_a_reload(admin_client, live_event, db):
    first = rounds.for_event(db.read(), live_event.id)[0]
    with admin_client.websocket_connect(f"/e/{live_event.slug}/stream") as ws:
        ws.receive_json()  # ready
        admin_client.post(f"/admin/rounds/{first.id}/state", data={"to": "open"})
        update = ws.receive_json()
    assert update["type"] == "update" and update["reload"] is True


def test_votes_reach_the_band_and_the_console_not_the_phones(admin_client, open_round, db):
    hub = admin_client.app.state.hub
    event = events.get(db.read(), open_round.event_id)
    with admin_client.websocket_connect(f"/admin/events/{event.id}/stream") as console:
        console.receive_json()
        assert hub.subscriber_count(votes_topic(event.id)) == 1
        assert hub.subscriber_count(event_topic(event.id)) == 1
        _join(admin_client, event)
        pick = rounds.votable_songs(db.read(), open_round.id)[0]["id"]
        admin_client.post(f"/e/{event.slug}/ballot",
                          data={"ballot_id": "a", "round_id": open_round.id, "song_ids": [pick]})
        assert console.receive_json()["kind"] == "votes"


def test_a_ping_is_answered(client, live_event):
    with client.websocket_connect(f"/e/{live_event.slug}/stream") as ws:
        ws.receive_json()
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_a_socket_the_route_refuses_is_closed_as_a_policy_violation(client, live_event):
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/e/no-such-event/stream") as ws:
            ws.receive_json()
    assert refused.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as signed_out:
        with client.websocket_connect(f"/admin/events/{live_event.id}/stream") as ws:
            ws.receive_json()
    assert signed_out.value.code == 1008


def test_the_object_asks_the_route_for_the_topics_over_http(client, admin_client, live_event, db):
    upgrade = {"upgrade": "websocket"}
    phone = client.get(f"/e/{live_event.slug}/stream", headers=upgrade).json()
    assert phone == {"topics": [event_topic(live_event.id)],
                     "ready": {"stamp": log.stamp(db.read(), live_event.id)}}

    console = admin_client.get(f"/admin/events/{live_event.id}/stream", headers=upgrade).json()
    assert console["topics"] == [event_topic(live_event.id), votes_topic(live_event.id)]

    # Without the upgrade it is not a page anyone should be shown.
    assert client.get(f"/e/{live_event.slug}/stream").status_code == 426


def test_the_band_link_must_be_signed_to_subscribe(client, live_event):
    response = client.get("/band/not-a-token/stream", headers={"upgrade": "websocket"})
    assert response.status_code == 403
