-- Jukebox LIVE schema, version 2: failed sign-ins, for the throttle in
-- domain/identity.py.
--
-- In a table, not in process memory, because on Cloudflare the app runs in a
-- Durable Object that is emptied whenever it sleeps, which it may do between
-- two guesses (docs/08-cloudflare-port.md, step 6.3). Rows older than the
-- window are deleted as new ones arrive.

CREATE TABLE login_failures (
    client  TEXT NOT NULL,      -- the caller's address, as security.client_address reads it
    at      REAL NOT NULL       -- Unix time in seconds
);

CREATE INDEX login_failures_client ON login_failures (client, at);
