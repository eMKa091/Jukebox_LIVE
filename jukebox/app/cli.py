"""Operator commands.

    python -m app.cli create-admin marek
    python -m app.cli reset-password marek
    python -m app.cli migrate
    python -m app.cli backup /path/to/snapshot.db
    python -m app.cli stats

Everything an operator needs to do lives here rather than in a web page, so
none of it needs a route, a session, or a button that has to be found at a gig.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .config import load_settings
from .db import Database
from .domain import identity
from .domain.errors import DomainError


def _db() -> Database:
    # No route, no session, no signed link: the CLI has no use for a secret.
    settings = load_settings(require_secret=False)
    db = Database(settings.database_path)
    db.migrate()
    return db


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat:   "):
        raise SystemExit("Passwords did not match.")
    return first


def cmd_create_admin(args) -> int:
    try:
        identity.create_admin(_db(), username=args.username, password=_ask_password())
    except DomainError as exc:
        raise SystemExit(str(exc))
    print(f"Created admin {args.username!r}.")
    return 0


def cmd_reset_password(args) -> int:
    try:
        identity.set_password(
            _db(), username=args.username, password=_ask_password(), actor="cli"
        )
    except DomainError as exc:
        raise SystemExit(str(exc))
    print(f"Password updated for {args.username!r}.")
    return 0


def cmd_migrate(_args) -> int:
    print(f"Schema is at version {_db().migrate()}.")
    return 0


def cmd_backup(args) -> int:
    """A consistent snapshot, taken without stopping the app.

    sqlite3's own backup API copies a live database safely, unlike `cp`, which
    can catch it mid-write. Litestream covers continuous replication; this is
    for the moments you want a file in your hand.
    """
    import sqlite3

    source = _db().connect()
    target = sqlite3.connect(args.destination)
    with target:
        source.backup(target)
    target.close()
    print(f"Wrote {args.destination}.")
    return 0


def cmd_stats(_args) -> int:
    conn = _db().read()
    rows = conn.execute(
        "SELECT e.name, e.state, COUNT(DISTINCT v.voter_id) AS voters,"
        "       COUNT(v.id) AS votes"
        " FROM events e"
        " LEFT JOIN rounds r ON r.event_id = e.id"
        " LEFT JOIN votes v ON v.round_id = r.id"
        " GROUP BY e.id ORDER BY e.starts_at"
    ).fetchall()
    songs = conn.execute("SELECT COUNT(*) FROM songs WHERE retired_at IS NULL").fetchone()[0]
    admins = identity.admin_count(conn)
    print(f"{songs} songs, {admins} admin account(s), {len(rows)} event(s)\n")
    print(f"{'event':34} {'state':8} {'voters':>7} {'votes':>7}")
    for r in rows:
        print(f"{r['name'][:33]:34} {r['state']:8} {r['voters']:>7} {r['votes']:>7}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="create an admin account")
    p.add_argument("username")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password", help="change an admin password")
    p.add_argument("username")
    p.set_defaults(func=cmd_reset_password)

    sub.add_parser("migrate", help="apply pending schema migrations").set_defaults(func=cmd_migrate)

    p = sub.add_parser("backup", help="write a consistent snapshot")
    p.add_argument("destination")
    p.set_defaults(func=cmd_backup)

    sub.add_parser("stats", help="what is in the database").set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
