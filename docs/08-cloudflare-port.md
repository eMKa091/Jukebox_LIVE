# 08 — Everything on Cloudflare: the decision, the target, the checklist

**This file is the handover.** Whoever continues this work, person or model,
reads this first, does the next unticked step, ticks it, adds a line to the
log at the bottom, and commits. Nothing about the port lives only in a chat.

- Branch: `main`. The work began on `feat/cloudflare-workers` (cut from `main`
  at `1e5a9a0`); on 2026-11-13 Filip asked for it to go straight to `main`, and
  `main` was fast-forwarded to that branch, which is now finished with.
- Decided by Filip, 2026-11-13: **everything runs on Cloudflare, the app stays
  in Python, and the app moves from a container to a Worker with a Durable
  Object.** This supersedes the Fly.io plan in [05-hosting.md](05-hosting.md)
  and the "Deploying" section of `jukebox/README.md`. Until step 9 those stay
  in the tree, because the container version is the one that works today.

## 1. Why

The app needs a container only because of how it was built: a database file
on a disk, worker threads, one long-lived process holding the list of
connected screens, and native programs (argon2, Litestream). A Worker has none
of those.

A **Durable Object with SQLite storage** is the piece of Cloudflare that has
the same shape as this app: one single-threaded object, its own SQLite
database stored by Cloudflare, and the open connections held by the same
object. With it there is no machine to keep on, no disk, no backup pipeline
(Cloudflare restores the database to any moment of the last 30 days), and one
provider.

## 2. Target

```
www.jukeboxheroes.cz      Worker "jukeboxheroes-web"   static files only            site/  (built, not deployed)
hlasuj.jukeboxheroes.cz   Worker "jukebox-live", Python
                            entry Worker   serves /static/* from assets, hands every other
                                           request to the ONE Durable Object (name "jukebox",
                                           jurisdiction "eu")
                            Durable Object `Jukebox`
                                           the SQLite database        ctx.storage.sql
                                           the FastAPI app            pages and form posts
                                           the live connections       WebSockets, hibernating
admin.jukeboxheroes.cz    a Cloudflare redirect to hlasuj.jukeboxheroes.cz/admin
```

Everything in the object, as the first design, because it is the smallest
change: the app stays one program and its database calls stay in-process and
synchronous. **Fallback if step 8 shows one object is too slow:** render pages
in the entry Worker (many run in parallel) and keep only reads and writes in
the object.

What carries over unchanged in substance: `app/domain/` (the rules), the
templates and CSS, the 168 tests (they keep running against plain SQLite,
which is the same engine), the fixes of [07](07-review-of-the-rebuild.md).

What is rebuilt:

| Today | On Cloudflare | Step |
|---|---|---|
| `with db.write() as conn:` on a `sqlite3` file | `db.transact(fn)`; the object's `ctx.storage.transactionSync` | 2, 5 |
| request handlers on worker threads | `async def` handlers calling the rules inline (no threads exist) | 3 |
| settings from `os.environ` | settings from the Worker's `env` | 3 |
| `hub.py`: asyncio queues, Server-Sent Events | the object's WebSockets; `app.js` speaks WebSocket | 4 |
| `PRAGMA user_version` | a `schema_migrations` table | 2 |
| argon2 | argon2 if it imports there, else PBKDF2 from `hashlib` | 6 |
| `python -m app.cli create-admin` | a one-time setup page guarded by a secret | 6 |
| `scripts/migrate_legacy.py` writes a file | the same, then an admin-only import into the object | 7 |
| Dockerfile, `deploy/`, `fly.toml`, Litestream | deleted | 9 |

## 3. What Cloudflare's documentation says (read 2026-11-13)

Facts the plan rests on, each from the page named. Re-read a page before
relying on a number.

- Python Workers run on Pyodide. FastAPI is supported; the ASGI bridge is
  `from workers import asgi` / `asgi.entrypoint(app)`.
  ([python](https://developers.cloudflare.com/workers/languages/python/),
  [fastapi](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/))
- Packages: pure-Python packages from PyPI and packages built for Pyodide.
  `threading` and `multiprocessing` import but do not function. The filesystem
  is in memory and lost with the isolate.
  ([packages](https://developers.cloudflare.com/workers/languages/python/packages/),
  [stdlib](https://developers.cloudflare.com/workers/languages/python/stdlib/))
- A Durable Object can be written in Python: `from workers import
  DurableObject`, `self.ctx.storage.sql.exec(...)`.
  ([get started](https://developers.cloudflare.com/durable-objects/get-started/))
- `sql.exec()` is synchronous and returns a cursor (`toArray()`, `one()`,
  `rowsRead`, `rowsWritten`). It cannot run `BEGIN` or `SAVEPOINT`;
  transactions are `ctx.storage.transactionSync(callback)`, rolled back if the
  callback throws. Limits: 10 GB per object, 100 bound parameters per query,
  100 KB per statement. Point-in-time recovery: any moment of the last 30
  days, not available in local development.
  ([sqlite api](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/),
  [limits](https://developers.cloudflare.com/durable-objects/platform/limits/))
- One object: 128 MB of memory (the isolate limit), 30 s of CPU per request
  (configurable to 5 min), a soft limit of 1,000 requests per second.
- WebSockets accepted with the Hibernation API let the object sleep between
  messages and are not billed while it sleeps; there is a Python example.
  ([websockets](https://developers.cloudflare.com/durable-objects/best-practices/websockets/))
- An object can be pinned to the EU: `env.NAMESPACE.jurisdiction("eu")`.
  ([data location](https://developers.cloudflare.com/durable-objects/reference/data-location/))

## 4. What the documentation does not say

Each of these is answered by running it, in step 1, and the answer is written
here next to the question. Answered 2026-11-13 on the local runtime
(`pywrangler dev`, wrangler 4.161.0, workers-py 1.17.9, Pyodide's Python 3.14)
by a throwaway spike, one probe per question. It is in git history:
`git log --diff-filter=D --oneline -- jukebox/spike` names the commit that
deleted it; `git show <that commit>^:jukebox/spike/src/entry.py` prints it.

| # | Question | If the answer is no | Answer |
|---|---|---|---|
| U1 | Do FastAPI, Jinja2, python-multipart, itsdangerous, qrcode and tzdata import in a Python Worker? | replace the one that does not | **Yes**, all six. `ZoneInfo("Europe/Prague")` works from tzdata; qrcode writes its SVG. |
| U2 | Can the FastAPI app be served from inside a Durable Object's `fetch` (via the `asgi` module)? | route by hand in the object, keep the templates | **Yes**: `await asgi.fetch(app, request, self.env)` from the object's `fetch`. Cookies in, several `Set-Cookie` out, form posts with repeated fields, 303s: as in the container. Two catches. A plain `def` handler fails with `RuntimeError: can't start new thread` (FastAPI runs it on a thread), so 3.1 is required, not a tidy-up. And `asgi.fetch` runs the app's lifespan on every request, so the object's app has none: it migrates in the object's constructor. |
| U3 | Do `SELECT last_insert_rowid()` and `SELECT changes()` work through `sql.exec`? | `INSERT … RETURNING id`; count before and after | **Yes**, both, and `RETURNING` too. The cursor has no `lastrowid`, only `rowsWritten`; the adapter asks `last_insert_rowid()` after an INSERT. `None` binds as NULL, `bytes` as a BLOB, 100 parameters are accepted. **A cursor not read to the end blocks DDL** (`SQLITE_LOCKED` on the next `DROP TABLE`), so the adapter reads every result in full at once. |
| U4 | Does a Python exception raised inside a `transactionSync` callback roll back and arrive in Python as itself? | catch and re-raise in the adapter | **Yes**: the insert was rolled back and the same exception class arrived; the callback's return value comes back too. Constraint failures arrive as `pyodide.ffi.JsException` whose message names them (`UNIQUE constraint failed: …: SQLITE_CONSTRAINT`), so the adapter turns those into `IntegrityError`. `BEGIN` is refused, as documented. **`PRAGMA user_version` is refused (`SQLITE_AUTH`)**, so 2.5 is required. |
| U5 | Are foreign keys enforced (`ON DELETE CASCADE`), and do partial unique indexes and `CHECK` work? | enforce the cascade in `events.delete` | **Yes**, all three, with `PRAGMA foreign_keys` already 1; a dangling foreign key is refused. `lower()` folds ASCII only, exactly as the stdlib's SQLite does, so the songs index behaves the same. |
| U6 | Can templates and the `.sql` file be read from the bundle with ordinary file access? | load them into a dict at import | **Yes**: wrangler attaches every non-Python file under `src/` as a text module, and `Path(__file__).parent / …` reads it. |
| U7 | Does `argon2` import, and does one hash fit in memory? | PBKDF2-SHA256 from `hashlib` | **Yes**: argon2-cffi imports and one default hash (64 MiB) took 209 ms locally. The fallback would not have worked: Pyodide's `hashlib` has no `pbkdf2_hmac`. |
| U8 | Does the Hibernation API work from Python as in the docs' example (`acceptWebSocket`, `getWebSockets`)? | ordinary WebSockets, billed while open | **Yes**: `self.ctx.acceptWebSocket(server, to_js(["event:1"]))` (the tags must be a JS array; a Python list is refused), `getWebSockets(tag)`, `getTags`, attachments, and `webSocketMessage` / `webSocketClose` as methods. One broadcast reached 20 sockets in 25 ms. `webSocketClose` must call `ws.close(code, …)`, or the client waits out its close timeout. |
| U9 | Speed: how long does one ballot page (420 songs) take to render in the object? | the fallback design in section 2 | **Locally only, so not answered yet.** 500 requests, 50 at a time, for a 420-row page rendered by FastAPI in the object: 92 a second, median 345 ms, p95 1.6 s. A trivial response gave 175 a second whether the object or the entry Worker sent it, so locally most of the cost is the fixed cost of a Python request in one isolate; on Cloudflare the entry Worker's share of it is spread over many isolates, the object's is not. The need is about 170 a second (500 phones reloading over 3 s). Close, and only 8.2 on the deployed app can say. Cheap help before the fallback: render the song list once per round state and reuse it. Do not time inside a request on Cloudflare: its clock stands still while code runs. |

## 5. Checklist

Rules for every step: small commits on this branch; `cd jukebox &&
./.venv/bin/python -m pytest -q` passes before each commit (170 tests after
step 2.2a); never push without Filip saying so; if a step turns out wrong, say so
in the log rather than quietly doing something else.

**Step 0 — record the decision**
- [x] This file. Load-test scripts brought into the repo (`jukebox/tools/loadtest/`).

**Step 1 — answer U1–U9 on the real runtime**
- [x] Install the tooling: `brew install uv` (0.13.8), nothing else. A
      project names `workers-py` and `workers-runtime-sdk` in its
      `pyproject.toml` (`[dependency-groups] dev`); `uv run pywrangler dev`
      then fetches them into the project's own `.venv`, vendors the app's
      packages into `python_modules/`, fetches wrangler through `npx` (Node
      25 is on this Mac) and starts the local runtime. `uv run pywrangler
      deploy` deploys, after `uv run pywrangler login` (Filip's account). The
      runtime's Python is Pyodide's 3.14, not the virtualenv's.
- [x] A throwaway Worker + Durable Object in `jukebox/spike/` that answers
      U1–U8 locally, one small probe each. Answers in section 4.
- [x] ~~Deploy the spike once to Filip's account and time U9 there.~~
      Changed: the spike's page is not the real ballot, and its local timing
      showed the cost is mostly per request, not per template. The deployed
      timing is taken once, on the real app, in 8.2.
- [x] Delete `jukebox/spike/` once the answers are written down.

**Step 2 — the storage seam** *(pure refactor; the container app keeps working)*
- [x] 2.1 `Database.transact(fn)` and a backend-neutral `IntegrityError` in
      `app/db.py`. `write()` stays until 2.3.
- [x] 2.2a `domain/songs.py` converted, as the worked example of the pattern.
- [x] 2.2b `domain/events.py`
- [ ] 2.2c `domain/rounds.py`
- [ ] 2.2d `domain/ballots.py`
- [ ] 2.2e `domain/identity.py`
- [ ] 2.3 Remove `Database.write()`; `grep -rn "db.write\|\.write() as" app` is empty.
- [ ] 2.4 Catch `app.db.IntegrityError`, not `sqlite3.IntegrityError`, in
      `events.transition` and `rounds.transition`.
- [ ] 2.5 Track migrations in a `schema_migrations` table. A database that
      already has `user_version = 1` must be recognised as migrated.

The pattern, from `songs.py`:

```python
# before                                   # after
def retire(db, *, song_id, actor):         def retire(db, *, song_id, actor):
    with db.write() as conn:                   def work(conn):
        ...                                        ...
        return x                                   return x
                                               return db.transact(work)
```

`fn` receives the connection, runs entirely inside one transaction, and must
not be `async`. Whatever it raises rolls the transaction back and is re-raised.

**Step 3 — the web layer without threads**
- [ ] 3.1 Every handler `async def`, calling the rules inline. Remove the
      thread limiter in `main.py` and the `run_in_threadpool` calls. (On the
      object there is one thread and SQL is in-process, so this is correct
      there. It is NOT correct for the container, so from here on the
      container version is no longer the one to run at a concert.)
- [ ] 3.2 `load_settings(env)` takes a mapping; `os.environ` is only the default.
- [ ] 3.3 Templates load by whatever U6 found.

**Step 4 — live updates over WebSockets**
- [ ] 4.1 `hub.py` becomes an interface with two backends: in-process (tests,
      local) and the object's sockets, tagged `event:<id>` for every screen
      and `votes:<id>` for the band display and the console.
- [ ] 4.2 `app.js`: `WebSocket` instead of `EventSource`. The first message is
      still `ready` with the stamp; the stamp check, the reload spread and the
      wake-up reconnect stay exactly as they are.
- [ ] 4.3 The R1 test in a real browser again (docs/07, "What was done").

**Step 5 — the Durable Object**
- [ ] 5.1 `app/db_durable.py`: the same interface over `ctx.storage.sql`. Rows
      readable by name and by position; `lastrowid` and `rowcount` on the
      cursor (by U3); constraint failures raised as `IntegrityError`.
- [ ] 5.2 `jukebox/worker.py`: the entry Worker and the `Jukebox` object.
      `jukebox/wrangler.jsonc`: assets from `app/static`, the object binding,
      the SQLite migration tag, `JUKEBOX_PUBLIC_URL`.
- [ ] 5.3 A smoke script against the local dev server: create an event, go
      live, join, vote, see the count on the band display.

**Step 6 — accounts**
- [ ] 6.1 Password hashing by U7.
- [ ] 6.2 First admin: a setup page that works once, only with the secret
      `JUKEBOX_SETUP_TOKEN`, and only while there is no admin.
- [ ] 6.3 The sign-in throttle's counts in a table (the object's memory is
      emptied whenever it sleeps).

**Step 7 — the data**
- [ ] 7.1 Import: `migrate_legacy.py` output into the object through an
      admin-only endpoint, in one transaction, gate G2 run on the result.
- [ ] 7.2 A restore drill with point-in-time recovery on the deployed object.

**Step 8 — 500 phones on the real thing**
- [ ] 8.1 `tools/loadtest/phones.py` taught to speak WebSocket. (Today it speaks
      Server-Sent Events and runs against the container app:
      `jukebox/tools/loadtest/run.sh "$PWD/jukebox" label 500 15 30` seeds a
      scratch database, starts the app on port 8766, runs 500 phones arriving
      over 15 s and voting over 30 s, and prints the timings.)
- [ ] 8.2 Run against the deployed Worker. Pass: every vote stored, no errors,
      the ballot within 2 s for 95 % of phones after a round opens. Numbers in
      the log. If it fails on speed: the fallback design in section 2.

**Step 9 — cutover and cleanup**
- [ ] 9.1 DNS at Cloudflare (nameservers changed at Webglobe), both Workers on
      their names, the admin redirect.
- [ ] 9.2 Delete `Dockerfile`, `deploy/`, `fly.toml`, `compose.yaml`; rewrite
      "Deploying" in `jukebox/README.md`; mark 05-hosting.md superseded.
- [ ] 9.3 The Streamlit app replaced by one page linking to the new address
      (printed QR codes point at `jukeboxlive.streamlit.app`).

## 6. Costs

**$5 a month**, the Workers Paid plan, and nothing else at this size.

| | Plan | Cost |
|---|---|---|
| Website | static files on a Worker: requests are free and unlimited | $0 |
| Voting app | Workers Paid | $5 / month |
| Its database | inside the object; 5 GB included, this one is megabytes | included |
| Backup | point-in-time recovery, 30 days | included |
| DNS, certificates | Cloudflare free plan | $0 |
| Domain | stays at Webglobe (Cloudflare does not register `.cz`) | as today |

Included each month in the $5, against what one 500-phone evening uses (my
estimate from the load test, to be replaced by the dashboard's numbers after
step 8): 1 million requests against some 30,000; 50 million rows written
against some 10,000; 400,000 GB-seconds of running time against some 1,500.

Why not the free plan: it has daily caps (100,000 requests, 5 million rows
read, 100,000 rows written) and a hit cap means failed requests. A full room
loading the ballot several times could reach the rows-read cap on the night.

## 7. Log

Newest first. One line per session: date, who, what was done, what is next.

- 2026-11-13, Claude (Fable 5): decision recorded; branch created; load-test
  scripts added; steps 2.1 and 2.2a done, 170 tests pass (two new, for `transact`). Tooling for step 1
  (`uv`, `pywrangler`, `wrangler`) is not installed on this Mac and was not
  installed. **Next: 2.2b, or step 1 if the tooling is installed first.**
  Step 1 is the one that can still say no; steps 2.x are safe either way.
