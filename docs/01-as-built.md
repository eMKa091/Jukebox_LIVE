# 01 — As-built behaviour map

Status: accurate as of commit `4d31a0f` (2026-06-20), verified by reading every
source file and querying the shipped database.

This document describes **what the code does**, not what it was meant to do.
Where the two differ, the difference is recorded in [03-findings.md](03-findings.md).

---

## 1. What exists in the repository

| Path | What it is | Live? |
|---|---|---|
| `jukeboxHeroes-v2/` | The application. 15 Python files, ~1,900 LOC. | **Yes** |
| `webpage_source/` | v1 prototype. CSV-backed, no admin, no events. | No — superseded |
| `dataSources/*.csv` | Song lists. Only `songList.csv` matches the v2 import format. | Partly |
| `backups/backup-votes.db` | Stale SQLite copy at repo root (1 event, 34 votes). | No — orphan |
| `jukeboxHeroes-v2/backups/backup-votes.db` | **The production database.** 8 events, 45 votes, 112 songs. | **Yes** |
| `deliveryDocumentation/` | Oct-2024 delivery notes + interaction flow diagram. | Reference |
| `.devcontainer/` | Codespaces config, still points at the v1 `webpage_source/Uvod.py`. | Stale |

The v1 tree under `webpage_source/` reads songs from a CSV, writes a flat
`votes(uniqueID, randomNumber, song, date)` table, and has no concept of an
event or a round. Nothing in v2 imports from it. It is history.

---

## 2. Runtime topology

    Browser (attendee phone)  ─┐
    Browser (admin laptop)    ─┼──►  Streamlit Cloud container
    Browser (band tablet)     ─┘        │
                                        │  index.py  (single entrypoint)
                                        │  votes.db  (SQLite, on the container's
                                        │             ephemeral local disk)
                                        ▼
                             GitHub Contents API
                             az-fkaw/Jukebox_LIVE
                             jukeboxHeroes-v2/backups/backup-votes.db

There is no database server. **The durable store is a SQLite file committed to
GitHub.** The container holds the only writable copy.

### Cold start
`voting.py:20` and `admin.py:25` both do: if `votes.db` is missing, call
`init_empty_db()` (`database.py:45`), which

1. `download_database_from_github()` — GET the backup blob via the Contents API,
   base64-decode it to `./backups/backup-votes.db` (`gh_utils.py:11`);
2. if `votes.db` still does not exist, `CREATE TABLE IF NOT EXISTS` × 9;
3. `restore_from_backup()` — `shutil.copy` the downloaded file over `votes.db`.

Step 3 runs unconditionally, so the freshly created empty tables from step 2 are
immediately overwritten by whatever GitHub had. That is intentional and works.

### Warm operation
Every read and write opens a new `sqlite3.connect('votes.db')`, runs one
statement, and closes. There is no connection pool, no transaction spanning more
than one statement, and no WAL mode.

### Persistence back to GitHub
`backup_and_upload()` (`gitHubControl.py:86`) copies `votes.db` to
`jukeboxHeroes-v2/backups/backup-votes.db`, base64-encodes it, fetches the
current blob SHA, and PUTs a commit to `main` via the Contents API.

**It is called from exactly one place:** the "Backup now" button on the admin
page (`admin.py:313`). `voting.py:6` imports it and never calls it.

Consequence: votes survive only if a human presses a button before the container
recycles. See [03-findings.md#f1](03-findings.md) — this has already cost data.

---

## 3. Routing

`index.py` is the whole router, 21 lines:

```
if st.query_params:
    if st.query_params["admin"] == "Boss":   -> admin_page()
    elif st.query_params["admin"] == "Band": -> band_page()
else:
    voting_page()
```

| URL | Page | Auth |
|---|---|---|
| `/` | Voting page (or splash) | none — public, by design |
| `/?admin=Boss` | Admin console | username + password |
| `/?admin=Band` | Band setlist display | **none** |
| `/?anything=else` | **Crash** (`KeyError: 'admin'`) | — |

The `?admin=Band` page is reachable by anyone who guesses the string. The
crash on any other query parameter fires on ordinary links (`?utm_source=`,
`?fbclid=`) — a QR code or Facebook share can hand attendees a stack trace.

---

## 4. The attendee journey (`voting.py`)

1. `get_active_event()` — `SELECT ... FROM events WHERE voting_active = 1`,
   takes the first row. If none, `display_splash_screen()` renders the band's
   contact card plus an optional full repertoire listing, and stops.
2. Free-text name box. Empty name → warning, stop. **No validation, no
   uniqueness, no identity.** The name is the only voter identifier.
3. `st.session_state['voted_rounds']` — a per-websocket-connection dict of
   `{event_id: [round, ...]}`. If the current round is present, show
   "thank you" and stop. Lost on refresh, new tab, or reconnect.
4. `fetch_songs_for_voting(event_id)` — called with no `round_id`, so it takes
   the branch that ignores rounds entirely and returns every song where
   `played = 0 AND removed = 0` for the event (`song_control.py:242`).
5. `max_votes` is read from `rounds` for `(event_id, current_round)`; if no row
   exists it defaults to 5. **No `rounds` row exists for any live event**, so
   every production event has silently used 5 — the admin UI's "Set maximum
   votes" control writes a row, but only when the admin visits that screen.
6. Checkbox loop. Once `selected_count >= current_max_votes`, the loop **stops
   rendering checkboxes** instead of disabling them — the remaining songs vanish
   from the page. See [03-findings.md#f4](03-findings.md).
7. "Odešli hlasy!" → `submit_votes()` (`voting_control.py:144`): for each
   selected song, `SELECT COUNT(*)` for an existing identical vote, then
   `INSERT` if absent. Then mark the round as voted in session state, balloons,
   `st.rerun()`.

`submit_votes` receives `current_round` (a round **number**) and stores it in
`votes.round_id`, a column whose foreign key declares `rounds(id)`. The two are
not the same thing.

---

## 5. The admin journey (`admin.py`)

Gate: `st.session_state['logged_in']`, set by `login_control.handle_login()`
after comparing `sha256(password)` against `admin_users.password_hash`. Unsalted,
no iteration count, no rate limit, no lockout, no session expiry. One user
exists: `marek`.

Sidebar with seven screens:

| Screen | What it does |
|---|---|
| **Master song list** | Lists `songs`. Upload CSV with `Author;Song` columns (semicolon-delimited) → `add_song()` per row, skipping title+artist duplicates. "Delete all songs from DB" wipes `songs` without touching `event_songs`, orphaning every assignment. |
| **Event Management** | Tab 1 creates an event (name, date `DD.MM.YYYY` as **text**, round count 1–10) then calls `add_all_songs_to_event()`. Tab 2 deletes an event plus its `event_songs` and `votes`. |
| **Song management for events** | Single-round: multiselect to set `removed = 1`, and to set it back to 0. Multi-round: four tabs — remove, mark played, assign remaining songs to round *n+1*, per-round overview. |
| **Voting Control** | Selects a round, sets `rounds.max_votes`, and starts/stops voting. Start writes `round_status = 'ongoing'`, `voting_active = 1`. Stop writes `'completed'`, `0`. On a completed non-final round it auto-advances `voting_round`; on the final round it sets `last_round = 1`. |
| **Results** | `results.py` — votes joined to songs, grouped by event and round, ranked by count, one expander per event. |
| **Band page control** | A single free-text blob in `band_page_content`, rendered at `/?admin=Band` with `unsafe_allow_html=True`. |
| **Data Backup** | The "Backup now" button. The only durable-persistence trigger in the system. |

Note the "Download backup" button at `admin.py:316` is nested **inside** the
`if st.button("Backup now")` block, so it appears for one rerun and disappears
on the next interaction.

---

## 6. Event state: five fields, two competing round counters

`events` carries all live state:

| Column | Written by | Read by | Meaning |
|---|---|---|---|
| `voting_active` | `start_voting`, `stop_voting`, `update_voting_state`, and three inline `UPDATE`s in `admin.py` | `voting.py:14` | Is this event the one accepting votes? |
| `current_round` | `song_control.py:198`, `update_voting_state` | `voting.py`, `song_control.py` | Which round the **song assignment** UI is editing |
| `voting_round` | `admin.py:248` | `admin.py` | Which round **voting** is on |
| `round_status` | `admin.py:236/248/269` | `admin.py` | `not_started` / `ongoing` / `completed` |
| `last_round` | `admin.py:257` | nothing | Written, never read |

`current_round` and `voting_round` are distinct counters advanced by different
screens, and the attendee page reads `current_round` while the admin's voting
controls drive `voting_round`. In a multi-round event they drift. Every live
event so far has been single-round, which is why this has not yet broken in
production.

Mutation paths for `voting_active` alone: `database.update_voting_state()`,
`database.start_voting()`, `database.stop_voting()`, plus three inline SQL
statements in `admin.py`. `voting_control.py` contains a second, parallel
implementation (`manage_single_round`, `manage_rounds`) that is **never
reached** — `admin.py` does not call `voting_control()`.

---

## 7. Production usage to date

Eight events, 2025-11-29 → 2026-06-19. All `round_count = 1`.

| event | date | votes | voters |
|---|---|---|---|
| 20251129 Oslava Rychvald | 29.11.2025 | 5 | 1 |
| TEST | 12.01.2026 | 10 | 2 |
| 20260116_ERUNI | 16.01.2026 | 30 | 6 |
| 20260124 KOPR | 24.01.2026 | 0 | 0 |
| 20260129 Celnice Straub | 29.01.2026 | 0 | 0 |
| 29260131 Kynologove Petrwald | 31.01.2026 | 0 | 0 |
| 20260604 Hyskov | 04.06.2026 | 0 | 0 |
| 20260619 KRPOLE | 19.06.2026 | 0 | 0 |

Five events were created and carry zero votes. Either they were set up and never
run, or their votes were lost because nobody pressed "Backup now" before the
container recycled. The system keeps no record that would tell us which — there
is no audit log. That ambiguity is itself the finding.

Every voter cast exactly 5 votes, consistent with the `max_votes` default of 5
and with no `rounds` row ever being written for these events.

Git history: 415 commits, **92 of them** are `Backup SQLite database` — the
database writing to its own source repository.

---

## 8. Dead and duplicated code

- `database.store_vote()` (`database.py:214`) inserts into columns
  `uniqueID, randomNumber` that do not exist in the `votes` table. It is a v1
  leftover and would raise `OperationalError` if called. Nothing calls it.
- `database.fetch_votes()`, `database.fetch_played_songs()`,
  `database.mark_song_as_played()`, `database.create_round()`,
  `database.assign_song_to_event()`, `database.get_songs_for_event()`,
  `database.update_song()`, `database.add_voting_state_to_events()`,
  `database.remove_all_songs_from_event()` — no call sites.
- `song_control.display_song_selection()`, `export_votes_to_csv()`,
  `export_songs_to_csv()`, `get_song_name()`, `check_songs_exist()` (defined
  *inside* `song_management`, unreachable) — no call sites.
- `voting_control.voting_control()` has no call sites; `manage_single_round()`
  and `manage_rounds()` are called only from it. The whole multi-round control
  cluster is unreachable — `admin.py` reimplements it inline instead.
- `mark_song_as_played` is **defined twice** with different signatures:
  `database.py:234` takes `(song_id, event_id, round_id)` and writes
  `played_songs`; `song_control.py:371` takes `(event_id, song_id)` and writes
  `event_songs.played`. `admin.py` does `from database import *` followed by
  `from song_control import *`, so the second wins by import order. Reorder the
  imports and the app silently writes to the wrong table.
- Every module uses wildcard imports (`from database import *`). There are five
  independent `DATABASE = 'votes.db'` constants.
- `played_songs` (0 rows) and `admin_settings` (0 rows) are created and never
  used. `event_songs.played` is the real "played" flag.
