"""The admin console.

Feature parity with the legacy admin page is deliberate and checked item by
item in docs/06-migration-plan.md, gate G5. What is *not* carried over is the
way that page reached into the database from inside its own render: every
mutation here goes through app.domain, so the same rule cannot be enforced two
different ways on two different screens.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Form, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import transfer
from ..domain import ballots, events, identity, log, rounds, songs
from ..domain.errors import DomainError, Invalid, NotFound, NotPermitted
from .deps import get_db, get_settings, get_throttle, get_tokens
from .hub import Subscription, event_topic, get_hub, serve, subscription_response, votes_topic
from .render import fragment, redirect, render
from .security import SESSION_COOKIE, clear_session_cookie, client_address, set_session_cookie

router = APIRouter(prefix="/admin")

# Which buttons the "On air" panel offers, per state. Mirrors
# events.ALLOWED -- the UI never offers a transition the domain would refuse.
TRANSITION_BUTTONS = {
    "draft": [("ready", "Mark ready", "ghost")],
    "ready": [("live", "Put on air", ""), ("draft", "Back to draft", "ghost")],
    "live": [("closed", "Close event", "danger"), ("ready", "Take off air", "ghost")],
    "closed": [("ready", "Reopen", "ghost")],
}


def current_admin(request: Request) -> str:
    user = get_tokens(request).read_session(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise NotPermitted("Please sign in.")
    return user


def _zone(request: Request) -> ZoneInfo:
    """The band's zone, from settings. Never the machine's: the container
    runs in UTC, and 20:00 typed in Ostrava was being stored as 20:00 UTC."""
    return ZoneInfo(get_settings(request).timezone)


def _local(iso: str, zone: ZoneInfo) -> str:
    """Render a UTC timestamp in the band's timezone, for people to read."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return dt.astimezone(zone).strftime("%a %d %b %Y, %H:%M")


def _public_base(request: Request) -> str:
    """Where the audience reaches the app: the configured address if there is
    one, else the address this request arrived on."""
    return get_settings(request).public_url or str(request.base_url).rstrip("/")


# --------------------------------------------------------------- sign in --
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return render(request, "admin/login.html")


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        user = identity.authenticate(
            get_db(request),
            username=username,
            password=password,
            throttle=get_throttle(request),
            client=client_address(request),
        )
    except DomainError as exc:
        return redirect("/admin/login", flash=("bad", str(exc)))

    settings = get_settings(request)
    response = redirect("/admin")
    set_session_cookie(
        response,
        get_tokens(request).make_session(user),
        secure=settings.secure_cookies,
        max_age=settings.session_max_age,
    )
    return response


# ----------------------------------------------------------- first admin --
def _setup_open(request: Request) -> bool:
    """The setup page exists only while it can do something: a token is set,
    and there is no account yet. Otherwise it is not there at all."""
    return bool(get_settings(request).setup_token) and not identity.admin_count(
        get_db(request).read()
    )


@router.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    if not _setup_open(request):
        raise NotFound("There is no such page.")
    return render(request, "admin/setup.html")


@router.post("/setup")
async def setup(
    request: Request,
    token: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    repeat: str = Form(...),
):
    """Make the first account. The token is the deploy's secret, so only
    whoever set it can; wrong tokens count against the sign-in throttle."""
    if not _setup_open(request):
        raise NotFound("There is no such page.")
    throttle, client = get_throttle(request), client_address(request)
    try:
        throttle.check(client)
        if not identity.setup_token_matches(token, get_settings(request).setup_token):
            throttle.record_failure(client)
            raise NotPermitted("That setup token is not right.")
        if password != repeat:
            raise Invalid("The two passwords are not the same.")
        identity.create_admin(get_db(request), username=username, password=password,
                              actor="setup", first=True)
    except DomainError as exc:
        return redirect("/admin/setup", flash=("bad", str(exc)))
    return redirect("/admin/login", flash=("", f"Account {username.strip()} created. Sign in."))


@router.post("/logout")
async def logout():
    response = redirect("/admin/login", flash=("", "Signed out."))
    clear_session_cookie(response)
    return response


# ---------------------------------------------------------------- events --
# How many past events the dashboard shows before asking. There are many more
# gigs than the sample database suggests, and a flat list of all of them is not
# a thing anyone can use at a soundcheck.
PAST_PAGE = 12


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, q: str = "", limit: int = PAST_PAGE):
    """Three groups, not one list: what is on air, what is coming, what is done.

    The old page put every event in one table ordered by date. That reads fine
    with eight events and not at all with sixty.
    """
    user = current_admin(request)
    conn = get_db(request).read()
    zone = _zone(request)

    def decorate(event):
        return {
            "event": event,
            "stats": ballots.event_stats(conn, event.id),
            "starts_local": _local(event.starts_at, zone),
            "rounds": rounds.for_event(conn, event.id),
        }

    everything = events.list_events(conn)
    needle = q.strip().lower()
    if needle:
        everything = [e for e in everything if needle in f"{e.name} {e.venue}".lower()]

    live = next((e for e in everything if e.state == "live"), None)
    upcoming = sorted(
        (e for e in everything if e.state in ("draft", "ready")),
        key=lambda e: e.starts_at,
    )
    past = [e for e in everything if e.state == "closed"]  # already newest-first

    return render(
        request,
        "admin/events.html",
        nav="events",
        admin_user=user,
        query=q,
        live=decorate(live) if live else None,
        live_round=rounds.open_round_of(conn, live.id) if live else None,
        upcoming=[decorate(e) for e in upcoming],
        past=[decorate(e) for e in past[:limit]],
        past_total=len(past),
        past_shown=min(limit, len(past)),
        next_limit=limit + PAST_PAGE,
        song_count=len(songs.list_songs(conn)),
    )


@router.get("/events/new", response_class=HTMLResponse)
async def new_event_form(request: Request):
    """Its own page. On the dashboard this form was permanent clutter."""
    user = current_admin(request)
    conn = get_db(request).read()
    return render(
        request,
        "admin/event_new.html",
        nav="events",
        admin_user=user,
        song_count=len(songs.list_songs(conn)),
        default_start=datetime.now(_zone(request))
        .replace(hour=20, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M"),
    )


@router.post("/events")
async def create_event(
    request: Request,
    name: str = Form(...),
    starts_at: str = Form(...),
    venue: str = Form(""),
    round_count: int = Form(1),
    max_votes: int = Form(5),
):
    user = current_admin(request)
    db = get_db(request)
    # The browser sends local wall-clock time with no zone; read it in the
    # band's zone and store UTC.
    try:
        local = datetime.fromisoformat(starts_at).replace(tzinfo=_zone(request))
        iso = local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return redirect("/admin/events/new", flash=("bad", "That start time is not valid."))

    try:
        event = events.create(
            db,
            name=name,
            starts_at=iso,
            venue=venue,
            round_count=round_count,
            max_votes=max_votes,
            actor=user,
        )
        first = rounds.for_event(db.read(), event.id)[0]
        rounds.assign_all_songs(db, round_id=first.id, actor=user)
    except DomainError as exc:
        return redirect("/admin/events/new", flash=("bad", str(exc)))
    return redirect(f"/admin/events/{event.id}", flash=("", f"Created {event.name}."))


# The console is four tabs over one event, each a real URL so it can be
# bookmarked, opened on a second screen, and reloaded without losing its place.
# It used to be a single page with eight stacked sections, which meant finding
# the stop-voting button by scrolling, in the dark, during a gig.
TABS = [
    ("run", "Run"),
    ("songs", "Songs"),
    ("share", "Share"),
    ("data", "Data"),
]

SONG_FILTERS = {
    "available": "Available",
    "excluded": "Excluded",
    "played": "Played",
    "all": "All",
    # Not part of the round, so not part of the partition the other four form:
    # these are master songs the round does not offer at all.
    "missing": "Not in round",
}


def _console(request: Request, event_id: int, round_id: int | None):
    """Everything the console header needs, whichever tab is showing.

    The header is the same on every tab on purpose: what is on air, which round,
    and how many people are voting should never be more than a glance away.
    """
    # Authenticate before touching the database. Otherwise a signed-out visitor
    # learns which event ids exist from the difference between 404 and a
    # redirect to the sign-in page.
    admin_user = current_admin(request)

    conn = get_db(request).read()
    event = events.get(conn, event_id)
    all_rounds = rounds.for_event(conn, event_id)

    selected = next((r for r in all_rounds if r.id == round_id), None)
    if selected is None:
        # Default to whatever is happening: the open round, else the last one
        # that ran, else the first.
        selected = next((r for r in all_rounds if r.state == "open"), None)
        if selected is None:
            closed = [r for r in all_rounds if r.state == "closed"]
            selected = closed[-1] if closed else all_rounds[0]

    return conn, {
        "nav": "events",
        "admin_user": admin_user,
        "event": event,
        "stamp": log.stamp(conn, event_id),
        # The Run tab's one prominent button is built from these two, not from
        # whichever round happens to be selected: stop what is open, or start
        # what comes next.
        "open_round": next((r for r in all_rounds if r.state == "open"), None),
        "next_pending": next((r for r in all_rounds if r.state == "pending"), None),
        "starts_local": _local(event.starts_at, _zone(request)),
        "transitions": TRANSITION_BUTTONS[event.state],
        "tabs": TABS,
        "selected": selected,
        "next_round": any(r.ordinal == selected.ordinal + 1 for r in all_rounds),
        "round_rows": [
            {
                "round": r,
                "stats": ballots.round_stats(conn, r.id),
                "votable": len(rounds.votable_songs(conn, r.id)),
            }
            for r in all_rounds
        ],
        "event_stats": ballots.event_stats(conn, event_id),
        # Surfaced on the tab itself, so a song added to the master list
        # mid-gig is visible without opening the tab to look for it.
        "missing_count": len(rounds.songs_not_in_round(conn, selected.id)),
    }


@router.get("/events/{event_id}", response_class=HTMLResponse)
async def event_console(
    request: Request,
    event_id: int,
    tab: str = "run",
    round: int | None = None,
    filter: str = "available",
    q: str = "",
):
    if tab not in dict(TABS):
        tab = "run"
    conn, context = _console(request, event_id, round)
    selected = context["selected"]
    event = context["event"]

    if tab == "run":
        context |= {
            "tally": ballots.tally(conn, selected.id),
            "stats": ballots.round_stats(conn, selected.id),
        }

    elif tab == "songs":
        if filter not in SONG_FILTERS:
            filter = "available"
        needle = q.strip().lower()

        def matches(title: str, artist: str) -> bool:
            return not needle or needle in f"{title} {artist}".lower()

        board = [
            s for s in rounds.song_board(conn, selected.id)
            if matches(s["title"], s["artist"])
        ]
        missing = [
            {"id": r["id"], "title": r["title"], "artist": r["artist"],
             "status": "missing", "votes": 0}
            for r in rounds.songs_not_in_round(conn, selected.id)
            if matches(r["title"], r["artist"])
        ]

        by_status = {"available": "open", "excluded": "excluded", "played": "played"}
        context |= {
            "filters": SONG_FILTERS,
            "active_filter": filter,
            "query": q,
            "counts": {
                "available": sum(1 for s in board if s["status"] == "open"),
                "excluded": sum(1 for s in board if s["status"] == "excluded"),
                "played": sum(1 for s in board if s["status"] == "played"),
                "all": len(board),
                "missing": len(missing),
            },
            "board": (
                missing if filter == "missing"
                else board if filter == "all"
                else [s for s in board if s["status"] == by_status[filter]]
            ),
        }

    elif tab == "share":
        base = _public_base(request)
        context |= {
            "public_url": f"{base}/e/{event.slug}",
            "band_url": f"{base}/band/{get_tokens(request).make_band_token(event_id)}",
            "notes": events.band_notes(conn, event_id),
        }

    elif tab == "data":
        context |= {"log": log.for_event(conn, event_id, limit=100)}

    context["tab"] = tab
    return render(request, "admin/event.html", **context)


@router.get("/events/{event_id}/live", response_class=HTMLResponse)
async def event_live(event_id: int, request: Request, round: int | None = None):
    """Re-rendered in place as votes land. No page reload, no lost scroll."""
    conn, context = _console(request, event_id, round)
    selected = context["selected"]
    return fragment(
        "admin/_live.html",
        tally=ballots.tally(conn, selected.id),
        stats=ballots.round_stats(conn, selected.id),
        selected=selected,
    )


@router.post("/events/{event_id}/state")
async def event_state(event_id: int, request: Request, to: str = Form(...)):
    user = current_admin(request)
    try:
        events.transition(get_db(request), event_id=event_id, to=to, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}", flash=("bad", str(exc)))
    # Everyone holding this event's page needs the new shape of it.
    get_hub(request).publish(event_topic(event_id), kind="event", reload=True)
    return redirect(f"/admin/events/{event_id}")


@router.post("/events/{event_id}/rounds")
async def add_round(event_id: int, request: Request):
    user = current_admin(request)
    try:
        rnd = rounds.add_round(get_db(request), event_id=event_id, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}?tab=run", flash=("bad", str(exc)))
    return redirect(
        f"/admin/events/{event_id}?tab=songs&round={rnd.id}",
        flash=("", f"Round {rnd.ordinal} added, with the unplayed songs carried over."),
    )


@router.post("/events/{event_id}/notes")
async def save_notes(event_id: int, request: Request, body: str = Form("")):
    user = current_admin(request)
    events.update_band_notes(get_db(request), event_id=event_id, body=body, actor=user)
    get_hub(request).publish(event_topic(event_id), kind="notes")
    return redirect(f"/admin/events/{event_id}?tab=share", flash=("", "Notes saved."))


@router.post("/events/{event_id}/delete")
async def delete_event(event_id: int, request: Request):
    user = current_admin(request)
    try:
        events.delete(get_db(request), event_id=event_id, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}", flash=("bad", str(exc)))
    return redirect("/admin", flash=("", "Event deleted."))


# ---------------------------------------------------------------- rounds --
@router.post("/rounds/{round_id}/state")
async def round_state(round_id: int, request: Request, to: str = Form(...), tab: str = Form("run")):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    back = f"/admin/events/{rnd.event_id}?tab={tab}&round={round_id}"
    try:
        rounds.transition(db, round_id=round_id, to=to, actor=user)
    except DomainError as exc:
        return redirect(back, flash=("bad", str(exc)))
    # Opening or closing a round changes what every attendee's page should be,
    # so this one does force a reload on their side.
    get_hub(request).publish(event_topic(rnd.event_id), kind="round", reload=True)
    return redirect(back)


@router.post("/rounds/{round_id}/max-votes")
async def round_max_votes(round_id: int, request: Request, max_votes: int = Form(...)):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    back = f"/admin/events/{rnd.event_id}?tab=run&round={round_id}"
    try:
        rounds.set_max_votes(db, round_id=round_id, max_votes=max_votes, actor=user)
    except DomainError as exc:
        return redirect(back, flash=("bad", str(exc)))
    return redirect(back)


@router.post("/rounds/{round_id}/carry-forward")
async def carry_forward(round_id: int, request: Request):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    back = f"/admin/events/{rnd.event_id}?tab=songs&round={round_id}"
    try:
        moved = rounds.carry_forward(db, from_round=round_id, actor=user)
    except DomainError as exc:
        return redirect(back, flash=("bad", str(exc)))
    return redirect(back, flash=("", f"{moved} song(s) carried into round {rnd.ordinal + 1}."))


@router.post("/rounds/{round_id}/songs")
async def round_songs(
    round_id: int,
    request: Request,
    action: str = Form(""),
    song_ids: list[int] = Form(default_factory=list),
    filter: str = Form("available"),
    q: str = Form(""),
):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    # Return to exactly the view the action was fired from -- same tab, same
    # filter, same search -- so a bulk edit does not throw away where you were.
    back = (
        f"/admin/events/{rnd.event_id}?tab=songs&round={round_id}"
        f"&filter={quote(filter or 'available')}"
        f"&q={quote(q)}"
    )

    if action == "add_all":
        # No selection needed: put every master song the round lacks into it.
        missing = [r["id"] for r in rounds.songs_not_in_round(db.read(), round_id)]
        if not missing:
            return redirect(back, flash=("", "This round already has every song."))
        try:
            added = rounds.add_songs(db, round_id=round_id, song_ids=missing, actor=user)
        except DomainError as exc:
            return redirect(back, flash=("bad", str(exc)))
        get_hub(request).publish(event_topic(rnd.event_id), kind="songs", reload=True)
        return redirect(back, flash=("", f"{added} song(s) added to round {rnd.ordinal}."))

    if not song_ids:
        return redirect(back, flash=("warn", "Select some songs first."))

    try:
        if action == "add":
            n = rounds.add_songs(db, round_id=round_id, song_ids=song_ids, actor=user)
            message = f"{n} song(s) added to round {rnd.ordinal}."
            if rnd.state == "open":
                message += " Everyone's ballot has been refreshed."
        elif action == "exclude":
            n = rounds.set_excluded(db, round_id=round_id, song_ids=song_ids, excluded=True, actor=user)
            message = f"{n} song(s) excluded from round {rnd.ordinal}."
        elif action == "include":
            n = rounds.set_excluded(db, round_id=round_id, song_ids=song_ids, excluded=False, actor=user)
            message = f"{n} song(s) put back."
        elif action == "played":
            n = rounds.set_played(db, round_id=round_id, song_ids=song_ids, played=True, actor=user)
            message = f"{n} song(s) marked as played."
        elif action == "unplayed":
            n = rounds.set_played(db, round_id=round_id, song_ids=song_ids, played=False, actor=user)
            message = f"{n} song(s) un-marked."
        else:
            return redirect(back, flash=("bad", "Unknown action."))
    except DomainError as exc:
        return redirect(back, flash=("bad", str(exc)))

    get_hub(request).publish(event_topic(rnd.event_id), kind="songs", reload=True)
    return redirect(back, flash=("", message))


# ----------------------------------------------------------------- songs --
@router.get("/songs", response_class=HTMLResponse)
async def song_list(request: Request, q: str = "", show: str = "active"):
    """The master list, searchable.

    The catalogue is several hundred songs, not the hundred-odd in the sample
    database, so a flat unfiltered table is not usable.
    """
    user = current_admin(request)
    conn = get_db(request).read()
    everything = songs.list_songs(conn, include_retired=True)

    active = [s for s in everything if not s.retired]
    retired = [s for s in everything if s.retired]
    shown = retired if show == "retired" else active

    needle = q.strip().lower()
    if needle:
        shown = [s for s in shown if needle in f"{s.title} {s.artist}".lower()]

    return render(
        request,
        "admin/songs.html",
        nav="songs",
        admin_user=user,
        query=q,
        show=show,
        shown=shown,
        active_count=len(active),
        retired_count=len(retired),
    )


def _live_round_link(request: Request) -> tuple[str, str] | None:
    """Where to go to put a new song on the ballot, if a gig is happening.

    Adding to the master list does not add to a round -- rounds own their own
    lists. Mid-gig that distinction costs a song, so say it where it matters
    and link straight to the screen that fixes it.
    """
    conn = get_db(request).read()
    event = events.live_event(conn)
    if event is None:
        return None
    all_rounds = rounds.for_event(conn, event.id)
    target = next((r for r in all_rounds if r.state == "open"), None)
    if target is None:
        target = next((r for r in all_rounds if r.state == "pending"), None)
    if target is None:
        return None
    return (
        f"/admin/events/{event.id}?tab=songs&round={target.id}&filter=missing",
        f"Add to round {target.ordinal}",
    )


@router.post("/songs")
async def add_song(request: Request, title: str = Form(...), artist: str = Form(...)):
    user = current_admin(request)
    try:
        songs.add(get_db(request), title=title, artist=artist, actor=user)
    except DomainError as exc:
        return redirect("/admin/songs", flash=("bad", str(exc)))

    link = _live_round_link(request)
    if link is None:
        return redirect("/admin/songs", flash=("", f"Added {title}."))
    return redirect(
        "/admin/songs",
        flash=("warn", f"Added {title}. It is not on the ballot yet.", *link),
    )


@router.post("/songs/import")
async def import_songs(request: Request, file: UploadFile):
    user = current_admin(request)
    raw = file.file.read()
    try:
        report = songs.import_csv(get_db(request), raw, actor=user)
    except DomainError as exc:
        return redirect("/admin/songs", flash=("bad", str(exc)))

    parts = [f"{report.added} added"]
    if report.restored:
        parts.append(f"{report.restored} restored")
    if report.duplicates:
        parts.append(f"{report.duplicates} already there")
    if report.skipped:
        parts.append(f"{len(report.skipped)} skipped ({report.skipped[0]})")
    summary = ", ".join(parts) + "."

    link = _live_round_link(request) if (report.added or report.restored) else None
    if link is None:
        return redirect("/admin/songs", flash=("", summary))
    return redirect(
        "/admin/songs",
        flash=("warn", f"{summary} New songs are not on the ballot yet.", *link),
    )


@router.post("/songs/{song_id}/retire")
async def retire_song(song_id: int, request: Request):
    user = current_admin(request)
    songs.set_retired(get_db(request), song_id=song_id, retired=True, actor=user)
    return redirect("/admin/songs")


@router.post("/songs/{song_id}/restore")
async def restore_song(song_id: int, request: Request):
    user = current_admin(request)
    songs.set_retired(get_db(request), song_id=song_id, retired=False, actor=user)
    return redirect("/admin/songs")


@router.get("/songs/export.csv")
async def export_songs(request: Request):
    current_admin(request)
    rows = songs.list_songs(get_db(request).read(), include_retired=True)
    return _csv(
        "songs.csv",
        ["id", "title", "artist", "retired"],
        [[s.id, s.title, s.artist, "yes" if s.retired else ""] for s in rows],
    )


# --------------------------------------------------------------- exports --
def _plain(cell):
    """Keep a spreadsheet from running a cell as a formula.

    Voter names are typed by strangers and end up in a file the band opens in
    Excel, where a cell that starts with = + - or @ is code. A leading
    apostrophe makes it text again.
    """
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + cell
    return cell


def _csv(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows([_plain(cell) for cell in row] for row in rows)
    # BOM so Excel on a Czech Windows machine opens it as UTF-8 rather than
    # mangling every accented character.
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/events/{event_id}/export.csv")
async def export_votes(event_id: int, request: Request):
    current_admin(request)
    conn = get_db(request).read()
    event = events.get(conn, event_id)
    rows = conn.execute(
        "SELECT r.ordinal, vo.display_name, s.artist, s.title, v.cast_at"
        " FROM votes v"
        " JOIN rounds r ON r.id = v.round_id"
        " JOIN voters vo ON vo.id = v.voter_id"
        " JOIN songs s ON s.id = v.song_id"
        " WHERE r.event_id = ? ORDER BY r.ordinal, vo.display_name, s.artist",
        (event_id,),
    ).fetchall()
    return _csv(
        f"jukebox-{event.slug}-votes.csv",
        ["round", "voter", "artist", "title", "cast_at"],
        [list(r) for r in rows],
    )


@router.get("/events/{event_id}/results.csv")
async def export_results(event_id: int, request: Request):
    current_admin(request)
    conn = get_db(request).read()
    event = events.get(conn, event_id)
    rows = ballots.event_tally(conn, event_id)
    return _csv(
        f"jukebox-{event.slug}-results.csv",
        ["rank", "artist", "title", "votes"],
        [[i, r["artist"], r["title"], r["votes"]] for i, r in enumerate(rows, start=1)],
    )


# ------------------------------------------------------------ all data --
@router.get("/data/export.json")
async def export_everything(request: Request):
    """Every song, event, vote and log row, as one file (app/transfer.py).

    On the Worker this is the copy in your hand that `cli backup` is in the
    container, and what gate G2 is run on after an import.
    """
    current_admin(request)
    body = json.dumps(transfer.dump(get_db(request).read()), ensure_ascii=False)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="jukebox-live-export.json"'},
    )


@router.post("/data/import")
async def import_everything(request: Request, file: UploadFile):
    """Fill an empty app from an export, in one transaction (docs/08, step 7.1)."""
    user = current_admin(request)
    try:
        data = json.loads(file.file.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return JSONResponse({"error": "That file is not JSON."}, status_code=400)
    try:
        counts = transfer.load(get_db(request), data, actor=user)
    except DomainError as exc:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)
    return JSONResponse({"imported": counts})


# Cloudflare keeps every moment of the object's database this far back.
RESTORE_DAYS = 30


@router.post("/data/restore")
async def restore_to(request: Request, at: str = Form(...)):
    """Put the whole database back as it was at `at`, in the band's time.

    Point-in-time recovery. Cloudflare keeps the object's database at every
    moment of the last 30 days, but only the object can ask for one, so this
    is the button (docs/08, step 7.2). Everything after `at` goes, events,
    votes and accounts alike; the object restarts, and every screen
    reconnects and reloads. Pull a copy first (scripts/transfer.py restore
    does). Only on the Worker: the container's database is a file.
    """
    current_admin(request)
    restore = request.app.state.restore
    if restore is None:
        return JSONResponse({"error": "Restoring to a moment needs the Worker; this copy keeps "
                                      "its database in a file."}, status_code=501)
    try:
        moment = datetime.fromisoformat(at)
    except ValueError:
        return JSONResponse({"error": f"{at!r} is not a date and time."}, status_code=400)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_zone(request))
    moment = moment.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if not now - timedelta(days=RESTORE_DAYS) < moment < now:
        return JSONResponse({"error": f"Pick a moment in the last {RESTORE_DAYS} days."},
                            status_code=400)
    try:
        await restore(moment.timestamp() * 1000)
    except Exception as exc:  # Cloudflare's refusal, word for word (none locally)
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"restoring_to": moment.isoformat().replace("+00:00", "Z")})


@router.get("/events/{event_id}/qr.svg")
async def event_qr(event_id: int, request: Request):
    """The QR code for the table cards. Nobody types a URL in the dark."""
    current_admin(request)
    event = events.get(get_db(request).read(), event_id)
    url = f"{_public_base(request)}/e/{event.slug}"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buffer = io.BytesIO()
    img.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")


def _console_subscription(conn, event_id: int) -> Subscription:
    current_admin(conn)
    stamp = log.stamp(get_db(conn).read(), event_id)
    return Subscription((event_topic(event_id), votes_topic(event_id)), {"stamp": stamp})


@router.websocket("/events/{event_id}/stream")
async def admin_stream_socket(ws: WebSocket, event_id: int):
    await serve(ws, lambda: _console_subscription(ws, event_id))


@router.get("/events/{event_id}/stream")
async def admin_stream(event_id: int, request: Request):
    return subscription_response(request, _console_subscription(request, event_id))
