"""The master song list and CSV import."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain import rounds, songs
from app.domain.errors import Invalid

DATA = Path(__file__).resolve().parents[2] / "dataSources"


def test_songs_are_unique_case_insensitively(db):
    first = songs.add(db, title="Hello", artist="Adele", actor="t")
    second = songs.add(db, title="HELLO", artist="adele", actor="t")
    assert first.id == second.id
    assert len(songs.list_songs(db.read())) == 1


def test_title_and_artist_are_both_required(db):
    with pytest.raises(Invalid):
        songs.add(db, title="Hello", artist="  ", actor="t")


def test_retiring_hides_a_song_without_deleting_it(db, catalogue):
    target = catalogue[0]
    songs.set_retired(db, song_id=target.id, retired=True, actor="t")
    assert target.id not in {s.id for s in songs.list_songs(db.read())}
    assert target.id in {s.id for s in songs.list_songs(db.read(), include_retired=True)}
    # The row is still joinable, so past votes still resolve to a title (F10).
    assert songs.get(db.read(), target.id).title == target.title


def test_retired_songs_are_not_assigned_to_new_rounds(db, catalogue, event):
    songs.set_retired(db, song_id=catalogue[0].id, retired=True, actor="t")
    second = rounds.for_event(db.read(), event.id)[1]
    rounds.assign_all_songs(db, round_id=second.id, actor="t")
    assert catalogue[0].id not in {r["id"] for r in rounds.votable_songs(db.read(), second.id)}


# ------------------------------------------------------------------ CSV --
def test_the_bands_own_csv_imports(db):
    """songList.csv is the file the legacy app used: 'Author,Song', comma."""
    report = songs.import_csv(db, (DATA / "songList.csv").read_bytes(), actor="t")
    assert report.added == 103          # every row distinct
    assert report.skipped == []
    assert len(songs.list_songs(db.read())) == 103


def test_the_czech_csv_dialect_imports_too(db):
    """muzi.csv is 'Poradi,Umelec,Pisen' -- the legacy importer rejected it."""
    report = songs.import_csv(db, (DATA / "muzi.csv").read_bytes(), actor="t")
    assert report.added == 46
    assert report.skipped == []


@pytest.mark.parametrize("filename", ["songList.csv", "muzi.csv", "zeny.csv",
                                      "rokenrol.csv", "ceske_old.csv", "test.csv"])
def test_every_csv_in_the_repository_parses(filename):
    pairs = songs.parse_csv((DATA / filename).read_bytes())
    assert pairs, f"{filename} produced no rows"
    assert all(title and artist for title, artist in pairs), f"{filename} has blank cells"


def test_semicolon_and_cp1250_are_handled(db):
    raw = "Umelec;Pisen\nKabát;Pohoda\nČechomor;Proměny\n".encode("cp1250")
    report = songs.import_csv(db, raw, actor="t")
    assert report.added == 2
    assert {s.title for s in songs.list_songs(db.read())} == {"Pohoda", "Proměny"}


def test_reimporting_the_same_file_adds_nothing(db):
    raw = (DATA / "songList.csv").read_bytes()
    songs.import_csv(db, raw, actor="t")
    second = songs.import_csv(db, raw, actor="t")
    assert second.added == 0
    assert second.duplicates == 103


def test_reimporting_restores_retired_songs(db):
    raw = (DATA / "test.csv").read_bytes()
    songs.import_csv(db, raw, actor="t")
    first = songs.list_songs(db.read())[0]
    songs.set_retired(db, song_id=first.id, retired=True, actor="t")
    report = songs.import_csv(db, raw, actor="t")
    assert report.restored == 1
    assert not songs.get(db.read(), first.id).retired


def test_a_file_without_usable_headers_is_rejected_whole(db):
    with pytest.raises(Invalid, match="title column"):
        songs.import_csv(db, b"foo,bar\n1,2\n", actor="t")
    assert songs.list_songs(db.read()) == []


def test_blank_rows_are_reported_not_silently_dropped(db):
    report = songs.import_csv(db, b"Artist;Title\nAdele;Hello\n;Orphan\n", actor="t")
    assert report.added == 1
    assert len(report.skipped) == 1
    assert "line 3" in report.skipped[0]
