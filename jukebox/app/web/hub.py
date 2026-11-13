"""Live updates over WebSockets: who is told when something changes.

When the admin opens a round, two hundred phones need to find out without being
told to refresh. The legacy app had no mechanism for this at all -- attendees
reloaded and hoped.

A screen subscribes by opening a WebSocket to its page's `/stream` address. The
route decides what it may hear and what it is told first (a `Subscription`);
the hub delivers. Two hubs, one interface:

  * `LocalHub` -- in this process: asyncio queues feeding sockets FastAPI
    accepted. Tests, and the app run with uvicorn.
  * `SocketHub` -- the Durable Object's own sockets (docs/08-cloudflare-port.md,
    step 4). The object accepts each one with the Hibernation API, tagged with
    its topics, so it can sleep while five hundred phones stay connected.
    Publishing is sending to every socket carrying the tag.

Every message is JSON with a `type`: first `ready`, carrying the event's state
stamp, then an `update` for each change. A client may send `ping` at any time
and is answered `pong`; on the object the runtime answers without waking it.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse, Response

PING, PONG = "ping", "pong"

# Bounded, so one stalled client cannot grow a queue without limit. If a client
# falls this far behind it is dropped and its browser reconnects, which
# re-syncs it from scratch anyway.
QUEUE_SIZE = 32

# A socket refused because the route said no (no such event, not signed in).
POLICY_VIOLATION = 1008


@dataclass(frozen=True)
class Subscription:
    """What one screen may hear, and what its first message says.

    `ready` carries the event's stamp, so a browser that was away -- a locked
    phone, a dropped connection, a restarted server -- can tell on reconnect
    that the page it is showing is out of date. Nothing is replayed; the page
    is simply fetched again.
    """

    topics: tuple[str, ...]
    ready: dict = field(default_factory=dict)


class Hub:
    """The interface. Payloads are deliberately thin: a version and what changed.

    The client responds by re-fetching the fragment it cares about, so there is
    exactly one renderer for every piece of UI -- the server -- and no
    client-side copy of the state to drift.
    """

    def __init__(self) -> None:
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def publish(self, topic: str, **payload) -> None:
        """Announce that something under `topic` changed."""
        self._version += 1
        self._send(topic, message("update", v=self._version, **payload))

    def ready(self, subscription: Subscription) -> str:
        return message("ready", v=self._version, **subscription.ready)

    def subscriber_count(self, topic: str) -> int:
        raise NotImplementedError

    def _send(self, topic: str, text: str) -> None:
        raise NotImplementedError


def message(type_: str, /, **payload) -> str:
    return json.dumps({"type": type_, **payload}, ensure_ascii=False)


# --------------------------------------------------------------- local --
class _Subscriber:
    """One open socket: its queue, and whether the hub has given up on it."""

    __slots__ = ("queue", "dropped")

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.dropped = False


class LocalHub(Hub):
    """One process: a set of asyncio queues rather than a message broker."""

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: dict[str, set[_Subscriber]] = defaultdict(set)

    def _send(self, topic: str, text: str) -> None:
        for subscriber in list(self._subscribers.get(topic, ())):
            try:
                subscriber.queue.put_nowait(text)
            except asyncio.QueueFull:
                # Drop the slow subscriber. Marking it is what ends its stream:
                # the socket closes, the browser reconnects, and the first
                # message it gets back tells it whether it missed anything.
                subscriber.dropped = True

    async def stream(self, *topics: str, ready: dict | None = None) -> AsyncIterator[str]:
        """Yield one subscriber's messages, `ready` first, until it is dropped."""
        subscriber = _Subscriber()
        for topic in topics:
            self._subscribers[topic].add(subscriber)
        try:
            yield self.ready(Subscription(topics, ready or {}))
            while not subscriber.dropped:
                yield await subscriber.queue.get()
        finally:
            for topic in topics:
                self._subscribers[topic].discard(subscriber)
                if not self._subscribers[topic]:
                    self._subscribers.pop(topic, None)

    async def serve(self, ws: WebSocket, subscription: Subscription) -> None:
        """Hold one socket open: send what the stream yields, answer pings."""
        await ws.accept()
        messages = self.stream(*subscription.topics, ready=subscription.ready)

        async def pump() -> None:
            async for text in messages:
                await ws.send_text(text)

        async def listen() -> None:
            while True:
                received = await ws.receive()
                if received["type"] == "websocket.disconnect":
                    return
                if received.get("text") == PING:
                    await ws.send_text(PONG)

        tasks = [asyncio.ensure_future(pump()), asyncio.ensure_future(listen())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            with suppress(Exception):
                await messages.aclose()
            with suppress(Exception):
                await ws.close()

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


# -------------------------------------------------------------- object --
class SocketHub(Hub):
    """The Durable Object's hibernating sockets. `ctx` is the object's state.

    The object (worker.py) accepts each socket tagged with its subscription's
    topics; this only finds them by tag. The version restarts when the object
    wakes from sleep, which is harmless: clients compare stamps, not versions.
    """

    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx

    def _send(self, topic: str, text: str) -> None:
        for ws in self._ctx.getWebSockets(topic):
            with suppress(Exception):  # a socket closing as we send
                ws.send(text)

    def subscriber_count(self, topic: str) -> int:
        return len(self._ctx.getWebSockets(topic))


# ---------------------------------------------------------------- routes --
def get_hub(conn: Request | WebSocket) -> Hub:
    return conn.app.state.hub


async def serve(ws: WebSocket, subscribe) -> None:
    """A `/stream` socket in this process. `subscribe()` is the route's rule."""
    from ..domain.errors import DomainError

    try:
        subscription = subscribe()
    except DomainError:
        await ws.close(code=POLICY_VIOLATION)
        return
    await get_hub(ws).serve(ws, subscription)


def subscription_response(request: Request, subscription: Subscription) -> Response:
    """The same `/stream` address over plain HTTP: what the object asks.

    The Durable Object cannot hand a hibernating socket to FastAPI, so it asks
    the route first, the WebSocket upgrade still on the request, and accepts
    the socket itself with the topics it is told. Anyone else gets a 426.
    """
    if request.headers.get("upgrade", "").lower() != "websocket":
        return PlainTextResponse("This address takes a WebSocket.", status_code=426)
    return JSONResponse({"topics": list(subscription.topics), "ready": subscription.ready})


def event_topic(event_id: int) -> str:
    """What every screen of an event listens to: rounds opening and closing."""
    return f"event:{event_id}"


def votes_topic(event_id: int) -> str:
    """Vote counts, for the band's display and the console only.

    Phones do not subscribe. With five hundred of them in the room, sending
    every vote to every phone is a quarter of a million messages that each one
    throws away.
    """
    return f"votes:{event_id}"
