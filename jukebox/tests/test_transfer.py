"""The band's data in and out as one document (docs/08-cloudflare-port.md, 7.1).

The chain that matters: the legacy file, migrated, pushed into the app, pulled
back out, and gate G2 run on what came out. It runs on both backends, so the
Durable Object's path is the one tested, not only the file's.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import transfer
from app.db import Database
from app.domain import identity, songs
from app.domain.errors import Conflict, Invalid
from tests.conftest import ADMIN_PASSWORD, LEGACY_DB

needs_legacy = pytest.mark.skipif(not LEGACY_DB.exists(), reason="legacy database not present")


@pytest.fixture
def legacy_export(tmp_path):
    from scripts.migrate_legacy import migrate

    migrate(LEGACY_DB, tmp_path / "migrated.db", force=True)
    conn = sqlite3.connect(tmp_path / "migrated.db")
    conn.row_factory = sqlite3.Row
    yield transfer.dump(conn)
    conn.close()


@needs_legacy
def test_the_legacy_data_survives_in_and_out_of_the_app(db, legacy_export, tmp_path):
    from scripts.migrate_legacy import verify

    # The app as deployed: an account already made, so the log is not empty.
    identity.create_admin(db, username="marek", password=ADMIN_PASSWORD, first=True)
    counts = transfer.load(db, legacy_export, actor="t")
    assert counts["votes"] == len(legacy_export["tables"]["votes"]["rows"])

    pulled = Database(tmp_path / "pulled.db")
    pulled.migrate()
    transfer.load(pulled, json.loads(json.dumps(transfer.dump(db.read()))), actor="t")
    assert verify(LEGACY_DB, pulled.path) == []
    assert identity.admin_count(pulled.read()) == 0  # accounts never travel
    pulled.close()


def test_an_import_goes_into_an_empty_app_only(db):
    songs.add(db, title="Hello", artist="Adele", actor="t")
    data = {"format": transfer.FORMAT, "tables": {
        "songs": {"columns": ["id", "title", "artist", "retired_at"], "rows": [[7, "A", "B", None]]}}}
    with pytest.raises(Conflict):
        transfer.load(db, data, actor="t")
    assert [s.title for s in songs.list_songs(db.read())] == ["Hello"]


@pytest.mark.parametrize("data", [
    {"format": "something else", "tables": {}},
    {"format": transfer.FORMAT, "tables": {"admin_users": {"columns": [], "rows": []}}},
    {"format": transfer.FORMAT, "tables": {"songs": {"columns": ["id); DROP TABLE songs; --"], "rows": []}}},
])
def test_an_import_that_is_not_an_export_is_refused(db, data):
    with pytest.raises(Invalid):
        transfer.load(db, data, actor="t")


def test_a_half_bad_import_leaves_nothing_behind(db):
    data = {"format": transfer.FORMAT, "tables": {
        "songs": {"columns": ["id", "title", "artist"], "rows": [[1, "A", "B"]]},
        "events": {"columns": ["id", "nope"], "rows": [[1, "x"]]}}}
    with pytest.raises(Exception):
        transfer.load(db, data, actor="t")
    assert songs.list_songs(db.read()) == []


def test_the_export_and_import_routes_are_for_admins(client, admin_client, catalogue):
    signed_out = client.__class__(client.app)
    assert signed_out.get("/admin/data/export.json", follow_redirects=False).status_code == 303

    export = admin_client.get("/admin/data/export.json")
    assert "attachment" in export.headers["content-disposition"]
    assert len(export.json()["tables"]["songs"]["rows"]) == len(catalogue)

    again = admin_client.post("/admin/data/import",
                              files={"file": ("x.json", export.content, "application/json")})
    assert again.status_code == 409  # this app holds songs already
