"""The band's display.

A signed link rather than a password: the tablet on stage should open in one
tap, but the setlist must not be readable by anyone who guesses a query string
the way `?admin=Band` could be (F3).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ..domain import ballots, events, rounds
from ..domain.errors import NotPermitted
from .deps import get_db, get_tokens
from .hub import event_topic, hub
from .render import fragment, render

router = APIRouter(prefix="/band")


def _resolve(request: Request, token: str):
    event_id = get_tokens(request).read_band_token(token)
    if event_id is None:
        raise NotPermitted("That band link is not valid.")
    return events.get(get_db(request).read(), event_id)


def _live_context(request: Request, event) -> dict:
    conn = get_db(request).read()
    all_rounds = rounds.for_event(conn, event.id)
    current = next((r for r in all_rounds if r.state == "open"), None)
    if current is None:
        closed = [r for r in all_rounds if r.state == "closed"]
        current = closed[-1] if closed else None

    played = conn.execute(
        "SELECT s.title, s.artist, rs.played_at FROM round_songs rs"
        " JOIN songs s ON s.id = rs.song_id"
        " JOIN rounds r ON r.id = rs.round_id"
        " WHERE r.event_id = ? AND rs.played_at IS NOT NULL"
        " GROUP BY s.id ORDER BY rs.played_at",
        (event.id,),
    ).fetchall()

    return {
        "event": event,
        "round": current,
        "tally": ballots.tally(conn, current.id) if current else [],
        "played": played,
        "notes": events.band_notes(conn, event.id),
        "stats": ballots.event_stats(conn, event.id),
    }


@router.get("/{token}", response_class=HTMLResponse)
def display(token: str, request: Request):
    event = _resolve(request, token)
    return render(request, "band.html", token=token, **_live_context(request, event))


@router.get("/{token}/live", response_class=HTMLResponse)
def live_fragment(token: str, request: Request):
    """Re-rendered in place whenever a vote lands. No page reload."""
    event = _resolve(request, token)
    return fragment("_band_live.html", **_live_context(request, event))


@router.get("/{token}/stream")
async def stream(token: str, request: Request):
    event = _resolve(request, token)
    return StreamingResponse(
        hub.stream(event_topic(event.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
