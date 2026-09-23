"""Access to process-wide objects from inside a request.

They hang off app.state rather than module globals so tests can build an app
with its own temporary database, and two apps can coexist in one process.
"""

from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..db import Database
from ..domain.identity import LoginThrottle
from .security import Tokens


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_tokens(request: Request) -> Tokens:
    return request.app.state.tokens


def get_throttle(request: Request) -> LoginThrottle:
    return request.app.state.throttle
