"""Admin accounts and password handling.

The legacy scheme was sha256(password) with no salt, no work factor, no attempt
limit and no session expiry, and the resulting hash lived in a database file
committed to a public GitHub repository (F8). Argon2id replaces all of that.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ..db import Database, utcnow
from . import log
from .errors import Invalid, NotFound, NotPermitted

# Defaults are argon2-cffi's, which track the OWASP guidance. Tuning them is a
# deployment decision, not a code one.
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10

# One argon2 run takes 64 MiB. Nobody has to be signed in to cause one, so the
# number running at once is capped; a caller who finds both places taken is
# told to try again rather than parked on a worker thread the voters need.
_hashing = threading.BoundedSemaphore(2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@dataclass
class LoginThrottle:
    """Attempt limiting per caller, in process memory.

    Counted against where the attempts come from, not against the username
    they name. Counted per username, eight wrong passwords from anyone, from
    anywhere, shut the band out of their own console for the window.

    In process is the right scope here: there is one container, and a throttle
    that survives a restart would lock the band out of their own gig if the app
    were redeployed mid-evening. The goal is to stop online guessing, not to be
    a durable security control.
    """

    max_attempts: int
    window_seconds: int
    _attempts: dict[str, list[float]] = field(default_factory=dict)

    def check(self, client: str) -> None:
        now = time.monotonic()
        recent = [t for t in self._attempts.get(client, []) if now - t < self.window_seconds]
        if recent:
            self._attempts[client] = recent
        else:
            self._attempts.pop(client, None)
        if len(recent) >= self.max_attempts:
            wait = int(self.window_seconds - (now - recent[0])) // 60 + 1
            raise NotPermitted(
                f"Too many failed sign-ins. Try again in about {wait} minute(s)."
            )

    def record_failure(self, client: str) -> None:
        if len(self._attempts) > 4096:
            # Forget callers whose window has passed, so the table cannot grow
            # without limit under a flood from many addresses.
            now = time.monotonic()
            for key in [k for k, v in self._attempts.items() if now - v[-1] >= self.window_seconds]:
                del self._attempts[key]
        self._attempts.setdefault(client, []).append(time.monotonic())

    def clear(self, client: str) -> None:
        self._attempts.pop(client, None)


def create_admin(db: Database, *, username: str, password: str, actor: str = "system") -> int:
    username = username.strip()
    if not username:
        raise Invalid("A username is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    def work(conn: sqlite3.Connection) -> int:
        exists = conn.execute(
            "SELECT 1 FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise Invalid(f"User {username!r} already exists.")
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), utcnow()),
        )
        log.record(conn, actor=actor, action="admin.created", username=username)
        return int(cur.lastrowid)

    return db.transact(work)


def set_password(db: Database, *, username: str, password: str, actor: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    def work(conn: sqlite3.Connection) -> None:
        cur = conn.execute(
            "UPDATE admin_users SET password_hash = ? WHERE username = ?",
            (hash_password(password), username),
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


def list_admins(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"username": r["username"], "created_at": r["created_at"], "last_login_at": r["last_login_at"]}
        for r in conn.execute(
            "SELECT username, created_at, last_login_at FROM admin_users ORDER BY username"
        )
    ]


def admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()["n"]
