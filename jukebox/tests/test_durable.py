"""app.db_durable: the Durable Object's SQLite, shaped like sqlite3.

The whole suite already runs through it (conftest's `db` fixture). These pin
the few things the adapter itself adds, each a gap docs/08 section 4 found.
"""

from __future__ import annotations

import pytest

from app.db import IntegrityError
from app.db_durable import DurableDatabase
from tests.durable_standin import JsError, StandInStorage


@pytest.fixture
def durable(tmp_path):
    storage = StandInStorage(tmp_path / "object.db")
    database = DurableDatabase(storage)
    database.migrate()
    yield database
    storage.close()


def test_rows_read_by_name_by_position_and_as_a_list(durable):
    conn = durable.read()
    conn.execute("INSERT INTO songs (title, artist) VALUES (?, ?)", ("Hello", "Adele"))
    row = conn.execute("SELECT id, title, artist FROM songs").fetchone()
    assert row["title"] == "Hello" and row[2] == "Adele"
    assert list(row) == [row["id"], "Hello", "Adele"]
    assert conn.execute("SELECT id FROM songs WHERE title = 'nope'").fetchone() is None


def test_a_write_reports_its_rowid_and_how_many_rows_it_changed(durable):
    conn = durable.read()
    first = conn.execute("INSERT INTO songs (title, artist) VALUES ('A', 'B')")
    second = conn.execute("INSERT INTO songs (title, artist) VALUES ('C', 'D')")
    assert (first.lastrowid, second.lastrowid) == (1, 2)
    assert conn.execute("UPDATE songs SET retired_at = 'x'").rowcount == 2
    assert conn.execute("UPDATE songs SET retired_at = 'x' WHERE id = 99").rowcount == 0
    many = conn.executemany("INSERT INTO songs (title, artist) VALUES (?, ?)",
                            [("E", "F"), ("G", "H"), ("I", "J")])
    assert many.rowcount == 3


def test_a_constraint_failure_is_an_integrity_error(durable):
    conn = durable.read()
    conn.execute("INSERT INTO songs (title, artist) VALUES ('Hello', 'Adele')")
    with pytest.raises(IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO songs (title, artist) VALUES ('hello', 'ADELE')")
    with pytest.raises(JsError):  # anything else passes through as it came
        conn.execute("SELECT * FROM no_such_table")


def test_a_transaction_returns_what_the_callback_returned_or_rolls_back(durable):
    marker = object()

    def work(conn):
        conn.execute("INSERT INTO songs (title, artist) VALUES ('A', 'B')")
        return marker

    assert durable.transact(work) is marker

    class Refused(Exception):
        pass

    def fails(conn):
        conn.execute("INSERT INTO songs (title, artist) VALUES ('C', 'D')")
        raise Refused

    with pytest.raises(Refused):
        durable.transact(fails)
    assert durable.read().execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1


def test_a_failed_migration_leaves_nothing_behind_on_the_object_too(tmp_path, monkeypatch):
    import app.db as dbmod

    bad = tmp_path / "001_bad.sql"
    bad.write_text("CREATE TABLE a (x); CREATE TABLE b (y); THIS IS NOT SQL;")
    monkeypatch.setattr(dbmod, "MIGRATIONS", [bad])
    storage = StandInStorage(tmp_path / "object.db")

    with pytest.raises(JsError, match="syntax error"):
        DurableDatabase(storage).migrate()
    assert storage.sql.exec("SELECT COUNT(*) FROM sqlite_master").raw().toArray() == [[0]]
