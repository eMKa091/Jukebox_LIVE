"""Admin accounts and password handling.

The legacy scheme was sha256(password) with no salt, no work factor, no attempt
limit and no session expiry, and the resulting hash lived in a database file
committed to a public GitHub repository (F8). Argon2id replaces all of that.
"""

from __future__ import annotations

import hmac
import sqlite3
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ..db import Database, utcnow
from . import log
from .errors import Invalid, NotFound, NotPermitted

# OWASP's minimum for argon2id: 19 MiB, two passes, one lane. Not
# argon2-cffi's default of 64 MiB: on Cloudflare the app runs in one object
# with 128 MB for everything, the app alone holds 52 MiB of it, and one
# default hash grew that to 107 MiB, for good (docs/08, step 6.1). This one
# grows it by 10. Hashes made with other settings are redone at the next
# sign-in (check_needs_rehash below).
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

MIN_PASSWORD_LENGTH = 10

# Nobody has to be signed in to cause a password check, so in the container,
# where requests run side by side, the number running at once is capped; a
# caller who finds both places taken is told to try again. On the object,
# which runs one request at a time, the cap is never reached.
_hashing = threading.BoundedSemaphore(2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@dataclass
class LoginThrottle:
    """Attempt limiting per caller, kept in the database (login_failures).

    Counted against where the attempts come from, not against the username
    they name. Counted per username, eight wrong passwords from anyone, from
    anywhere, shut the band out of their own console for the window.

    In the database, not in memory: on Cloudflare the app runs in a Durable
    Object whose memory is emptied whenever it sleeps, which it may well do
    between two guesses (docs/08, step 6.3). The goal is still to stop online
    guessing, not to be a durable security control: a lockout lasts the
    window and no longer, restart or not.
    """

    db: Database
    max_attempts: int
    window_seconds: int

    def failures(self, client: str) -> list[float]:
        """When this caller failed within the window, oldest first."""
        since = time.time() - self.window_seconds
        return [
            r["at"]
            for r in self.db.read().execute(
                "SELECT at FROM login_failures WHERE client = ? AND at > ? ORDER BY at",
                (client, since),
            )
        ]

    def check(self, client: str) -> None:
        recent = self.failures(client)
        if len(recent) >= self.max_attempts:
            wait = int(self.window_seconds - (time.time() - recent[0])) // 60 + 1
            raise NotPermitted(
                f"Too many failed sign-ins. Try again in about {wait} minute(s)."
            )

    def record_failure(self, client: str) -> None:
        now = time.time()

        def work(conn: sqlite3.Connection) -> None:
            # Forget whatever has left the window, so a flood from many
            # addresses cannot grow the table without limit.
            conn.execute("DELETE FROM login_failures WHERE at <= ?", (now - self.window_seconds,))
            conn.execute("INSERT INTO login_failures (client, at) VALUES (?, ?)", (client, now))

        self.db.transact(work)

    def clear(self, client: str) -> None:
        self.db.transact(
            lambda conn: conn.execute("DELETE FROM login_failures WHERE client = ?", (client,))
        )


def create_admin(
    db: Database, *, username: str, password: str, actor: str = "system", first: bool = False
) -> int:
    """Make an account. `first=True` is the setup page's: refused if any
    account exists, checked in the same transaction that makes this one, so
    two people setting up at once cannot both succeed."""
    username = username.strip()
    if not username:
        raise Invalid("A username is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    password_hash = hash_password(password)

    def work(conn: sqlite3.Connection) -> int:
        if first and admin_count(conn):
            raise NotPermitted("An admin account already exists. Sign in instead.")
        exists = conn.execute(
            "SELECT 1 FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise Invalid(f"User {username!r} already exists.")
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, utcnow()),
        )
        log.record(conn, actor=actor, action="admin.created", username=username)
        return int(cur.lastrowid)

    return db.transact(work)


def set_password(db: Database, *, username: str, password: str, actor: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    password_hash = hash_password(password)

    def work(conn: sqlite3.Connection) -> None:
        cur = conn.execute(
            "UPDATE admin_users SET password_hash = ? WHERE username = ?",
            (password_hash, username),
        )
        if cur.rowcount == 0:
            raise NotFound(f"No such user: {username}")
        log.record(conn, actor=actor, action="admin.password_changed", username=username)

    db.transact(work)


def authenticate(
    db: Database, *, username: str, password: str, throttle: LoginThrottle, client: str = "local"
) -> str:
    """Return the username on success. Raise on failure.

    The same error text covers "no such user" and "wrong password", so the form
    does not confirm which usernames exist. `client` is whoever is asking --
    an address, in the web layer -- and is what the throttle counts against.
    """
    username = username.strip()
    throttle.check(client)

    row = db.read().execute(
        "SELECT username, password_hash FROM admin_users WHERE username = ?", (username,)
    ).fetchone()

    if not _hashing.acquire(blocking=False):
        raise NotPermitted("Sign-in is busy right now. Try again in a moment.")
    try:
        if row is None:
            # Spend the time anyway, so a missing user is not faster than a
            # wrong password.
            _hasher.hash("timing-equalisation")
            matched = False
        else:
            try:
                _hasher.verify(row["password_hash"], password)
                matched = True
            except (VerifyMismatchError, InvalidHashError):
                matched = False
    finally:
        _hashing.release()

    if not matched:
        throttle.record_failure(client)
        raise NotPermitted("Incorrect username or password.")

    throttle.clear(client)
    # Hashed before the transaction, not inside it: one argon2 run takes a
    # fifth of a second, and a write should not hold the database that long.
    rehashed = (
        hash_password(password) if _hasher.check_needs_rehash(row["password_hash"]) else None
    )

    def work(conn: sqlite3.Connection) -> None:
        if rehashed is not None:
            # Argon2 parameters get stronger over time; upgrade on next login.
            conn.execute(
                "UPDATE admin_users SET password_hash = ? WHERE username = ?",
                (rehashed, row["username"]),
            )
        conn.execute(
            "UPDATE admin_users SET last_login_at = ? WHERE username = ?",
            (utcnow(), row["username"]),
        )

    db.transact(work)
    return row["username"]


def setup_token_matches(given: str, expected: str) -> bool:
    """Compared in constant time, and never true when no token is set."""
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def list_admins(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"username": r["username"], "created_at": r["created_at"], "last_login_at": r["last_login_at"]}
        for r in conn.execute(
            "SELECT username, created_at, last_login_at FROM admin_users ORDER BY username"
        )
    ]


def admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()["n"]
