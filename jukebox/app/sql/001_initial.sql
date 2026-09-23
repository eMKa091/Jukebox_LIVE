-- Jukebox LIVE schema, version 1.
--
-- Design rules, each one traceable to a finding in ../../docs/03-findings.md:
--
--   * Every dedup rule that used to be a SELECT-then-INSERT in Python is a
--     constraint here instead. The old code checked for an existing vote and
--     then inserted it, which is a race (F6).
--   * Rounds are never optional. A single-round event is an event with exactly
--     one round. The legacy event_songs.round_id was NULL in all 896 rows,
--     which silently disabled its own PRIMARY KEY (F7's cousin).
--   * Nothing is ever hard-deleted that another row points at. "Delete all
--     songs" used to orphan every assignment (F10).
--   * Timestamps are ISO-8601 UTC strings, sortable as text. The legacy
--     DD.MM.YYYY sorted 01.12.2025 before 29.11.2025 (F15).

CREATE TABLE songs (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL CHECK (trim(title) <> ''),
    artist      TEXT NOT NULL CHECK (trim(artist) <> ''),
    retired_at  TEXT            -- soft delete; retired songs stay joinable
);

-- Case-insensitive uniqueness, enforced by the database rather than by
-- add_song()'s SELECT COUNT(*) which two uploads could interleave through.
CREATE UNIQUE INDEX songs_unique ON songs (lower(artist), lower(title));


CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (trim(name) <> ''),
    slug        TEXT NOT NULL UNIQUE,   -- the QR code target: /e/{slug}
    venue       TEXT NOT NULL DEFAULT '',
    starts_at   TEXT NOT NULL,          -- ISO-8601 UTC
    state       TEXT NOT NULL DEFAULT 'draft'
                CHECK (state IN ('draft', 'ready', 'live', 'closed')),
    created_at  TEXT NOT NULL
);

-- At most one event may be live at a time. This single index replaces
-- update_voting_state()'s "find the other active event and stop it" scan,
-- which raced and reported the stop through a warning nobody reads.
CREATE UNIQUE INDEX one_live_event ON events (state) WHERE state = 'live';


CREATE TABLE rounds (
    id          INTEGER PRIMARY KEY,
    event_id    INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL CHECK (ordinal >= 1),
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'open', 'closed')),
    max_votes   INTEGER NOT NULL DEFAULT 5
                CHECK (max_votes BETWEEN 1 AND 50),
    opened_at   TEXT,
    closed_at   TEXT,
    UNIQUE (event_id, ordinal)
);

-- At most one round per event may be open. Together with one_live_event this
-- is the whole of what the legacy voting_active / current_round / voting_round
-- / round_status / last_round columns were trying to express across six
-- scattered call sites (F7).
CREATE UNIQUE INDEX one_open_round ON rounds (event_id) WHERE state = 'open';


CREATE TABLE round_songs (
    round_id    INTEGER NOT NULL REFERENCES rounds (id) ON DELETE CASCADE,
    song_id     INTEGER NOT NULL REFERENCES songs (id),
    excluded    INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
    played_at   TEXT,           -- set when the band actually plays it
    PRIMARY KEY (round_id, song_id)
);


CREATE TABLE voters (
    id            TEXT PRIMARY KEY,     -- uuid4 hex
    event_id      INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    display_name  TEXT NOT NULL CHECK (trim(display_name) <> ''),
    device_token  TEXT NOT NULL,        -- httpOnly cookie; the real identity
    created_at    TEXT NOT NULL,
    UNIQUE (event_id, device_token)
);

-- One voter per device per event is the point of the UNIQUE above. The legacy
-- system keyed on a free-text name, so a refresh bought a fresh ballot and the
-- live data contains both "Martin" and "Martin " (F6).


CREATE TABLE votes (
    id          INTEGER PRIMARY KEY,
    round_id    INTEGER NOT NULL REFERENCES rounds (id) ON DELETE CASCADE,
    voter_id    TEXT NOT NULL REFERENCES voters (id) ON DELETE CASCADE,
    song_id     INTEGER NOT NULL REFERENCES songs (id),
    ballot_id   TEXT NOT NULL,          -- client-generated; makes retry safe
    cast_at     TEXT NOT NULL,
    UNIQUE (round_id, voter_id, song_id)
);

CREATE INDEX votes_round_song ON votes (round_id, song_id);
CREATE INDEX votes_ballot ON votes (ballot_id);


CREATE TABLE band_notes (
    event_id    INTEGER PRIMARY KEY REFERENCES events (id) ON DELETE CASCADE,
    body        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);


CREATE TABLE admin_users (
    id             INTEGER PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash  TEXT NOT NULL,       -- argon2id
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);


-- Append-only. Never UPDATEd, never DELETEd.
--
-- This table exists because of a question nobody could answer about the legacy
-- system: five of its eight events hold zero votes, and there is no way to tell
-- whether they were never run or whether the data was lost. Every state
-- transition writes a row here so that question is always answerable.
CREATE TABLE event_log (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL,
    actor     TEXT NOT NULL,            -- admin username, or 'system'
    action    TEXT NOT NULL,            -- 'round.open', 'song.played', ...
    event_id  INTEGER,
    payload   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX event_log_event ON event_log (event_id, id);
