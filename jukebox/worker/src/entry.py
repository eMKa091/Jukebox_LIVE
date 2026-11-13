"""Jukebox LIVE as a Cloudflare Worker (docs/08-cloudflare-port.md, step 5).

Two classes, one program:

  * `Default`, the entry Worker. Cloudflare has already answered /static/*
    from the assets; everything else goes to the one object.
  * `Jukebox`, the Durable Object. It holds the SQLite database, runs the
    FastAPI app against it, and holds every live screen's WebSocket, asleep
    between messages.

The app is the same one the tests run (../app, copied in by build.py); only
its database (app/db_durable.py) and its hub (app/web/hub.py, SocketHub) are
the object's own.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from workers import DurableObject, Response, WorkerEntrypoint, asgi

# The one object. A name, not an id, so every request finds the same one.
OBJECT_NAME = "jukebox"


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        namespace = self.env.JUKEBOX
        # "eu" on Cloudflare (wrangler.jsonc), where the band and its audience
        # are; it cannot be changed later without moving the data. Empty in
        # local runs, which do not implement jurisdictions.
        jurisdiction = getattr(self.env, "JUKEBOX_JURISDICTION", "")
        if jurisdiction:
            namespace = namespace.jurisdiction(jurisdiction)
        return await namespace.getByName(OBJECT_NAME).fetch(request)


def _settings_env(env) -> dict[str, str]:
    """The Worker's vars and secrets as the mapping load_settings reads."""
    from app.config import SETTINGS_KEYS

    out: dict[str, str] = {}
    for key in SETTINGS_KEYS:
        value = getattr(env, key, None)
        if isinstance(value, str):
            out[key] = value
    return out


class Jukebox(DurableObject):
    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        from js import WebSocketRequestResponsePair

        from app.config import load_settings
        from app.db_durable import DurableDatabase
        from app.main import create_app
        from app.web.hub import PING, PONG, SocketHub

        # Runs whenever the object starts, which includes waking from sleep.
        # Migrating is then one read of schema_migrations.
        db = DurableDatabase(ctx.storage)
        db.migrate()
        self.hub = SocketHub(ctx)
        self.app = create_app(load_settings(_settings_env(env)), db=db, hub=self.hub,
                              serve_static=False, restore=self._restore)
        # Pings are answered by the runtime itself, so a room full of phones
        # keeping their connections alive does not wake the object.
        ctx.setWebSocketAutoResponse(WebSocketRequestResponsePair.new(PING, PONG))

    async def fetch(self, request):
        if (request.headers.get("upgrade") or "").lower() == "websocket":
            return await self._accept(request)
        return await asgi.fetch(self.app, request, self.env)

    async def _accept(self, request):
        """Accept a screen's WebSocket, if its route says yes.

        The route is asked over plain HTTP (hub.subscription_response): which
        topics this screen may hear, and the stamp its first message carries.
        A refusal goes back as the route's own answer, so the handshake fails
        and the browser tries again later.
        """
        from js import WebSocketPair
        from pyodide.ffi import to_js

        from app.web.hub import Subscription

        answer = await asgi.fetch(self.app, request, self.env)
        if answer.status != 200:
            return answer
        granted = json.loads(await answer.text())
        subscription = Subscription(tuple(granted["topics"]), granted["ready"])

        client, server = WebSocketPair.new().object_values()
        self.ctx.acceptWebSocket(server, to_js(list(subscription.topics)))
        server.send(self.hub.ready(subscription))
        return Response(None, status=101, web_socket=client)

    async def _restore(self, at_ms: float) -> None:
        """Point-in-time recovery: the database as it was at `at_ms`.

        It takes effect when the object next starts, so the object stops
        itself just after the answer has gone out (docs/08, step 7.2).
        """
        bookmark = await self.ctx.storage.getBookmarkForTime(at_ms)
        await self.ctx.storage.onNextSessionRestoreBookmark(bookmark)
        asyncio.ensure_future(self._stop_soon())

    async def _stop_soon(self) -> None:
        await asyncio.sleep(0.5)
        with suppress(BaseException):  # abort() raises to end this task
            self.ctx.abort("restoring to an earlier moment")

    async def webSocketMessage(self, ws, message):
        """Nothing to do: screens only listen, and pings never get here."""

    async def webSocketClose(self, ws, code, reason, was_clean):
        # Answer the close, or the browser waits out its timeout (docs/08, U8).
        # 1005 and 1006 are reports, not codes anyone may send.
        with suppress(Exception):
            ws.close(1000 if code in (1005, 1006) else code, "closing")

    async def webSocketError(self, ws, error):
        with suppress(Exception):
            ws.close(1011, "error")
