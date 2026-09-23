"""Domain errors.

These carry a message written for the person who will see it, not for a log.
The web layer maps them to status codes; it does not rewrite the text.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class. Everything below is a rule the caller broke."""

    status = 400


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    """The request was valid but the current state does not permit it.

    Raised when two admins act at once, or when a transition is attempted out
    of order. The legacy code handled this case by silently stopping whatever
    else was running.
    """

    status = 409


class Invalid(DomainError):
    """Malformed input."""

    status = 400


class NotPermitted(DomainError):
    status = 403
