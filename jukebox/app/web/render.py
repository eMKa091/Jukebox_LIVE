"""Template rendering, plus one-shot flash messages.

Flashes ride in a short-lived cookie rather than a server-side session, so the
app keeps no per-user state in memory and a restart mid-evening logs nobody out
of anything. The cookie is cleared as it is read.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import APP_DIR

FLASH_COOKIE = "jb_flash"

env = Environment(
    loader=FileSystemLoader(APP_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Busts the browser cache for CSS and JS on deploy without hashing filenames.
# Set to the release version in production; the import time is fine locally.
import time as _time

ASSET_VERSION = str(int(_time.time()))


def take_flashes(request: Request) -> list[tuple[str, str]]:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return []
    try:
        return [(kind, text) for kind, text in json.loads(unquote(raw))]
    except (ValueError, TypeError):
        return []


def render(
    request: Request,
    template: str,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    flashes = take_flashes(request)
    html = env.get_template(template).render(
        request=request,
        flashes=flashes,
        asset_version=ASSET_VERSION,
        **context,
    )
    response = HTMLResponse(html, status_code=status_code)
    if flashes:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def fragment(template: str, **context: Any) -> HTMLResponse:
    """Render a partial for the client's data-refresh swap. No chrome."""
    return HTMLResponse(
        env.get_template(template).render(asset_version=ASSET_VERSION, **context)
    )


def redirect(url: str, *, flash: tuple[str, str] | None = None, status_code: int = 303) -> RedirectResponse:
    """POST-redirect-GET, optionally carrying one message across."""
    response = RedirectResponse(url, status_code=status_code)
    if flash is not None:
        set_flash(response, *flash)
    return response


def set_flash(response: Response, kind: str, message: str) -> None:
    # Percent-encoded, because cookie values travel in a Set-Cookie header and
    # headers are latin-1. Every attendee-facing message here is Czech, so
    # "Vyber prosím alespoň jednu píseň" would otherwise raise
    # UnicodeEncodeError on the way out -- on an error path, where the user is
    # already having a bad time.
    response.set_cookie(
        FLASH_COOKIE,
        quote(json.dumps([[kind, message]], ensure_ascii=False)),
        max_age=30,
        httponly=True,
        samesite="lax",
        path="/",
    )
