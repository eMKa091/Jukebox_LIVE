"""In-process publish/subscribe for Server-Sent Events.

When the admin opens a round, two hundred phones need to find out without being
told to refresh. The legacy app had no mechanism for this at all -- attendees
reloaded and hoped.

One container, one process, so the fan-out is a set of asyncio queues rather
than Redis or a message broker. If this ever runs on more than one machine the
same interface can be backed by a real bus; nothing above this module would
change.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

# How long a stream waits before sending a keepalive comment. Proxies and
# mobile networks drop connections that go quiet; 20 seconds is comfortably
# under the usual 30-60 second idle timeouts.
KEEPALIVE_SECONDS = 20

# Bounded, so one stalled client cannot grow a queue without limit. If a client
# falls this far behind it is dropped and its browser reconnects, which
# re-syncs it from scratch anyway.
QUEUE_SIZE = 32


class _Subscriber:
    """One open stream: its queue, and whether the hub has given up on it."""

    __slots__ = ("queue", "dropped")

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.dropped = False


class Hub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[_Subscriber]] = defaultdict(set)
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def publish(self, topic: str, **payload) -> None:
        """Announce that something under `topic` changed.

        The payload is deliberately thin: a version stamp and what changed. The
        client responds by re-fetching the fragment it cares about, so there is
        exactly one renderer for every piece of UI -- the server -- and no
        client-side copy of the state to drift.
        """
        self._version += 1
        message = json.dumps({"v": self._version, **payload}, ensure_ascii=False)
        # Handlers run on the event loop itself (docs/08, step 3), so the
        # queues can be woken directly.
        self._deliver(topic, message)

    def _deliver(self, topic: str, message: str) -> None:
        for subscriber in list(self._subscribers.get(topic, ())):
            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the slow subscriber. Marking it is what ends its stream:
                # the connection closes, the browser reconnects, and the first
                # frame it gets back tells it whether it missed anything.
                subscriber.dropped = True

    async def stream(self, *topics: str, ready: dict | None = None) -> AsyncIterator[str]:
        """Yield SSE frames for one subscriber until it disconnects.

        `ready` rides on the first frame. The routes put the event's state
        stamp in it, so a browser that was away -- a locked phone, a dropped
        connection, a restarted server -- can tell on reconnect that the page
        it is showing is out of date. Nothing is replayed; the page is simply
        fetched again.
        """
        subscriber = _Subscriber()
        for topic in topics:
            self._subscribers[topic].add(subscriber)
        try:
            yield _frame("ready", json.dumps({"v": self._version, **(ready or {})}))
            while not subscriber.dropped:
                try:
                    message = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _frame("update", message)
        finally:
            for topic in topics:
                self._subscribers[topic].discard(subscriber)
                if not self._subscribers[topic]:
                    self._subscribers.pop(topic, None)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


def _frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def event_topic(event_id: int) -> str:
    """What every screen of an event listens to: rounds opening and closing."""
    return f"event:{event_id}"


def votes_topic(event_id: int) -> str:
    """Vote counts, for the band's display and the console only.

    Phones do not subscribe. With five hundred of them in the room, sending
    every vote to every phone is a quarter of a million frames that each one
    throws away.
    """
    return f"event:{event_id}:votes"


def stream_response(*topics: str, ready: dict | None = None) -> StreamingResponse:
    return StreamingResponse(
        hub.stream(*topics, ready=ready),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


hub = Hub()
