# 02 — Data model, as built and as proposed

## Part A — What is in the database today

Source: `jukeboxHeroes-v2/backups/backup-votes.db`, 86 KB, nine tables.

```
events ──┬─< event_songs >── songs
         ├─< votes
         ├─< rounds
         └─< played_songs        (0 rows, dead)

admin_users        (1 row)
admin_settings     (0 rows, dead)
band_page_content  (0 rows)
```

### `events` — 8 rows
`id, name, date TEXT, round_count, current_round, voting_round, voting_active,
round_status TEXT, last_round`

`date` is a `DD.MM.YYYY` string, so it sorts lexically, not chronologically.
The five state columns are analysed in [01-as-built.md §6](01-as-built.md).

### `songs` — 112 rows
`id, title, artist`. No uniqueness constraint; `add_song()` enforces it in
Python with a `SELECT COUNT(*)` first, which is a race under concurrency.

### `event_songs` — 896 rows (8 events × 112 songs)
`PRIMARY KEY (event_id, song_id, round_id)` plus `played`, `removed` flags.

**`round_id` is NULL in all 896 rows.** SQLite permits NULLs in PRIMARY KEY
columns (a documented legacy deviation from the standard), so the primary key
enforces nothing here. The same `(event, song)` pair can be inserted repeatedly.

`add_all_songs_to_event()` guards against this with a `SELECT COUNT(*)` using
`round_id IS NULL`, but `assign_remaining_songs_to_next_round()` uses
`round_id = ?`, which never matches a NULL — so the multi-round path would
duplicate rows rather than skip them.

### `votes` — 45 rows
`id, user_id TEXT, song TEXT, event_id, round_id, date TEXT`

Three separate type problems:

1. `song` is `TEXT` holding a numeric song id. `results.py` joins
   `ON v.song = s.id` against an `INTEGER` column. This **works** — SQLite
   applies numeric affinity across the comparison — but it is accidental, and it
   will not survive a move to Postgres, which rejects `text = integer` outright.
2. `round_id` holds a round **number** (always `1` in production), while its
   foreign key declares `rounds(id)`. The `rounds` table's only row has
   `id = 1, event_id = 1` for an event that no longer exists.
3. `date` is `DATE('now')` — a UTC date string, no time, no timezone. Two
   rounds on the same night are indistinguishable by timestamp.

No unique constraint. Duplicate suppression is a `SELECT` then `INSERT` in
`voting_control.submit_votes()`, which is a check-then-act race.

### `rounds` — 1 row
`id, event_id, round_number, max_votes DEFAULT 5, description`

A row is written only when an admin changes "maximum votes" on the Voting
Control screen. No live event has one, so every live event ran on the hardcoded
fallback of 5 in `voting.py:60`.

### `admin_users` — 1 row
`marek`, unsalted SHA-256, role `admin`. The `role` column is never read.

### Dead tables
`played_songs` (0 rows — superseded by `event_songs.played`) and
`admin_settings` (0 rows — never written).

### Identity
There is none. A voter is a free-text string the attendee types. `Martin` and
`Martin ` (trailing space) are two different voters in the live data, as are
`Kristyna` and `Kristyna `. Anyone can vote as anyone.

---

## Part B — Proposed schema (PostgreSQL)

Design rules applied:

- **One source of truth per fact.** Round state lives in `rounds`, not in five
  columns on `events`.
- **Invariants in the database, not in Python.** Every dedup rule that is
  currently a `SELECT COUNT(*)` becomes a constraint.
- **Rounds are never optional.** A single-round event is an event with exactly
  one round. That deletes the entire `round_id IS NULL` branch class.
- **Append-only history.** A live gig that misbehaves must be explainable
  afterwards.

```sql
CREATE TYPE event_state AS ENUM ('draft','ready','live','closed');
CREATE TYPE round_state AS ENUM ('pending','open','closed');

CREATE TABLE songs (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title       text NOT NULL,
  artist      text NOT NULL,
  retired_at  timestamptz,                    -- soft delete, never DELETE
  UNIQUE (lower(artist), lower(title))
);

CREATE TABLE events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL,
  venue       text,
  starts_at   timestamptz NOT NULL,           -- real timestamp, not DD.MM.YYYY
  state       event_state NOT NULL DEFAULT 'draft',
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- At most one live event at a time, enforced by the database:
CREATE UNIQUE INDEX one_live_event ON events ((state)) WHERE state = 'live';

CREATE TABLE rounds (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id    bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  ordinal     int NOT NULL CHECK (ordinal >= 1),
  state       round_state NOT NULL DEFAULT 'pending',
  max_votes   int NOT NULL DEFAULT 5 CHECK (max_votes BETWEEN 1 AND 50),
  opened_at   timestamptz,
  closed_at   timestamptz,
  UNIQUE (event_id, ordinal)
);
-- At most one open round per event:
CREATE UNIQUE INDEX one_open_round ON rounds (event_id) WHERE state = 'open';

CREATE TABLE round_songs (
  round_id    bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
  song_id     bigint NOT NULL REFERENCES songs(id),
  excluded    boolean NOT NULL DEFAULT false,  -- admin removed it from this round
  played_at   timestamptz,                     -- band played it
  PRIMARY KEY (round_id, song_id)
);

CREATE TABLE voters (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id     bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  device_token uuid NOT NULL,                  -- httpOnly cookie, the real identity
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_id, device_token)
);

CREATE TABLE votes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id   bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
  voter_id   uuid   NOT NULL REFERENCES voters(id) ON DELETE CASCADE,
  song_id    bigint NOT NULL REFERENCES songs(id),
  cast_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, voter_id, song_id)         -- dedup is now an invariant
);
CREATE INDEX votes_round_song ON votes (round_id, song_id);

CREATE TABLE band_notes (
  event_id   bigint PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
  body       text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE admin_users (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username      citext UNIQUE NOT NULL,
  password_hash text NOT NULL,                 -- argon2id
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

CREATE TABLE event_log (                        -- append-only; never updated
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at         timestamptz NOT NULL DEFAULT now(),
  actor      text NOT NULL,                     -- admin username or 'system'
  action     text NOT NULL,                     -- 'round.open', 'song.played', ...
  event_id   bigint,
  payload    jsonb NOT NULL DEFAULT '{}'
);
```

### What each change buys

| Change | Removes |
|---|---|
| `one_live_event` partial unique index | `update_voting_state()`'s "stop the other event" scan, and the silent-warning race behind it |
| `one_open_round` partial unique index | The `voting_active` / `voting_round` / `round_status` drift |
| Rounds mandatory | Every `round_id IS NULL` code path (two query variants per lookup) |
| `votes UNIQUE (round_id, voter_id, song_id)` | The check-then-act dedup race |
| `voters.device_token` | Vote-as-anyone; makes one-vote-per-device real |
| `starts_at timestamptz` | `DD.MM.YYYY` text sorting |
| `event_log` | The "did event 11 have zero votes, or did we lose them?" ambiguity |
| `songs.retired_at` | "Delete all songs from DB" orphaning 896 assignment rows |

### Cardinality reality check
112 songs, ~10 events/year, ≤300 voters/event × ≤10 votes. That is **under
30,000 rows/year**. Postgres is chosen for correctness and concurrency, not
scale. Any instance size will do; the smallest one will do for a decade.
