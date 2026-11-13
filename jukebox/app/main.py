"""Application entrypoint.

One FastAPI app, one process, one SQLite file. The whole of the deployment is
`docker run`; there is no second service to keep alive and nothing writes to a
GitHub repository at runtime.
"""

from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_DIR, Settings, load_settings
from .db import Database, applied_migrations
from .domain.errors import DomainError, NotPermitted
from .domain.identity import LoginThrottle
from .web import admin, band, public
from .web.hub import Hub, LocalHub
from .web.render import redirect
from .web.security import Tokens

log = logging.getLogger("jukebox")


def create_app(
    settings: Settings | None = None,
    *,
    db=None,
    hub: Hub | None = None,
    serve_static: bool = True,
    restore=None,
) -> FastAPI:
    """The app, in a process of its own unless told otherwise.

    The Durable Object (worker/src/entry.py) passes the rest: `db`, its own
    database, already migrated; `hub`, its own sockets (web/hub.py); and
    `serve_static=False`, because Cloudflare serves /static before a request
    reaches it; and `restore`, how it puts its database back to a moment
    (/admin/data/restore). Given a `db`, the app has no lifespan: on the Worker that runs
    once per request, and the object migrates once, when it starts.
    """
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        version = app.state.db.migrate()
        log.info("jukebox ready: db=%s schema=v%s", settings.database_path, version)
        yield
        app.state.db.close()

    app = FastAPI(
        title="Jukebox LIVE",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan if db is None else None,
    )

    app.state.settings = settings
    app.state.db = db if db is not None else Database(settings.database_path)
    app.state.hub = hub or LocalHub()
    app.state.restore = restore
    app.state.tokens = Tokens(settings.secret_key, session_max_age=settings.session_max_age)
    app.state.throttle = LoginThrottle(
        app.state.db,
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )

    if serve_static:
        app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(admin.router)
    app.include_router(band.router)
    app.include_router(public.router)

    # ---------------------------------------------------------- errors --
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        """Domain errors carry text written for a person. Do not rewrite it.

        An unauthenticated browser asking for an admin page is sent to sign in
        rather than shown a 403 it can do nothing about.
        """
        if isinstance(exc, NotPermitted) and request.url.path.startswith("/admin"):
            return redirect("/admin/login", flash=("bad", str(exc)))
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(
                f'<!doctype html><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<link rel="stylesheet" href="/static/app.css">'
                f'<main class="wrap"><h1>Nepovedlo se</h1>'
                f'<div class="notice bad"><p>{html.escape(str(exc))}</p></div>'
                f'<p><a href="/">Zpět na úvod</a></p></main>',
                status_code=exc.status,
            )
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    # -------------------------------------------------------------- ops --
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return PlainTextResponse("ok")

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request):
        """Ready means: the database answers and the schema is current."""
        try:
            conn = request.app.state.db.read()
            version = len(applied_migrations(conn))
            conn.execute("SELECT COUNT(*) FROM songs").fetchone()
        except Exception as exc:  # pragma: no cover - only fires on a broken volume
            return PlainTextResponse(f"not ready: {exc}", status_code=503)
        return PlainTextResponse(f"ready schema=v{version}")

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """Build the ASGI app on first access, not at import.

    `uvicorn app.main:app` resolves this attribute and gets a configured app.
    Importing the module for any other reason -- a test, the CLI, a tool
    reading the routes -- does not, so it does not demand JUKEBOX_SECRET_KEY
    just to be imported.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
