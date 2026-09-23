# Jukebox LIVE

Live song voting for a band and its audience. Attendees pick songs from their
phones during a gig; the band sees the ranking update on stage.

This is the rebuild. The Streamlit version it replaces is in
[`../jukeboxHeroes-v2/`](../jukeboxHeroes-v2/), and what it did, what was wrong
with it and why this exists are all in [`../docs/`](../docs/).

---

## Run it locally

> **Everything below runs from inside `jukebox/`.** `cd jukebox` first — the
> `app` package lives here, not at the repository root.

First time only:

```sh
cd jukebox && python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
```

Create an account. No environment variables needed — the CLI signs nothing, so
it does not ask for a secret key:

```sh
./.venv/bin/python -m app.cli create-admin marek
```

Start it:

```sh
JUKEBOX_DEV=1 ./.venv/bin/python -m uvicorn app.main:app --reload --port 8080
```

`JUKEBOX_DEV=1` generates a throwaway signing key and relaxes the `Secure`
cookie flag for plain http on localhost. Without it the app refuses to start
unless `JUKEBOX_SECRET_KEY` is set — deliberately, so production cannot come up
with a guessable one.

Then: <http://localhost:8080/admin> to run a gig, <http://localhost:8080> to vote.

The database lands at `jukebox/data/jukebox.db`. Delete that file for a clean
slate; set `JUKEBOX_DB` to put it somewhere else.

Tests — all 95 of them, against a real SQLite database and the real legacy
backup file, no mocks:

```sh
./.venv/bin/python -m pytest
```

## Load the real data from the old system

```sh
./.venv/bin/python scripts/migrate_legacy.py \
    ../jukeboxHeroes-v2/backups/backup-votes.db data/jukebox.db --force
```

It prints what it moved and then runs gate G2 — event counts, vote counts, zero
orphans, and per-song tallies identical to the old results screen. It refuses
to report success if any of those fail. Admin accounts are deliberately **not**
migrated; the legacy hashes are unsalted SHA-256 from a database file that sat
in a public GitHub repository.

---

## How a gig runs

```
  ADMIN                          ATTENDEES                  BAND
  ─────                          ─────────                  ────
  Import the song list
  Create the event         ──►   (nothing public yet)
  Put it on air            ──►   QR code works, name prompt
  Open round 1             ──►   ballot appears             ranking appears
                                 they vote            ──►   ranking moves live
  Close round 1            ──►   standings
  Mark what was played
  Open round 2             ──►   ballot, played songs gone
  Close the event          ──►   splash screen
```

The admin console is the only place any of this is driven from, and every step
is one state transition, logged.

## Design in one page

**One container, one process, one SQLite file on a persistent volume, with
Litestream streaming the write-ahead log to object storage continuously.** That
is the entire production topology.

SQLite rather than a database server because this application has one writer,
about thirty thousand rows a year, and a hard requirement to be correct during
a twenty-minute burst a few nights a month. The legacy system's data loss was
never caused by SQLite — it was caused by an ephemeral disk plus a backup
button someone had to remember to press. Fix those two and SQLite is the right
answer, at a lower recovery point than nightly dumps would give.

Three rules the code is built around:

1. **Invariants live in the database.** At most one live event and at most one
   open round per event are partial unique indexes, not Python checks. One
   voter can hold at most one vote per song per round, by constraint. The old
   code did `SELECT COUNT(*)` then `INSERT`, which is a race.
2. **`app/domain/` never imports `app/web/`.** Every rule is testable without
   an HTTP client. The old rules were interleaved with `st.button()` calls,
   which is why none of them could be tested.
3. **Nothing is deleted that something else points at.** Songs retire, they do
   not vanish. The old "Delete all songs" button orphaned 896 rows.

```
app/
  main.py            FastAPI app, error handling, /healthz, /readyz
  config.py          settings, all from the environment
  db.py              connections, WAL, migrations via PRAGMA user_version
  sql/               schema, applied in filename order
  domain/            the rules. no HTTP in here
    events.py          draft -> ready -> live -> closed
    rounds.py          pending -> open -> closed, plus per-round song lists
    ballots.py         casting votes, idempotency, tallies
    songs.py           master list, CSV import
    identity.py        argon2 passwords, login throttle
    log.py             append-only audit trail
  web/
    public.py          the attendee journey
    band.py            the stage display, on a signed link
    admin.py           the console
    hub.py             SSE fan-out
    security.py        cookies, sessions, band tokens
    render.py          templates and flash messages
  templates/  static/  server-rendered HTML, one CSS file, ~160 lines of JS
scripts/migrate_legacy.py
tests/
```

### Live updates

Server-Sent Events, not WebSockets: one-way server-to-client is the shape of
the problem, and plain HTTP survives the captive portals and mobile proxies
that break WebSocket upgrades. `EventSource` reconnects by itself, which is the
normal case on venue wifi.

A round opening or closing reloads the attendee's page, because its whole shape
differs between states. Votes arriving from other phones do not — they only
re-render the band's and the admin's fragments, so nobody is yanked out of a
half-made ballot.

### There is no client-side state

The server renders every fragment. The only thing the browser owns is a
half-made selection, kept in `sessionStorage` so a reload does not lose it.
"Have I already voted" is read from the database against an httpOnly device
cookie — the fact that used to live in `st.session_state` and die on refresh.

---

## Deploying

Fly.io, Warsaw, about $5/month. See [`../docs/05-hosting.md`](../docs/05-hosting.md)
for why not AWS or Azure.

```sh
fly launch --no-deploy
fly volumes create jukebox_data --size 1 --region waw
fly secrets set JUKEBOX_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
fly secrets set LITESTREAM_REPLICA_URL=s3://your-bucket/jukebox \
                LITESTREAM_ACCESS_KEY_ID=... \
                LITESTREAM_SECRET_ACCESS_KEY=...
fly deploy
fly ssh console -C "python -m app.cli create-admin marek"
```

`fly.toml` sets `min_machines_running = 1` deliberately. **Do not scale to
zero.** A cold start is fine on a Tuesday and unacceptable when the singer has
just told two hundred people to open the link; the saving is about $2/month.

The container refuses to start without `JUKEBOX_SECRET_KEY`, and prints a loud
warning if `LITESTREAM_REPLICA_URL` is missing — running a real event
unreplicated is the failure mode this whole project exists to remove.

### Environment

| Variable | Required | Meaning |
|---|---|---|
| `JUKEBOX_SECRET_KEY` | **yes** in production | signs admin sessions and band links |
| `JUKEBOX_DB` | no | database path, default `./data/jukebox.db` |
| `JUKEBOX_DEV` | no | relaxes cookie `Secure`, generates a throwaway secret |
| `JUKEBOX_SESSION_MAX_AGE` | no | admin session lifetime, default 12h |
| `JUKEBOX_LOGIN_MAX_ATTEMPTS` | no | failures before lockout, default 8 |
| `LITESTREAM_REPLICA_URL` | in production | S3-compatible replica target |

### Operator commands

```sh
python -m app.cli create-admin <username>
python -m app.cli reset-password <username>
python -m app.cli backup /path/to/snapshot.db     # consistent, app still running
python -m app.cli stats
```

### Restore drill

Do this once a quarter. A backup nobody has restored is a hope.

```sh
litestream restore -o /tmp/restored.db s3://your-bucket/jukebox
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM votes;"
```

---

## What changed from the plan

Two deliberate deviations from [`../docs/04-target-architecture.md`](../docs/04-target-architecture.md),
both toward less machinery:

- **SQLite + Litestream instead of PostgreSQL.** Reasoning above and in the
  README section on design. One service instead of two, no DB bill, and a
  tighter recovery point.
- **~160 lines of plain JavaScript instead of HTMX.** The page needs a
  fetch-and-swap and a checkbox limiter. Pulling in a library — and a CDN
  dependency — to avoid writing those was not a good trade.

## Not built, on purpose

Attendee accounts, Spotify integration, multi-band tenancy, analytics beyond
CSV export, native apps. The list is in
[`../docs/04-target-architecture.md`](../docs/04-target-architecture.md) §7 so
it can be pointed at rather than re-argued.
