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
from contextlib import suppress

# How long a stream waits before sending a keepalive comment. Proxies and
# mobile networks drop connections that go quiet; 20 seconds is comfortably
# under the usual 30-60 second idle timeouts.
KEEPALIVE_SECONDS = 20

# Bounded, so one stalled client cannot grow a queue without limit. If a client
# falls this far behind it is dropped and its browser reconnects, which
# re-syncs it from scratch anyway.
QUEUE_SIZE = 32


class Hub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._version = 0

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the event loop, so sync request handlers can publish.

        Endpoint functions that touch SQLite are sync and run in Starlette's
        threadpool. Waking a queue from there has to hop back onto the loop
        thread, which is what call_soon_threadsafe below does.
        """
        self._loop = loop

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
        loop = self._loop
        if loop is None:  # not running inside the app (tests, scripts)
            self._deliver(topic, message)
            return
        with suppress(RuntimeError):  # loop closed during shutdown
            loop.call_soon_threadsafe(self._deliver, topic, message)

    def _deliver(self, topic: str, message: str) -> None:
        for queue in list(self._subscribers.get(topic, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the slow subscriber. Its browser will reconnect and get
                # a fresh snapshot, which is more correct than a stale backlog.
                self._subscribers[topic].discard(queue)

    async def stream(self, topic: str) -> AsyncIterator[str]:
        """Yield SSE frames for one subscriber until it disconnects."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers[topic].add(queue)
        try:
            # An immediate frame so the client knows the stream is live and
            # renders from current state rather than waiting for the first
            # change.
            yield _frame("ready", json.dumps({"v": self._version}))
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _frame("update", message)
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


def _frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def event_topic(event_id: int) -> str:
    return f"event:{event_id}"


hub = Hub()
