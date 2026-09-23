"""Runtime configuration. Everything comes from the environment.

Nothing in this file has a production-safe default except the ones that are
genuinely environment-independent. Secrets that are missing in production make
the app refuse to start rather than fall back to something guessable.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Where the SQLite file lives. On Fly this is the mounted volume, which is
    # the whole difference between this design and the legacy one: the database
    # survives a container restart, so nobody has to press a backup button.
    database_path: Path

    # Signs the admin session cookie and the band display links.
    secret_key: str

    # Admin sessions expire. The legacy app's session never did.
    session_max_age: int

    # Failed logins per username per window, then a lockout.
    login_max_attempts: int
    login_window_seconds: int

    dev_mode: bool

    @property
    def secure_cookies(self) -> bool:
        # Cookies are Secure in production. In dev the app is served over
        # plain http on localhost, where Secure cookies are simply dropped.
        return not self.dev_mode


def load_settings(*, require_secret: bool = True) -> Settings:
    """Read settings from the environment.

    `require_secret=False` is for commands that never sign anything -- the CLI
    creates accounts and takes snapshots, and demanding a session-signing key
    to do that is a papercut that shows up the first time someone follows the
    README.
    """
    dev_mode = _bool("JUKEBOX_DEV", False)

    secret = os.getenv("JUKEBOX_SECRET_KEY")
    if not secret:
        if require_secret and not dev_mode:
            raise RuntimeError(
                "JUKEBOX_SECRET_KEY is not set. Generate one with:\n"
                "    python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        # A fresh key each dev restart. Logs everyone out, which is correct:
        # a dev secret must never be stable enough to become a real one.
        secret = secrets.token_urlsafe(32)

    default_db = ROOT_DIR / "data" / "jukebox.db"
    database_path = Path(os.getenv("JUKEBOX_DB", str(default_db))).expanduser()

    return Settings(
        database_path=database_path,
        secret_key=secret,
        session_max_age=int(os.getenv("JUKEBOX_SESSION_MAX_AGE", str(12 * 3600))),
        login_max_attempts=int(os.getenv("JUKEBOX_LOGIN_MAX_ATTEMPTS", "8")),
        login_window_seconds=int(os.getenv("JUKEBOX_LOGIN_WINDOW", "900")),
        dev_mode=dev_mode,
    )
