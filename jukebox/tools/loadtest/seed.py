"""Seed a scratch database: admin, 420 songs, a two-round event on air, round 1 open."""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from app.db import Database
from app.domain import events, identity, rounds, songs

db = Database(Path(sys.argv[2]))
db.migrate()
identity.create_admin(db, username="load", password="load-test-password")
n = int(sys.argv[3])
with db.write() as conn:
    for i in range(n):
        conn.execute("INSERT INTO songs (title, artist) VALUES (?, ?)",
                     (f"Píseň číslo {i:03d}", f"Interpret {i % 60:02d}"))
ev = events.create(db, name="Zatezova zkouska", starts_at="2026-11-12T19:00:00Z",
                   round_count=2, max_votes=5, actor="load")
r1 = rounds.for_event(db.read(), ev.id)[0]
rounds.assign_all_songs(db, round_id=r1.id, actor="load")
events.transition(db, event_id=ev.id, to="ready", actor="load")
events.transition(db, event_id=ev.id, to="live", actor="load")
rounds.transition(db, round_id=r1.id, to="open", actor="load")
print(ev.slug, r1.id, ev.id)
