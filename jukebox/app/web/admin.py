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
from datetime import datetime, timezone

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse

from ..domain import ballots, events, identity, log, rounds, songs
from ..domain.errors import DomainError, NotPermitted
from .deps import get_db, get_settings, get_throttle, get_tokens
from .hub import event_topic, hub
from .render import fragment, redirect, render
from .security import SESSION_COOKIE, clear_session_cookie, set_session_cookie

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


def _local(iso: str) -> str:
    """Render a UTC timestamp in the band's timezone, for people to read."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return dt.astimezone().strftime("%a %d %b %Y, %H:%M")


# --------------------------------------------------------------- sign in --
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "admin/login.html")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        user = identity.authenticate(
            get_db(request),
            username=username,
            password=password,
            throttle=get_throttle(request),
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


@router.post("/logout")
def logout():
    response = redirect("/admin/login", flash=("", "Signed out."))
    clear_session_cookie(response)
    return response


# ---------------------------------------------------------------- events --
@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_admin(request)
    conn = get_db(request).read()
    rows = [
        {
            "event": e,
            "stats": ballots.event_stats(conn, e.id),
            "starts_local": _local(e.starts_at),
        }
        for e in events.list_events(conn)
    ]
    return render(
        request,
        "admin/events.html",
        nav="events",
        admin_user=user,
        events=rows,
        live=events.live_event(conn),
        song_count=len(songs.list_songs(conn)),
        default_start=datetime.now().replace(hour=20, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M"),
    )


@router.post("/events")
def create_event(
    request: Request,
    name: str = Form(...),
    starts_at: str = Form(...),
    venue: str = Form(""),
    round_count: int = Form(1),
    max_votes: int = Form(5),
):
    user = current_admin(request)
    db = get_db(request)
    # The browser sends local wall-clock time with no zone; interpret it in the
    # server's zone and store UTC.
    try:
        local = datetime.fromisoformat(starts_at)
        iso = local.astimezone().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return redirect("/admin", flash=("bad", "That start time is not valid."))

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
        return redirect("/admin", flash=("bad", str(exc)))
    return redirect(f"/admin/events/{event.id}", flash=("", f"Created {event.name}."))


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_console(event_id: int, request: Request, round: int | None = None):
    user = current_admin(request)
    settings = get_settings(request)
    conn = get_db(request).read()
    event = events.get(conn, event_id)
    all_rounds = rounds.for_event(conn, event_id)

    selected = next((r for r in all_rounds if r.id == round), None)
    if selected is None:
        selected = next((r for r in all_rounds if r.state == "open"), all_rounds[0])

    base = str(request.base_url).rstrip("/")
    band_token = get_tokens(request).make_band_token(event_id)

    return render(
        request,
        "admin/event.html",
        nav="events",
        admin_user=user,
        event=event,
        starts_local=_local(event.starts_at),
        transitions=TRANSITION_BUTTONS[event.state],
        selected=selected,
        next_round=any(r.ordinal == selected.ordinal + 1 for r in all_rounds),
        round_rows=[
            {
                "round": r,
                "stats": ballots.round_stats(conn, r.id),
                "votable": len(rounds.votable_songs(conn, r.id)),
            }
            for r in all_rounds
        ],
        board=rounds.song_board(conn, selected.id),
        tally=ballots.tally(conn, selected.id),
        stats=ballots.round_stats(conn, selected.id),
        listeners=hub.subscriber_count(event_topic(event_id)),
        notes=events.band_notes(conn, event_id),
        log=log.for_event(conn, event_id, limit=40),
        public_url=f"{base}/e/{event.slug}",
        band_url=f"{base}/band/{band_token}",
        settings=settings,
    )


@router.get("/events/{event_id}/live", response_class=HTMLResponse)
def event_live(event_id: int, request: Request, round: int | None = None):
    current_admin(request)
    conn = get_db(request).read()
    all_rounds = rounds.for_event(conn, event_id)
    selected = next((r for r in all_rounds if r.id == round), None)
    if selected is None:
        selected = next((r for r in all_rounds if r.state == "open"), all_rounds[0])
    return fragment(
        "admin/_live.html",
        tally=ballots.tally(conn, selected.id),
        stats=ballots.round_stats(conn, selected.id),
        listeners=hub.subscriber_count(event_topic(event_id)),
    )


@router.post("/events/{event_id}/state")
def event_state(event_id: int, request: Request, to: str = Form(...)):
    user = current_admin(request)
    try:
        events.transition(get_db(request), event_id=event_id, to=to, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}", flash=("bad", str(exc)))
    # Everyone holding this event's page needs the new shape of it.
    hub.publish(event_topic(event_id), kind="event", reload=True)
    return redirect(f"/admin/events/{event_id}")


@router.post("/events/{event_id}/rounds")
def add_round(event_id: int, request: Request):
    user = current_admin(request)
    try:
        rnd = rounds.add_round(get_db(request), event_id=event_id, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}", flash=("bad", str(exc)))
    return redirect(
        f"/admin/events/{event_id}?round={rnd.id}",
        flash=("", f"Round {rnd.ordinal} added, with the unplayed songs carried over."),
    )


@router.post("/events/{event_id}/notes")
def save_notes(event_id: int, request: Request, body: str = Form("")):
    user = current_admin(request)
    events.update_band_notes(get_db(request), event_id=event_id, body=body, actor=user)
    hub.publish(event_topic(event_id), kind="notes")
    return redirect(f"/admin/events/{event_id}", flash=("", "Notes saved."))


@router.post("/events/{event_id}/delete")
def delete_event(event_id: int, request: Request):
    user = current_admin(request)
    try:
        events.delete(get_db(request), event_id=event_id, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{event_id}", flash=("bad", str(exc)))
    return redirect("/admin", flash=("", "Event deleted."))


# ---------------------------------------------------------------- rounds --
@router.post("/rounds/{round_id}/state")
def round_state(round_id: int, request: Request, to: str = Form(...)):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    try:
        rounds.transition(db, round_id=round_id, to=to, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{rnd.event_id}?round={round_id}", flash=("bad", str(exc)))
    # Opening or closing a round changes what every attendee's page should be,
    # so this one does force a reload on their side.
    hub.publish(event_topic(rnd.event_id), kind="round", reload=True)
    return redirect(f"/admin/events/{rnd.event_id}?round={round_id}")


@router.post("/rounds/{round_id}/max-votes")
def round_max_votes(round_id: int, request: Request, max_votes: int = Form(...)):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    try:
        rounds.set_max_votes(db, round_id=round_id, max_votes=max_votes, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{rnd.event_id}?round={round_id}", flash=("bad", str(exc)))
    return redirect(f"/admin/events/{rnd.event_id}?round={round_id}")


@router.post("/rounds/{round_id}/carry-forward")
def carry_forward(round_id: int, request: Request):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    try:
        moved = rounds.carry_forward(db, from_round=round_id, actor=user)
    except DomainError as exc:
        return redirect(f"/admin/events/{rnd.event_id}?round={round_id}", flash=("bad", str(exc)))
    return redirect(
        f"/admin/events/{rnd.event_id}?round={round_id}",
        flash=("", f"{moved} song(s) carried into round {rnd.ordinal + 1}."),
    )


@router.post("/rounds/{round_id}/songs")
async def round_songs(round_id: int, request: Request):
    user = current_admin(request)
    db = get_db(request)
    rnd = rounds.get(db.read(), round_id)
    form = await request.form()
    action = form.get("action")
    song_ids = [int(v) for v in form.getlist("song_ids")]
    back = f"/admin/events/{rnd.event_id}?round={round_id}"

    if not song_ids:
        return redirect(back, flash=("warn", "Select some songs first."))

    try:
        if action == "exclude":
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

    hub.publish(event_topic(rnd.event_id), kind="songs", reload=True)
    return redirect(back, flash=("", message))


# ----------------------------------------------------------------- songs --
@router.get("/songs", response_class=HTMLResponse)
def song_list(request: Request):
    user = current_admin(request)
    conn = get_db(request).read()
    everything = songs.list_songs(conn, include_retired=True)
    return render(
        request,
        "admin/songs.html",
        nav="songs",
        admin_user=user,
        active=[s for s in everything if not s.retired],
        retired=[s for s in everything if s.retired],
    )


@router.post("/songs")
def add_song(request: Request, title: str = Form(...), artist: str = Form(...)):
    user = current_admin(request)
    try:
        songs.add(get_db(request), title=title, artist=artist, actor=user)
    except DomainError as exc:
        return redirect("/admin/songs", flash=("bad", str(exc)))
    return redirect("/admin/songs", flash=("", f"Added {title}."))


@router.post("/songs/import")
async def import_songs(request: Request, file: UploadFile):
    user = current_admin(request)
    raw = await file.read()
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
    return redirect("/admin/songs", flash=("", ", ".join(parts) + "."))


@router.post("/songs/{song_id}/retire")
def retire_song(song_id: int, request: Request):
    user = current_admin(request)
    songs.set_retired(get_db(request), song_id=song_id, retired=True, actor=user)
    return redirect("/admin/songs")


@router.post("/songs/{song_id}/restore")
def restore_song(song_id: int, request: Request):
    user = current_admin(request)
    songs.set_retired(get_db(request), song_id=song_id, retired=False, actor=user)
    return redirect("/admin/songs")


@router.get("/songs/export.csv")
def export_songs(request: Request):
    current_admin(request)
    rows = songs.list_songs(get_db(request).read(), include_retired=True)
    return _csv(
        "songs.csv",
        ["id", "title", "artist", "retired"],
        [[s.id, s.title, s.artist, "yes" if s.retired else ""] for s in rows],
    )


# --------------------------------------------------------------- exports --
def _csv(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel on a Czech Windows machine opens it as UTF-8 rather than
    # mangling every accented character.
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/events/{event_id}/export.csv")
def export_votes(event_id: int, request: Request):
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
def export_results(event_id: int, request: Request):
    current_admin(request)
    conn = get_db(request).read()
    event = events.get(conn, event_id)
    rows = ballots.event_tally(conn, event_id)
    return _csv(
        f"jukebox-{event.slug}-results.csv",
        ["rank", "artist", "title", "votes"],
        [[i, r["artist"], r["title"], r["votes"]] for i, r in enumerate(rows, start=1)],
    )


@router.get("/events/{event_id}/qr.svg")
def event_qr(event_id: int, request: Request):
    """The QR code for the table cards. Nobody types a URL in the dark."""
    current_admin(request)
    event = events.get(get_db(request).read(), event_id)
    url = f"{str(request.base_url).rstrip('/')}/e/{event.slug}"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buffer = io.BytesIO()
    img.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")


@router.get("/events/{event_id}/stream")
async def admin_stream(event_id: int, request: Request):
    current_admin(request)
    return StreamingResponse(
        hub.stream(event_topic(event_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
