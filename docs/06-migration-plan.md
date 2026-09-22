# 06 — Migration plan

Ten phases. Each has a **gate** — a thing that must be demonstrably true before
the next phase starts. Estimates are working days for one person who already
knows the domain.

**Total: ~13–16 working days.** The rewrite itself is about six of those. The
rest is migration, rehearsal and cutover, and skipping them is how a live show
breaks.

---

## Phase 0 — Stop the bleeding *(1 hour — only if a gig happens before cutover)*

Do not refactor. Two changes to the running Streamlit app:

1. Call `backup_and_upload()` in the "Stop voting" handler (`admin.py:239`).
   One commit per round instead of one per voter. This is [F1](03-findings.md).
2. Guard the router: `if st.query_params.get("admin") == "Boss"`. This is
   [F5](03-findings.md), and it is one word.

Optionally also [F4](03-findings.md) — render the checkbox `disabled` instead of
skipping it. It is three lines and it is the worst thing attendees hit.

**Gate G0:** a test event, voted from two phones, votes present in the GitHub
backup blob after "Stop voting" and without touching "Backup now".

**Skip this phase entirely if no gig is scheduled before cutover.** Do not
invest anywhere else in this codebase.

---

## Phase 1 — Freeze and document *(done)*

This branch. `docs/01`–`06`. No further behavioural change to `jukeboxHeroes-v2/`.

**Gate G1:** behaviour map reviewed by you and agreed as accurate. Anything I
got wrong gets corrected here before anything is built on top of it.

---

## Phase 2 — Schema and data migration *(1.5 days)*

Alembic migration producing the schema in [02-data-model.md](02-data-model.md),
plus `scripts/migrate_sqlite.py` that reads the real
`jukeboxHeroes-v2/backups/backup-votes.db` and loads Postgres.

Mapping decisions that need a call from you:

| Old | New | Decision |
|---|---|---|
| `votes.user_id` (free text, incl. `Martin` / `Martin `) | `voters.display_name` | Trim whitespace, then treat identical trimmed names within one event as the same voter. **Confirm.** |
| `votes.round_id` = round *number* | `rounds.id` | Synthesise one `rounds` row per event (`ordinal = 1`, `max_votes = 5`). All eight live events are single-round. |
| `events.date` `DD.MM.YYYY` | `starts_at timestamptz` | Parse as 20:00 Europe/Prague. Times were never recorded; this is a stated assumption, not a recovery. |
| `event_songs` with `round_id IS NULL` | `round_songs` | Attach to that event's synthesised round 1. |
| `played_songs`, `admin_settings` | — | Dropped. Zero rows. |
| The 5 zero-vote events (11–15) | migrated as `closed`, zero votes | Preserved as-is. We cannot recover what was never written. |

**Gate G2 — all four must pass, in CI, against the real backup file:**
- Row counts: 8 events, 112 songs, 45 votes, 9 distinct voters.
- Every `votes.song` value resolves to a `songs.id`. Zero orphans.
  (Today this join works only by SQLite type coercion — [F14](03-findings.md).)
- Per-event vote tallies are byte-identical to the old `results.py` output.
- The script is idempotent: running it twice yields the same database.

---

## Phase 3 — Domain core *(2.5 days)*

`app/domain/` — event and round transitions, ballot submission, tallying. No
HTTP, no templates. Tests first; this is where the product's rules live and it
is the part the current codebase cannot test at all.

**Gate G3:**
- Every legal transition has a test. Every *illegal* transition has a test that
  asserts rejection (open a round on a `closed` event; vote into a `pending`
  round; two rounds open at once).
- Concurrency: two simultaneous `open_round` calls on the same event → one
  succeeds, one gets a clean 409. Asserted against a real Postgres, not a mock.
- Ballot idempotency: the same ballot UUID submitted twice produces one set of
  votes.
- `event_log` has a row for every transition.

---

## Phase 4 — Attendee experience *(2 days)*

Ballot page, splash, SSE stream, device cookie, QR entry at `/e/{slug}`.

**Gate G4:**
- At the vote limit the remaining songs are `disabled` and visible, never
  removed ([F4](03-findings.md)).
- Reload mid-ballot: ticks restored from `sessionStorage`.
- Reload after submitting: "already voted" comes from the server, not a session
  variable ([F6](03-findings.md)).
- Kill the network for 30 seconds with the page open: SSE reconnects on its own
  and the ballot still submits.
- Lighthouse mobile performance ≥ 90; first contentful paint under 1.5 s on
  throttled 3G.

---

## Phase 5 — Admin console *(2.5 days)*

Login, events, rounds, song assignment, live results, CSV export, QR generation,
band-link management.

**Gate G5 — feature parity, checked item by item against
[01-as-built.md §5](01-as-built.md):**

| Old capability | Must exist |
|---|---|
| CSV song upload (`Author;Song`) | yes — plus a preview before commit |
| Master song list | yes — with soft delete, not `DELETE FROM songs` ([F10](03-findings.md)) |
| Create / delete event | yes |
| Include / exclude songs per round | yes |
| Mark songs played | yes |
| Start / stop voting | yes — as state transitions |
| Set max votes per round | yes — and defaulted visibly, not silently to 5 |
| Multi-round events | yes — with one round counter, not two ([F7](03-findings.md)) |
| Results per event and round | yes — live, updating as votes land |
| Band page content | yes — and a live ranking, which is what the band actually wants |
| Backup / export | yes — CSV always available ([F12](03-findings.md)), plus automatic per-event dump |

Also: argon2id password, rate-limited login, session expiry ([F8](03-findings.md)).

---

## Phase 6 — Band display *(0.5 day)*

`/band/{signed-token}` — live ranking, what has been played, what is next.
Auto-updating, designed to be readable at arm's length on a tablet in stage
lighting. Replaces the free-text blob and closes [F3](03-findings.md).

**Gate G6:** opening the URL with a tampered token returns 403. Nothing renders
unescaped HTML.

---

## Phase 7 — Deploy, backup, observe *(1 day)*

Fly app + Postgres in `waw`, `min_machines_running = 1`, domain, TLS, secrets.
Nightly `pg_dump` to object storage; automatic dump + CSV on `event.closed`.
Structured logs, `/healthz`, `/readyz`, and an alert if the app is down.

**Gate G7 — the restore drill. This is non-negotiable:**
Drop the production database, restore it from last night's dump, confirm all 45
migrated votes are present. Write down how long it took. If you have not
restored a backup, you do not have backups.

---

## Phase 8 — Load and dress rehearsal *(1 day)*

- **Load:** 300 simulated clients, one round, all submitting within 30 seconds.
  Zero errors, p95 under 500 ms, and every vote present afterwards. This is the
  test the current stack has never had ([F9](03-findings.md)).
- **Dress rehearsal:** the band, in a room, with their own phones, on mobile
  data — not office wifi. Marek runs the admin console cold, without help. Where
  he hesitates is a UI bug, not a training gap.

**Gate G8:** a full event run end to end by the band, with no developer
intervention, including one round opened, closed, and results shown.

---

## Phase 9 — Cutover *(at the next low-stakes event)*

- Migrate production data again, from a fresh backup blob taken that day.
- Point the domain at the new app. Leave the Streamlit app reachable at its old
  URL, untouched, as a fallback for this one event.
- Be present, or on the phone, for the whole gig.

**Gate G9:** one real event completed on the new system, votes verified present
the following morning.

---

## Phase 10 — Decommission *(0.5 day)*

- Take down the Streamlit deployment.
- **Revoke `GITHUB_TOKEN`** ([F2](03-findings.md)) — after confirming which
  repository it actually targets.
- Move `jukeboxHeroes-v2/` and `webpage_source/` under `legacy/`, or tag the
  final commit `streamlit-final` and delete them. Tag, then delete — the history
  is the archive.
- Fix `.devcontainer/` ([F17](03-findings.md)).

---

## Risks

| Risk | Mitigation |
|---|---|
| Cutover at a high-stakes gig goes wrong | Phase 9 targets the *lowest*-stakes event on the calendar, with the old app still up |
| The band finds the new admin console unfamiliar mid-gig | Phase 8 is Marek driving it cold; his hesitations are the bug list |
| Venue wifi is worse than any test | SSE auto-reconnect, idempotent submit, ballot cached client-side. Test on real mobile data, never office wifi |
| Scope creep (Spotify, accounts, multi-band) | [04-target-architecture.md §7](04-target-architecture.md) names the out-of-scope list. Point at it |
| The rewrite stalls half-done | Phases 2–6 each leave a working, tested artefact. Nothing is a big-bang |
| Votes lost during the migration window | Phase 9 re-migrates from a same-day blob; the old app is never written to after cutover |

## Sequencing note

Phases 2 and 3 are the load-bearing ones. If the schema and the state machine
are right, phases 4–6 are ordinary UI work. If they are wrong, no amount of
frontend polish will save it — which is precisely the lesson the current
codebase is teaching, where five state columns and two round counters make the
UI impossible to reason about.
