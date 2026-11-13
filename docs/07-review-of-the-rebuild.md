# 07 — Review of the rebuild

Written 2026-11-12 against `feat/jukebox-rebuild` at `d8ab0d0`, for a peak of
**500 voting phones** at one concert. Every file in `jukebox/` was read. Each
finding below says how it was established: a probe test that passes when the
defect is real, a measurement, or a reading of the source. Nothing in
`jukebox/` was changed.

## What holds

- All 140 tests pass.
- 500 phones, each joining, holding the live stream and casting five votes
  inside 30 seconds: 2,500 votes stored, 500 voters, no errors, no lost vote.
  Run three times on an M1 Mac with a 420-song catalogue, a band display and an
  admin console connected.
- The invariants are in the database, as designed. A ballot retried with the
  same id is counted once. The domain layer does not import the web layer.

The rules are sound. What follows is about a full room, a phone that went to
sleep, and a deployment that has not been run yet.

## Will be met at a concert

| # | Finding | Established by |
|---|---|---|
| R1 | A phone that sleeps through a round change stays on the old page | probe, source |
| R2 | A round opening costs 9× the CPU it needs | measurement |
| R3 | The container cannot start with replication switched on | Litestream source |
| R4 | The connection ceiling is 600 and the room is 500 | config |
| R5 | A played song returns if the next round was filled first | probe |
| R6 | After round 1 closes, the big button reopens round 1 | probe |
| R7 | An apostrophe in the event name removes the delete confirmation | probe |

### R1 — A phone that sleeps through a round change stays on the old page
`app/static/app.js:109`, `app/web/hub.py:85`.

The stream's first frame carries the hub's version, and the client's `ready`
handler only resets its retry timer. Frames carry no id and nothing is
replayed. A phone locked while the band plays reconnects when it wakes, is told
nothing, and keeps showing "Stránka se sama obnoví, až kapela otevře další
kolo". It will not. The same happens to every phone after a server restart.
Between rounds is exactly when phones are locked.

*Fix:* on a `ready` that follows a reconnect, reload (a half-made ballot
survives a reload already). Better, send a stamp of event and round state in
`ready` and reload only when it differs from the page's own.

### R2 — A round opening costs 9× the CPU it needs
`app/main.py` (no thread limit), `app/static/app.js:117`.

When a round opens or closes, every phone reloads in the same instant. The
handlers run in Starlette's default pool of 40 threads, and Python's `sqlite3`
releases the interpreter lock on every row it fetches, so 40 threads spend
their time handing the lock to each other.

| 500 phones reload onto the ballot | CPU seconds | median wait | 95th percentile |
|---|---|---|---|
| as built (40 threads) | 21 | 3.3 s | 6.0 s |
| pool limited to 4 threads | 2.3 | 1.0 s | 1.8 s |

Measured on an M1; the waits include this Mac's short accept queue. A small
shared cloud CPU is several times slower, and during those seconds the health
check competes for the same threads.

*Fix:* set the pool to about 4 (`anyio.to_thread.current_default_thread_limiter()`
in the lifespan), and delay each phone's reload by a random 0 to 3 seconds.
The ballot's song list is the same for everyone and could be cached per round.

Related, small: every vote is sent to every phone (240,000 frames in the test,
3.5 CPU seconds) and the phones ignore it. A second topic for vote counts,
subscribed to by the band display and the console only, removes it.

### R3 — The container cannot start with replication switched on
`deploy/entrypoint.sh`, `Dockerfile`, `deploy/litestream.yml`.

Read from Litestream v0.3.13's source; not run, there is no Docker on this
machine. Both commands in the entrypoint are given no replica and no `-config`,
so both read `/etc/litestream.yml`. The Dockerfile never copies
`deploy/litestream.yml` there. `LITESTREAM_REPLICA_URL` is not a variable
Litestream reads. With it set, `litestream restore` exits with `config file not
found`, `set -e` stops the script, and the container never reaches uvicorn.
Also: v0.3 cannot take a Cloudflare R2 endpoint from a URL, it needs
`endpoint:` in the config file.

*Fix:* copy the config into the image, name bucket, path, `endpoint` and
`region: auto` in it, and prove it with the restore drill before any event.

### R4 — The connection ceiling is 600 and the room is 500
`fly.toml`, `hard_limit = 600`. Each phone holds one stream; at a round change
each opens a second connection for the reload while the first is closing. Only
relevant if the app stays on Fly. Raise it to 2,000.

### R5 — A played song returns if the next round was filled first
`app/domain/rounds.py:336`. Carry-forward only adds. If round 2 is filled
before round 1's songs are marked as played (an event created with two rounds
and prepared in advance does this), the played songs stay on round 2's ballot,
and pressing carry-forward again does not remove them. *Fix:* treat "played"
as a fact about the event: leave out of every ballot any song played in any
round of it.

### R6 — After round 1 closes, the big button reopens round 1
`app/web/admin.py:236`. The console selects the open round, else the last
closed one, so the one prominent control reads "Start round 1" when the next
thing to do is round 2. *Fix:* when nothing is open, select the first pending
round.

### R7 — An apostrophe in the event name removes the delete confirmation
`app/templates/admin/_tab_data.html:42`. The name is written into an inline
`confirm('…')`. "Rock'n'Roll párty" ends the string early, the handler fails to
compile, and the form submits without asking. *Fix:* put the name in a
`data-` attribute and read it from there.

## Integrity and security

| # | Finding | Established by |
|---|---|---|
| R8 | One phone can vote again through another event's link | probe |
| R9 | Eight wrong passwords lock the band out for fifteen minutes | probe |
| R10 | A database with an admin account is committed to the public repository | verified |
| R11 | A voter's name can run as a formula in the exported CSV | probe |

**R8.** `app/web/public.py:109,130`. Joining works on an event in any state, and
the ballot takes `round_id` from the form without checking that the round
belongs to the event in the URL. Join a past event by its slug, post the live
round's id through that event's ballot URL, and the same phone holds a second
ballot. *Fix:* refuse to join an event that is not live, and refuse a ballot
whose round is not the URL's event. (Clearing cookies also buys a ballot; that
is the stated design.)

**R9.** `app/domain/identity.py:46`. The throttle counts per username, and the
username `marek` is in the README and in the committed database. Separately,
each attempt for an unknown name hashes with 64 MiB of memory on one of 40
threads, enough to exhaust a 512 MB machine. *Fix:* count per client address
(Cloudflare sends it in `CF-Connecting-IP`), run one hash at a time, or put
Cloudflare Access in front of `/admin`.

**R10.** `data/jukebox.db` is tracked since `195a0f2` and holds the account
`marek` with its argon2 hash. The repository is public. `git rm --cached` it,
and do not use that password in production.

**R11.** `app/web/admin.py:628`. A name such as `=HYPERLINK(...)` reaches the
votes export unchanged and Excel evaluates it. Prefix cells that start with
`=`, `+`, `-` or `@` with an apostrophe.

## Smaller

- **A dropped subscriber is never disconnected** (`hub.py:75`). A stream whose
  queue fills is taken out of the fan-out and goes on sending keepalives, so
  that browser never reconnects. End the stream instead. Probe.
- **The draft is cleared before the ballot is known to have arrived**
  (`app.js:66`). On a failed submit the selection is gone. Clear it when the
  receipt page loads.
- **Start times are stored in the server's zone**, and the image runs in UTC:
  20:00 typed in Ostrava is stored as 20:00Z. Set `TZ=Europe/Prague`. Probe.
- **A failed migration is not rolled back** and its error is replaced by
  "cannot rollback" (`db.py:94`): `executescript` commits first. Probe.
- **The ranking still lists a retired song** that the ballot no longer offers
  (`ballots.py:170`). Probe.
- **The ballot and the admin song actions touch SQLite on the event loop**
  (`async def` handlers). No effect in the load test; make them plain `def`.
- **The ballot page is 145 KB** at 420 songs and the app does not compress.
  Behind Cloudflare it is compressed for free.
- **The error page writes the exception text unescaped** (`main.py:80`). No
  path reaches it with user text today.
- `requirements.txt` is unpinned. The READMEs say 94 and 95 tests; there are
  140. `migrate_legacy.py --force` replaces the whole database, admins included.

## Two addresses, and Cloudflare

- The QR code and the audience link are built from whatever host the admin is
  on (`admin.py:330,681`). Opened as `admin.jukeboxheroes.cz`, the console
  prints a QR code for `admin.jukeboxheroes.cz/e/…`. Probe. Either give the app
  a public address setting, or keep one host and let Cloudflare redirect
  `admin.jukeboxheroes.cz` to `hlasuj.jukeboxheroes.cz/admin`. The second needs
  no code.
- The QR code on the Wix site and in its printable PDF points at
  `https://jukeboxlive.streamlit.app/`. Printed cards stop working at cutover
  unless the Streamlit app is left as one page that links to the new address.
- **Cloudflare cannot run this app on Workers or Pages**: it is a Python
  process with a SQLite file. Cloudflare Containers can run the image (Workers
  Paid, $5 a month, plus usage). Its disk is wiped whenever the instance sleeps
  or the platform restarts it, and Cloudflare says it may do that at any time.
  Litestream to R2 then holds the only lasting copy, which makes R3 the first
  thing to fix and R1 the second. The plan in `05-hosting.md` (Fly, a volume,
  Litestream to R2, Cloudflare in front for DNS and the website) keeps two
  copies. Sources: Cloudflare's Containers pricing, architecture and FAQ pages,
  read 2026-11-12.

## How this was checked

The probes and the load test were run from a scratch folder against this
checkout and are not in the repository. Each probe is a dozen lines and belongs
in `jukebox/tests/` next to the fix it guards, inverted so that it fails until
the fix is made.
