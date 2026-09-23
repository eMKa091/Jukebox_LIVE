# 04 — Target architecture

## 1. What the product actually is

Strip away the code and the requirement is small and sharp:

> For a 20-minute window in a loud, dark room, 20–300 people on phones with bad
> connectivity pick songs from a list of ~112. One person on stage opens and
> closes that window and needs the ranking on screen within a second of closing
> it.

That is a **live, short-lived, broadcast-shaped** workload. It is not a CRUD
app that happens to have a vote button. Three properties follow, and they drive
every decision below:

1. **The window is unforgiving.** A failure at 21:40 on a Saturday cannot be
   fixed by a redeploy — the moment is gone. Availability during a ~2-hour
   window, a few nights a month, matters more than uptime percentage.
2. **State is shared and changes at one point.** The admin opens a round; 200
   phones must find out without being told to refresh. One writer, many readers.
3. **The load is nothing.** ~30,000 rows a year. Sizing is irrelevant.
   Correctness under a 30-second burst is not.

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Runtime | **Python 3.12 + FastAPI** | Same language as the existing code and the rest of your work. The domain logic ports as a translation, not a re-derivation. |
| UI | **Jinja2 templates + HTMX + Tailwind** | Server-rendered HTML with surgical partial updates. No Node build, no bundle, no hydration. A first paint on venue 3G is one small HTML document. |
| Real-time | **Server-Sent Events** | One-way server→client is exactly the shape of the problem. Plain HTTP: survives proxies and captive portals that break WebSockets, and reconnects on its own with `Last-Event-ID`. |
| Database | **PostgreSQL 16** | Real constraints, real transactions, real timestamps. See [02-data-model.md](02-data-model.md). |
| DB access | **SQLAlchemy 2 Core + Alembic** | Migrations you can review. Core, not ORM — the queries here are simple and explicit reads better. |
| Auth | **Argon2id + signed session cookie** (admin), **httpOnly device cookie** (attendee) | Replaces `?admin=Boss` and unsalted SHA-256. |
| Packaging | **One Docker image, one process** | Runs on any host. No lock-in, so a hosting decision stays reversible. |

### Why not a SPA framework
SvelteKit or Next.js would give a nicer authoring experience for complex client
state. This app has almost none: a checkbox set and a submit. Adding a JS
toolchain buys bundle size on the worst possible network, a second language, and
a build step, and it buys nothing this product needs. If the UI later grows
genuinely client-heavy, the HTML endpoints stay and a client can be added in
front of them — the decision is not load-bearing.

### The one real fork
**Cloudflare Workers + D1 + Durable Objects** is cheaper (plausibly $0) and its
Durable Object primitive is the single best fit anywhere for "one live round,
many connected phones". You already deploy on Cloudflare. The price is
TypeScript for the whole backend and genuine platform lock-in — Durable Objects
have no equivalent elsewhere.

**Recommendation: take the Python path.** Language continuity with the rest of
your work and a container that runs anywhere are worth more than the ~$5/month
difference. Revisit only if the monthly cost ever actually matters.

---

## 3. State: one machine, one writer, one broadcast

The current design's central defect is that live state is five columns on
`events`, mutated from six places, with two round counters that drift
([03-findings.md#f7](03-findings.md)). Replace it with an explicit state machine
whose transitions are the *only* way state changes.

```
EVENT           draft ──► ready ──► live ──► closed
                            ▲         │
                            └─────────┘   (reopen, admin-only)

ROUND (within a live event)
                pending ──► open ──► closed
```

Invariants, **enforced by the database, not by Python** (partial unique indexes
in [02-data-model.md](02-data-model.md)):

- At most one event in state `live`.
- At most one round per event in state `open`.
- A vote can only be inserted against a round in state `open` — checked in the
  same transaction that reads the state.

### Transition service

Every transition is one function, one transaction, one `event_log` row:

```python
# app/domain/rounds.py
def open_round(session, *, round_id: int, actor: str) -> RoundView:
    """Open a round for voting.

    Locks the row so two admin taps cannot both open it. The partial unique
    index one_open_round is the real backstop: if another round on this event
    is already open, the UPDATE raises IntegrityError and we surface it as a
    409, rather than silently stopping the other round the way
    update_voting_state() used to.
    """
```

Compare with today: `voting_active` is written by `update_voting_state()`,
`start_voting()`, `stop_voting()`, and three inline `UPDATE` statements in
`admin.py`. After this change there is exactly one path, and `event_log`
answers "who opened round 2, and when" — the question nobody can answer about
the five zero-vote events.

### Broadcast

```
admin taps "Open round 2"
   │
   ├─ transition in one transaction ──► Postgres
   │                                      │ NOTIFY jukebox_state
   │                                      ▼
   └─────────────────────────► app LISTENs, fans out over SSE
                                          │
              ┌───────────────────────────┼──────────────────┐
              ▼                           ▼                  ▼
         200 attendee phones         band display       admin console
         (ballot appears)            (live ranking)     (live vote count)
```

Postgres `LISTEN`/`NOTIFY` is the fan-out bus. It costs nothing, needs no extra
service, and if the app ever runs on two instances every instance still hears
every change. No Redis, no Pusher, no polling.

Attendee clients hold one `EventSource` to `/api/stream`. On reconnect — the
normal case on venue wifi — the browser resends `Last-Event-ID` and the server
replays from the current state snapshot, so a dropped connection is invisible.

### Client state

Three variables, and the ballot is the only one the client owns:

| State | Owner | Recovery after a reload |
|---|---|---|
| Round open/closed, `max_votes`, song list | Server, pushed via SSE | Re-pushed on connect |
| Which songs I have ticked (unsubmitted) | Client, in `sessionStorage` | Restored |
| Which songs I have submitted | Server, keyed by device cookie | Re-read from the server |

This is what fixes [F6](03-findings.md): "have I already voted" becomes a server
fact keyed to an httpOnly cookie, not a websocket session variable that dies on
refresh.

---

## 4. Request surface

```
PUBLIC
  GET  /                          splash or ballot, depending on live state
  GET  /e/{slug}                  direct entry (QR code target)
  POST /api/ballot                submit; idempotent; 409 if round not open
  GET  /api/stream                SSE: round state, song list, my submission

BAND (signed link, no password)
  GET  /band/{token}              live ranking + setlist, auto-updating

ADMIN (session cookie)
  POST /admin/login
  GET  /admin                     console
  POST /admin/events              create
  POST /admin/rounds/{id}/open    transition
  POST /admin/rounds/{id}/close   transition
  POST /admin/rounds/{id}/songs   include / exclude / mark played
  GET  /admin/events/{id}/export  CSV, always available (fixes F12)

OPS
  GET  /healthz                   liveness
  GET  /readyz                    DB reachable + migrations current
```

Idempotency for `POST /api/ballot`: the client sends a UUID it generates once
per ballot. A retry on a flaky connection re-sends the same UUID and the
`UNIQUE (round_id, voter_id, song_id)` constraint plus an `ON CONFLICT DO
NOTHING` makes the duplicate a no-op. The attendee taps submit twice on bad
signal and nothing bad happens — today they would be told "thank you" and their
vote may or may not have landed.

---

## 5. Module layout

```
app/
  main.py              FastAPI app, middleware, lifespan (LISTEN task)
  config.py            pydantic-settings; every secret from the environment
  db.py                engine, session, NOTIFY helper
  domain/
    events.py          event lifecycle transitions
    rounds.py          round lifecycle transitions + song assignment
    ballots.py         vote submission, idempotency, tallying
    identity.py        device cookies, admin sessions, argon2
  web/
    public.py          attendee routes
    band.py            band display routes
    admin.py           admin routes
    stream.py          SSE endpoint + subscriber registry
  templates/           Jinja2; base + partials that HTMX swaps
  static/              one CSS file, ~40 lines of JS
migrations/            Alembic
tests/
  test_transitions.py  the state machine, exhaustively
  test_ballots.py      idempotency, limits, closed-round rejection
  test_migration.py    old SQLite -> new Postgres, on the real backup file
Dockerfile
compose.yaml           local dev: app + postgres
```

Rule: `domain/` imports nothing from `web/`. Every rule in the product is
testable without an HTTP client. Today that separation does not exist — the
domain logic is interleaved with `st.button()` calls, which is why none of it
can be tested.

---

## 6. UI

The room is dark, the phone is one-handed, the connection is bad, the user is
mildly drunk and will give you about fifteen seconds.

- **Dark by default.** Not a style preference — a bright white page in a dark
  venue is physically unpleasant and gets closed.
- **Mobile-first, one column.** Minimum 44px touch targets. No horizontal scroll.
- **The counter is the interface.** A persistent "3 / 5 vybráno" bar pinned to
  the bottom, with the submit button in it. Always visible, always reachable
  with a thumb.
- **At the limit, remaining songs go `disabled` and dimmed — they never
  disappear.** This is [F4](03-findings.md), the worst bug in the product.
- **Search box** above the list. 112 songs is a lot of scrolling in the dark.
- **Submission is final and obvious.** A confirmation screen showing exactly
  what was counted, not `st.balloons()`.
- **Czech copy throughout**, proofread. The current strings include
  "Prosím vyberr alespoň jednu píseň" (`voting.py:100`) and an admin button
  labelled "Add to DB (only refreshes page in reality" — unclosed parenthesis
  included.
- **QR code per event.** Generated in the admin console, printed for the tables.
  It encodes `/e/{slug}` — no typing a URL in the dark.

## 7. Explicitly out of scope

Named here so they do not creep in:

- Accounts, email, or SMS for attendees. The device cookie is enough.
- Spotify / streaming integration.
- Multi-band or multi-tenant support.
- Any analytics beyond per-event CSV export.
- Mobile apps.
- Migrating `webpage_source/` (the v1 prototype). It gets deleted.

---

## Amendment — 2026-09-23: SQLite, not PostgreSQL

Reversed after building it, with the operator's agreement.

The workload is one writer, ~30,000 rows a year, and a hard correctness
requirement during a twenty-minute burst. SQLite in WAL mode on a persistent
volume, with Litestream streaming the write-ahead log to object storage
continuously, meets that with one service instead of two, no database bill, and
a *tighter* recovery point than the nightly `pg_dump` this document originally
proposed — seconds rather than hours.

The reasoning that put Postgres here was wrong in a specific way worth naming:
F1 was read as an argument against SQLite. It is not. F1 was caused by an
ephemeral disk plus a backup button a human had to remember to press. Neither
is a property of SQLite, and swapping the engine would have fixed neither.

What was actually given up: horizontal scaling this app will never use, and
`LISTEN`/`NOTIFY` fan-out across processes, which matters only above one
process. The SSE hub is an in-process asyncio fan-out instead
(`app/web/hub.py`); its interface would take a real bus behind it without
anything above it changing.

The invariants this document argued for all survived the move — SQLite supports
partial unique indexes, so `one_live_event` and `one_open_round` are enforced
by the database exactly as designed.

**Also changed:** the UI uses ~160 lines of plain JavaScript rather than HTMX.
The page needs a fetch-and-swap and a checkbox limiter; a library plus a CDN
dependency to avoid writing those was not a good trade.

The built system is in [`../jukebox/`](../jukebox/), and
[`../jukebox/README.md`](../jukebox/README.md) documents it as it actually is.
