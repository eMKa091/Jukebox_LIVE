#!/usr/bin/env python3
"""Move the band's data between a database file and a running app.

    python scripts/transfer.py push FILE.db URL USER     the file into the app
    python scripts/transfer.py pull URL USER FILE.db     the app into a new file
    python scripts/transfer.py restore URL USER WHEN     the app as it was at WHEN

For the Worker, which has no file to copy (docs/08-cloudflare-port.md, step 7).
<address> is where the app answers: https://jukebox-live.<account>.workers.dev
until the switch, https://hlasuj.jukeboxheroes.cz after it. The password is
asked for, or read from JUKEBOX_PASSWORD.

The legacy data goes in like this, and gate G2 is then run on what came back
out, not on the file that went in:

    python scripts/migrate_legacy.py ../jukeboxHeroes-v2/backups/backup-votes.db data/legacy.db --force
    python scripts/transfer.py push data/legacy.db <address> <user>
    python scripts/transfer.py pull <address> <user> data/pulled.db
    python scripts/migrate_legacy.py ../jukeboxHeroes-v2/backups/backup-votes.db data/pulled.db --verify-only

`push` is refused by an app that already holds songs or events. `pull` is
also the copy to keep: run it after every gig.

`restore` puts the Worker's whole database back to WHEN, the band's local
time (`2026-11-20T21:30`), up to 30 days back; everything after it goes. It
pulls a copy of the present to data/before-restore-<time>.db first.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import transfer  # noqa: E402
from app.db import Database  # noqa: E402


def _signed_in(url: str, user: str) -> httpx.Client:
    password = os.environ.get("JUKEBOX_PASSWORD") or getpass.getpass(f"Password for {user}: ")
    client = httpx.Client(base_url=url.rstrip("/"), timeout=120)
    answer = client.post("/admin/login", data={"username": user, "password": password})
    if answer.headers.get("location") != "/admin":
        raise SystemExit("Could not sign in.")
    return client


def push(path: Path, url: str, user: str) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    body = json.dumps(transfer.dump(conn), ensure_ascii=False).encode("utf-8")
    conn.close()
    answer = _signed_in(url, user).post(
        "/admin/data/import", files={"file": ("export.json", body, "application/json")}
    )
    if answer.status_code != 200:
        raise SystemExit(f"Refused ({answer.status_code}): {answer.text[:300]}")
    for table, n in answer.json()["imported"].items():
        print(f"  {table:12} {n}")
    return 0


def pull(url: str, user: str, path: Path) -> int:
    if path.exists():
        raise SystemExit(f"{path} already exists; pull writes a new file.")
    answer = _signed_in(url, user).get("/admin/data/export.json")
    if answer.status_code != 200:
        raise SystemExit(f"Refused ({answer.status_code}): {answer.text[:300]}")
    db = Database(path)
    db.migrate()
    counts = transfer.load(db, answer.json(), actor="transfer.pull")
    db.close()
    for table, n in counts.items():
        print(f"  {table:12} {n}")
    print(f"Wrote {path}.")
    return 0


def restore(url: str, user: str, when: str) -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    keep = Path(__file__).resolve().parent.parent / "data" / f"before-restore-{stamp}.db"
    keep.parent.mkdir(parents=True, exist_ok=True)
    print(f"First, a copy of the present: {keep}")
    pull(url, user, keep)
    answer = _signed_in(url, user).post("/admin/data/restore", data={"at": when})
    if answer.status_code != 200:
        raise SystemExit(f"Refused ({answer.status_code}): {answer.text[:300]}")
    print(f"Restoring to {answer.json()['restoring_to']}. The app restarts; pull again to check.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("push", help="a database file into a running app")
    p.add_argument("file", type=Path)
    p.add_argument("url")
    p.add_argument("user")
    p = sub.add_parser("pull", help="a running app into a new database file")
    p.add_argument("url")
    p.add_argument("user")
    p.add_argument("file", type=Path)
    p = sub.add_parser("restore", help="the app's database as it was at a moment")
    p.add_argument("url")
    p.add_argument("user")
    p.add_argument("when", help="the band's local time, e.g. 2026-11-20T21:30")
    args = parser.parse_args()
    if args.command == "push":
        return push(args.file, args.url, args.user)
    if args.command == "restore":
        return restore(args.url, args.user, args.when)
    return pull(args.url, args.user, args.file)


if __name__ == "__main__":
    raise SystemExit(main())
