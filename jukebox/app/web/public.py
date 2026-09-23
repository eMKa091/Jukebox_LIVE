"""Attendee-facing routes.

The whole journey is four states, and which one a visitor sees is decided by
the server from the database on every request. Nothing depends on a websocket
session variable, which is what made the legacy "have I voted?" check evaporate
on refresh (F6).

    no live event            -> splash
    live, no name yet        -> join
    live, round open, unvoted-> ballot
    live, round open, voted  -> receipt
    live, no round open      -> standings
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ..domain import ballots, events, rounds, songs
from ..domain.errors import DomainError
from .deps import get_db, get_settings
from .hub import event_topic, hub
from .render import redirect, render
from .security import device_token, ensure_device_cookie

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    db = get_db(request)
    event = events.live_event(db.read())
    if event is None:
        return _splash(request, "Aktuálně neprobíhá žádné hlasování.")
    return redirect(f"/e/{event.slug}")


def _splash(request: Request, message: str) -> HTMLResponse:
    db = get_db(request)
    return render(
        request,
        "splash.html",
        message=message,
        repertoire=songs.list_songs(db.read()),
    )


@router.get("/e/{slug}", response_class=HTMLResponse)
def event_page(slug: str, request: Request):
    db = get_db(request)
    settings = get_settings(request)
    conn = db.read()

    try:
        event = events.by_slug(conn, slug)
    except DomainError:
        return _splash(request, "Tenhle odkaz už neplatí.")

    if event.state != "live":
        return _splash(request, "Aktuálně neprobíhá žádné hlasování.")

    token = device_token(request)
    voter = ballots.voter_in_event(conn, event_id=event.id, device_token=token)
    open_round = rounds.open_round_of(conn, event.id)

    if voter is None:
        response = render(request, "join.html", event=event, display_name=None)
        ensure_device_cookie(response, token, secure=settings.secure_cookies)
        return response

    if open_round is None:
        # Between rounds: show where things stand rather than a dead end.
        last = [r for r in rounds.for_event(conn, event.id) if r.state == "closed"]
        response = render(
            request,
            "closed.html",
            event=event,
            heading="Kolo právě skončilo",
            message="Kapela teď hraje. Další kolo otevřeme za chvíli.",
            tally=ballots.tally(conn, last[-1].id)[:10] if last else [],
        )
        ensure_device_cookie(response, token, secure=settings.secure_cookies)
        return response

    already = ballots.submitted_songs(conn, round_id=open_round.id, voter_id=voter["id"])
    if already:
        response = render(
            request,
            "voted.html",
            event=event,
            round=open_round,
            voter_name=voter["display_name"],
            songs=ballots.titles(conn, already),
        )
    else:
        response = render(
            request,
            "ballot.html",
            event=event,
            round=open_round,
            voter_name=voter["display_name"],
            songs=rounds.votable_songs(conn, open_round.id),
        )
    ensure_device_cookie(response, token, secure=settings.secure_cookies)
    return response


@router.post("/e/{slug}/join")
def join(slug: str, request: Request, display_name: str = Form(...)):
    db = get_db(request)
    settings = get_settings(request)
    event = events.by_slug(db.read(), slug)
    token = device_token(request)

    try:
        ballots.voter_for_device(
            db, event_id=event.id, device_token=token, display_name=display_name
        )
    except DomainError as exc:
        response = redirect(f"/e/{slug}", flash=("bad", str(exc)))
        ensure_device_cookie(response, token, secure=settings.secure_cookies)
        return response

    response = redirect(f"/e/{slug}")
    ensure_device_cookie(response, token, secure=settings.secure_cookies)
    return response


@router.post("/e/{slug}/ballot")
async def cast_ballot(slug: str, request: Request):
    db = get_db(request)
    conn = db.read()
    event = events.by_slug(conn, slug)

    form = await request.form()
    ballot_id = str(form.get("ballot_id") or "")
    try:
        round_id = int(form.get("round_id") or 0)
        song_ids = [int(v) for v in form.getlist("song_ids")]
    except ValueError:
        return redirect(f"/e/{slug}", flash=("bad", "Neplatný formulář, zkus to prosím znovu."))

    token = device_token(request)
    voter = ballots.voter_in_event(conn, event_id=event.id, device_token=token)
    if voter is None:
        return redirect(f"/e/{slug}", flash=("bad", "Zadej prosím nejdřív své jméno."))

    try:
        ballots.submit(
            db,
            round_id=round_id,
            voter_id=voter["id"],
            song_ids=song_ids,
            ballot_id=ballot_id,
        )
    except DomainError as exc:
        return redirect(f"/e/{slug}", flash=("bad", str(exc)))

    # Tell the band's display and the admin console, not the other attendees:
    # a vote count changing under someone's ballot is noise.
    hub.publish(event_topic(event.id), kind="votes")
    return redirect(f"/e/{slug}")


@router.get("/e/{slug}/stream")
async def stream(slug: str, request: Request):
    """Live updates for attendees.

    Only round transitions reach this stream with reload=True; individual votes
    do not, so a phone mid-ballot is never yanked out from under its owner.
    """
    event = events.by_slug(get_db(request).read(), slug)
    return StreamingResponse(
        hub.stream(event_topic(event.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
