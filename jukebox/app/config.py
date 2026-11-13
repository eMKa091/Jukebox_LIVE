"""Runtime configuration. Everything comes from the environment.

The environment is a mapping, os.environ unless told otherwise: on the
Cloudflare Worker it is the Worker's own `env`, its variables and secrets
(docs/08-cloudflare-port.md, step 3.2).

Nothing in this file has a production-safe default except the ones that are
genuinely environment-independent. Secrets that are missing in production make
the app refuse to start rather than fall back to something guessable.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent


# Every name load_settings reads. The Worker copies these, and only these, out
# of its env, which is not a mapping.
SETTINGS_KEYS = (
    "JUKEBOX_DEV",
    "JUKEBOX_SECRET_KEY",
    "JUKEBOX_DB",
    "JUKEBOX_SESSION_MAX_AGE",
    "JUKEBOX_LOGIN_MAX_ATTEMPTS",
    "JUKEBOX_LOGIN_WINDOW",
    "JUKEBOX_PUBLIC_URL",
    "JUKEBOX_TIMEZONE",
)


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
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

    # The address the audience uses, e.g. https://hlasuj.jukeboxheroes.cz.
    # QR codes and the links on the Share tab are built from it. Empty means
    # "whatever address this request came in on", which is right on one host
    # and wrong the day the console is opened under a second name.
    public_url: str = ""

    # The zone the band lives in. Start times are typed and shown in it and
    # stored as UTC; the container itself runs in UTC and is never asked.
    timezone: str = "Europe/Prague"

    @property
    def secure_cookies(self) -> bool:
        # Cookies are Secure in production. In dev the app is served over
        # plain http on localhost, where Secure cookies are simply dropped.
        return not self.dev_mode


def load_settings(
    env: Mapping[str, str] | None = None, *, require_secret: bool = True
) -> Settings:
    """Read settings from `env`, the process environment if none is given.

    `require_secret=False` is for commands that never sign anything -- the CLI
    creates accounts and takes snapshots, and demanding a session-signing key
    to do that is a papercut that shows up the first time someone follows the
    README.
    """
    env = os.environ if env is None else env
    dev_mode = _bool(env, "JUKEBOX_DEV", False)

    secret = env.get("JUKEBOX_SECRET_KEY")
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
    database_path = Path(env.get("JUKEBOX_DB", str(default_db))).expanduser()

    return Settings(
        database_path=database_path,
        secret_key=secret,
        session_max_age=int(env.get("JUKEBOX_SESSION_MAX_AGE", str(12 * 3600))),
        login_max_attempts=int(env.get("JUKEBOX_LOGIN_MAX_ATTEMPTS", "8")),
        login_window_seconds=int(env.get("JUKEBOX_LOGIN_WINDOW", "900")),
        dev_mode=dev_mode,
        public_url=env.get("JUKEBOX_PUBLIC_URL", "").strip().rstrip("/"),
        timezone=env.get("JUKEBOX_TIMEZONE", "Europe/Prague"),
    )
