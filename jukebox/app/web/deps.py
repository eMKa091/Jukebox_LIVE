"""Access to process-wide objects from inside a request.

They hang off app.state rather than module globals so tests can build an app
with its own temporary database, and two apps can coexist in one process.
Each takes a request or a WebSocket: both carry the app.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from ..config import Settings
from ..db import Database
from ..domain.identity import LoginThrottle
from .security import Tokens


def get_db(request: HTTPConnection) -> Database:
    return request.app.state.db


def get_settings(request: HTTPConnection) -> Settings:
    return request.app.state.settings


def get_tokens(request: HTTPConnection) -> Tokens:
    return request.app.state.tokens


def get_throttle(request: HTTPConnection) -> LoginThrottle:
    return request.app.state.throttle
