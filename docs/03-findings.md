# 03 — Findings

Every entry was verified against the source or the shipped database. Severity is
"what happens at a gig", not abstract code quality.

| # | Severity | Finding |
|---|---|---|
| F1 | **Critical** | Votes are persisted only when an admin presses a button |
| F2 | High | A repo-write GitHub token lives inside the web app |
| F3 | High | The band page is unauthenticated and renders raw HTML |
| F4 | High | Hitting the vote limit makes the rest of the song list disappear |
| F5 | High | Any unexpected query parameter crashes the app |
| F6 | High | No voter identity — a refresh buys another ballot |
| F7 | Medium | Two competing round counters that drift apart |
| F8 | Medium | Unsalted SHA-256 admin password, no rate limiting |
| F9 | Medium | SQLite under concurrent writes is untested above 6 voters |
| F10 | Medium | "Delete all songs" orphans every event assignment |
| F11 | Medium | `mark_song_as_played` correctness depends on import order |
| F12 | Low | The "Download backup" button is effectively unreachable |
| F13 | Low | ~40% of the codebase has no call sites |
| F14 | Low | `votes.song` joins to `songs.id` only by SQLite type coercion |
| F15 | Low | Event dates are `DD.MM.YYYY` strings |
| F16 | Low | The database commits itself to its own source repository |
| F17 | Low | The devcontainer still launches the v1 prototype |

---

## F1 — Votes are persisted only when an admin presses a button
**Critical.** `gitHubControl.py:86`, called from `admin.py:313` only.

The container's `votes.db` is the only writable copy. It is pushed to GitHub
solely by the "Backup now" button on the Data Backup screen. Streamlit Cloud
recycles containers on idle, redeploy, or platform maintenance. Any votes cast
between the last button press and a recycle are gone, silently, with no error
and no trace.

`voting.py:6` imports `backup_and_upload` and never calls it — the intent was
clearly there and was never wired up.

Evidence: five of eight production events hold zero votes
([01-as-built.md §7](01-as-built.md)). The system records nothing that would
distinguish "the event never ran" from "we lost the votes", because there is no
audit log. That ambiguity is the point — you cannot currently answer the
question.

*Interim fix, if any gig happens before the rewrite:* call `backup_and_upload()`
at the end of `submit_votes()` in `voting_control.py:162`, or at minimum inside
the "Stop voting" handler at `admin.py:239`. One line each. The stop-voting
placement costs one GitHub commit per round instead of one per voter.

## F2 — A repo-write GitHub token lives inside the web app
**High.** `gh_utils.py:6`, `gitHubControl.py:13`.

`GITHUB_TOKEN` must carry `contents:write` on `az-fkaw/Jukebox_LIVE` for the
backup to function. It sits in the environment of a public-facing app whose
admin gate is a magic query string plus an unsalted password hash. Compromise of
the app is compromise of the repository.

No token literal appears anywhere in git history — that was checked and the
history is clean. The exposure is runtime, not committed.

Also note `gh_utils.py:7` targets `az-fkaw/Jukebox_LIVE` while this clone's
origin is `eMKa091/Jukebox_LIVE`. Confirm which repository the deployment
actually writes to before touching either.

## F3 — The band page is unauthenticated and renders raw HTML
**High.** `index.py:18`, `band.py:24`.

`/?admin=Band` requires no login. Its content comes from `band_page_content`,
is passed through `st.markdown(..., unsafe_allow_html=True)`, and is written by
the admin. Today only an admin can write it, so this is stored-XSS-shaped rather
than stored XSS. It becomes exploitable the moment anything else can write that
table.

The page also leaks the full setlist to anyone who guesses the string `Band`.

## F4 — Hitting the vote limit makes the rest of the song list disappear
**High.** `voting.py:72-84`.

```python
if selected_count >= current_max_votes:
    limit_reached = True
    is_selected = False          # <- no checkbox is rendered at all
else:
    is_selected = st.checkbox(...)
```

Once an attendee ticks their fifth song, every song **below** it in the list
stops rendering. From the attendee's side the page appears to have lost half the
repertoire. They cannot deselect and reconsider a song further down, because it
is no longer on the page.

The intended behaviour — render the checkbox `disabled` — already exists in
`song_control.display_song_selection()` at line 289, which has no call sites.
The correct implementation was written and never wired in.

This is the single worst thing an attendee experiences, and it fires for every
attendee who reaches the limit, which is every attendee who votes.

## F5 — Any unexpected query parameter crashes the app
**High.** `index.py:15-19`.

```python
if st.query_params:
    if st.query_params["admin"] == "Boss":
```

The guard tests whether *any* parameter exists, then indexes `"admin"`
unconditionally. `/?utm_source=facebook`, `/?fbclid=...`, or any tracked or
shortened link raises `KeyError: 'admin'` and shows attendees a stack trace
instead of the voting page. Sharing the link through Facebook or Messenger — the
obvious distribution channel for a band — is enough to trigger it.

## F6 — No voter identity
**High.** `voting.py:33`, `voting_control.py:144`.

Identity is a free-text name box. The one-vote-per-round guard is
`st.session_state['voted_rounds']`, which lives in the websocket session and
dies on refresh, tab switch, or reconnect on flaky venue wifi.

Refresh → new session → vote again. The only backstop is the `SELECT COUNT(*)`
dedup on `(user_id, song, event_id, round_id)`, so a second ballot for *different*
songs is accepted in full. The live data already contains `Martin` and `Martin `
as separate voters.

A vote result that can be moved by a bored attendee with a refresh button is not
a result the band can act on.

## F7 — Two competing round counters
**Medium (latent).** `events.current_round` vs `events.voting_round`.

`current_round` is advanced by the song-management screen (`song_control.py:198`)
and read by the attendee page (`voting.py:29`). `voting_round` is advanced by the
voting-control screen (`admin.py:248`) and read only there. In a multi-round
event they diverge, and the attendee page then reads `max_votes` for the wrong
round while voting is open for another.

Not yet observed in production because all eight live events were single-round.
It will fire the first time a multi-round event is run.

## F8 — Unsalted SHA-256 admin password, no rate limiting
**Medium.** `login_control.py:6-12`, `database.py:168`.

`sha256(password)` with no salt, no work factor, no attempt limit, no lockout,
no session expiry. The one stored hash is a single rainbow-table lookup away if
the database blob is ever read — and the database blob is a public file in a
GitHub repository.

## F9 — SQLite under concurrent writes is untested above 6 voters
**Medium.** All modules.

Every operation opens its own `sqlite3.connect()`, runs one statement, and
closes. No WAL mode, so writers take an exclusive lock on the whole file.
Streamlit serves each browser session on its own thread, so N attendees pressing
submit at the same moment are N concurrent writers with the 5-second default
busy timeout.

Peak observed concurrency in production is **6 voters**. Nothing has broken. But
"works at 6" is not evidence for 200, and a `database is locked` exception at a
gig is unrecoverable in the moment.

## F10 — "Delete all songs" orphans every event assignment
**Medium.** `admin.py:82`, `database.py:464`.

`remove_all_songs()` runs `DELETE FROM songs` with no cascade and no check. The
896 rows in `event_songs` keep pointing at song ids that no longer exist. The UI
does warn ("Do not delete songs if you have any events to manage") — the
destructive operation is one unguarded click behind that warning.

## F11 — `mark_song_as_played` correctness depends on import order
**Medium.** `database.py:234` and `song_control.py:371`.

Two functions, same name, different signatures, different target tables.
`admin.py` does `from database import *` (line 5) then `from song_control import *`
(line 6), so `song_control`'s version — the correct one, writing
`event_songs.played` — wins. Swapping those two import lines silently redirects
every "mark as played" to the dead `played_songs` table, and nothing raises.

## F12 — The "Download backup" button is effectively unreachable
**Low.** `admin.py:311-317`.

`st.download_button("Download backup", ...)` is nested inside
`if st.button("Backup now")`, so it renders for exactly one script run and
vanishes on the next interaction. The local-download escape hatch does not work.

## F13 — ~40% of the codebase has no call sites
**Low.** Fourteen functions and one whole module cluster, enumerated in
[01-as-built.md §8](01-as-built.md). Combined with five wildcard imports and
five copies of `DATABASE = 'votes.db'`, the reachable program is hard to
separate from the abandoned one by reading.

## F14 — `votes.song` joins to `songs.id` only by type coercion
**Low now, blocking at migration.** `results.py:27`.

`votes.song` is declared `TEXT`; `songs.id` is `INTEGER`. SQLite applies numeric
affinity across the comparison, so the results screen works today. Postgres
rejects `text = bigint`. Any migration must cast explicitly and verify that
every value converts — see [06-migration-plan.md](06-migration-plan.md) gate G2.

## F15 — Event dates are `DD.MM.YYYY` strings
**Low.** `admin.py:108`. Sorts lexically. `01.12.2025` precedes `29.11.2025`.

## F16 — The database commits itself to its own source repository
**Low.** 92 of 415 commits are `Backup SQLite database`, and `votes.db` appears
in 99 commits across history. Code archaeology means reading past the database's
own write log.

## F17 — The devcontainer still launches the v1 prototype
**Low.** `.devcontainer/devcontainer.json` runs
`streamlit run webpage_source/Uvod.py` and opens `webpage_source/Uvod.py`. A new
contributor gets the abandoned 2024 prototype.
