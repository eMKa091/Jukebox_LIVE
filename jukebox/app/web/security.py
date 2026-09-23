"""Cookies, signed sessions, and band links.

Three separate identities, none of which is a magic query string:

  * the attendee's device token -- an httpOnly cookie, the thing that makes
    one ballot per device real;
  * the admin session -- a signed, expiring cookie;
  * the band display link -- a signed token in the URL, so the band can open it
    on a tablet without a password but a stranger cannot guess it (F3).
"""

from __future__ import annotations

import uuid

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer

DEVICE_COOKIE = "jb_device"
SESSION_COOKIE = "jb_session"

# Distinct salts, so a token minted for one purpose can never be replayed as
# another even though both are signed with the same secret.
SESSION_SALT = "jukebox.admin.session"
BAND_SALT = "jukebox.band.link"


class Tokens:
    def __init__(self, secret: str, *, session_max_age: int) -> None:
        self._session = URLSafeTimedSerializer(secret, salt=SESSION_SALT)
        self._band = URLSafeSerializer(secret, salt=BAND_SALT)
        self.session_max_age = session_max_age

    # -- admin session ----------------------------------------------------
    def make_session(self, username: str) -> str:
        return self._session.dumps({"u": username})

    def read_session(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            data = self._session.loads(raw, max_age=self.session_max_age)
        except (BadSignature, SignatureExpired):
            return None
        return data.get("u")

    # -- band link --------------------------------------------------------
    def make_band_token(self, event_id: int) -> str:
        return self._band.dumps({"e": event_id})

    def read_band_token(self, raw: str) -> int | None:
        try:
            return int(self._band.loads(raw)["e"])
        except (BadSignature, KeyError, TypeError, ValueError):
            return None


def device_token(request: Request) -> str:
    """This browser's token, from the cookie or freshly minted.

    Minted here and written by `ensure_device_cookie` on the way out, so a
    first-time visitor can vote within the same request rather than needing a
    round trip to acquire an identity.
    """
    existing = request.cookies.get(DEVICE_COOKIE)
    if existing and len(existing) == 32:
        return existing
    return uuid.uuid4().hex


def ensure_device_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=60 * 60 * 24 * 180,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def set_session_cookie(response: Response, value: str, *, secure: bool, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
