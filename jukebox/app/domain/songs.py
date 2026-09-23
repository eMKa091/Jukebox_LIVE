"""The master song list.

Songs are never deleted. The legacy admin page had a "Delete all songs from DB"
button that ran DELETE FROM songs with no cascade, leaving all 896 rows in
event_songs pointing at ids that no longer existed (F10). Here retirement is a
timestamp: a retired song disappears from pickers but every past vote still
resolves to a title.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass

from ..db import Database, utcnow
from . import log
from .errors import Invalid, NotFound

# The legacy CSV export the band already has uses these headers with a
# semicolon delimiter. Both spellings are accepted so old files still import.
TITLE_HEADERS = ("song", "title", "pisen", "píseň", "skladba")
ARTIST_HEADERS = ("author", "artist", "umelec", "umělec", "interpret")


@dataclass(frozen=True)
class Song:
    id: int
    title: str
    artist: str
    retired: bool

    @property
    def label(self) -> str:
        return f"{self.title} — {self.artist}"


def _row(r: sqlite3.Row) -> Song:
    return Song(id=r["id"], title=r["title"], artist=r["artist"], retired=bool(r["retired_at"]))


def list_songs(conn: sqlite3.Connection, *, include_retired: bool = False) -> list[Song]:
    sql = "SELECT id, title, artist, retired_at FROM songs"
    if not include_retired:
        sql += " WHERE retired_at IS NULL"
    sql += " ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE"
    return [_row(r) for r in conn.execute(sql)]


def get(conn: sqlite3.Connection, song_id: int) -> Song:
    r = conn.execute(
        "SELECT id, title, artist, retired_at FROM songs WHERE id = ?", (song_id,)
    ).fetchone()
    if r is None:
        raise NotFound(f"Song {song_id} does not exist.")
    return _row(r)


def add(db: Database, *, title: str, artist: str, actor: str) -> Song:
    title, artist = title.strip(), artist.strip()
    if not title or not artist:
        raise Invalid("A song needs both a title and an artist.")
    with db.write() as conn:
        existing = conn.execute(
            "SELECT id, title, artist, retired_at FROM songs"
            " WHERE lower(artist) = lower(?) AND lower(title) = lower(?)",
            (artist, title),
        ).fetchone()
        if existing is not None:
            # An exact duplicate un-retires rather than erroring: re-uploading
            # last year's CSV should restore the list, not fail halfway.
            if existing["retired_at"]:
                conn.execute("UPDATE songs SET retired_at = NULL WHERE id = ?", (existing["id"],))
                log.record(conn, actor=actor, action="song.restored", song_id=existing["id"])
            return _row(existing)
        cur = conn.execute(
            "INSERT INTO songs (title, artist) VALUES (?, ?)", (title, artist)
        )
        song_id = int(cur.lastrowid)
        log.record(conn, actor=actor, action="song.added", song_id=song_id, title=title, artist=artist)
        return Song(id=song_id, title=title, artist=artist, retired=False)


def set_retired(db: Database, *, song_id: int, retired: bool, actor: str) -> None:
    with db.write() as conn:
        if conn.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone() is None:
            raise NotFound(f"Song {song_id} does not exist.")
        conn.execute(
            "UPDATE songs SET retired_at = ? WHERE id = ?",
            (utcnow() if retired else None, song_id),
        )
        log.record(
            conn,
            actor=actor,
            action="song.retired" if retired else "song.restored",
            song_id=song_id,
        )


@dataclass
class ImportReport:
    added: int = 0
    restored: int = 0
    duplicates: int = 0
    skipped: list[str] = None  # rows that could not be read, with the reason

    def __post_init__(self) -> None:
        if self.skipped is None:
            self.skipped = []

    @property
    def total_rows(self) -> int:
        return self.added + self.restored + self.duplicates + len(self.skipped)


def parse_csv(raw: bytes) -> list[tuple[str, str]]:
    """Read (title, artist) pairs from an uploaded CSV.

    Deliberately forgiving about the things that actually vary between the
    band's files: the delimiter (semicolon or comma), the encoding (Excel on a
    Czech Windows machine writes cp1250), header case, and an extra leading
    index column. Deliberately strict about everything else -- a file we cannot
    read confidently is reported row by row rather than imported partially.
    """
    for encoding in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes any byte string
        raise Invalid("The file could not be read as text.")

    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise Invalid("The file has no header row.")

    lookup = {(name or "").strip().lower(): name for name in reader.fieldnames}
    title_col = next((lookup[h] for h in TITLE_HEADERS if h in lookup), None)
    artist_col = next((lookup[h] for h in ARTIST_HEADERS if h in lookup), None)
    if title_col is None or artist_col is None:
        raise Invalid(
            "The file needs a title column and an artist column. Accepted "
            f"titles: {', '.join(TITLE_HEADERS)}. Accepted artists: "
            f"{', '.join(ARTIST_HEADERS)}."
        )

    pairs: list[tuple[str, str]] = []
    for row in reader:
        pairs.append(((row.get(title_col) or "").strip(), (row.get(artist_col) or "").strip()))
    return pairs


def import_csv(db: Database, raw: bytes, *, actor: str) -> ImportReport:
    """Import a CSV in one transaction. Either all of it lands or none does."""
    pairs = parse_csv(raw)
    report = ImportReport()
    with db.write() as conn:
        for line_no, (title, artist) in enumerate(pairs, start=2):
            if not title or not artist:
                report.skipped.append(f"line {line_no}: missing title or artist")
                continue
            existing = conn.execute(
                "SELECT id, retired_at FROM songs"
                " WHERE lower(artist) = lower(?) AND lower(title) = lower(?)",
                (artist, title),
            ).fetchone()
            if existing is None:
                conn.execute("INSERT INTO songs (title, artist) VALUES (?, ?)", (title, artist))
                report.added += 1
            elif existing["retired_at"]:
                conn.execute("UPDATE songs SET retired_at = NULL WHERE id = ?", (existing["id"],))
                report.restored += 1
            else:
                report.duplicates += 1
        log.record(
            conn,
            actor=actor,
            action="songs.imported",
            added=report.added,
            restored=report.restored,
            duplicates=report.duplicates,
            skipped=len(report.skipped),
        )
    return report
