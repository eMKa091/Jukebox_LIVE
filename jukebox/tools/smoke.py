"""One evening in a minute, against any running copy of the app.

    python tools/smoke.py http://127.0.0.1:8787 [setup token]

For the Worker, local (`pywrangler dev`) or deployed (docs/08, steps 5.3 and
8). Signs in as `smoke`, making that account through /admin/setup first if
the app has none and a setup token is given. Then: three songs, an event put
on air, round 1 opened, a phone that joins and votes, the vote arriving on
the band display's WebSocket and in its tally, the round closed and the
phone's page showing the standings, the event closed again. Prints one line
per step and exits non-zero on the first that fails.

Safe to run again on the same app: each run makes its own event and closes
it. It does leave the songs and the event behind, so do not point it at the
band's real data.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time

import httpx
import websockets

BASE = sys.argv[1].rstrip("/")
SETUP_TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""
USER, PASSWORD = "smoke", "smoke-test-password"
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")


def step(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        raise SystemExit(1)


def found(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


async def main() -> None:
    timeout = httpx.Timeout(30)
    async with httpx.AsyncClient(base_url=BASE, timeout=timeout) as admin, \
            httpx.AsyncClient(base_url=BASE, timeout=timeout) as phone:
        ready = await admin.get("/readyz")
        step("the app answers", ready.status_code == 200, ready.text)

        if (await admin.get("/admin/setup")).status_code == 200:
            step("a setup token was given", bool(SETUP_TOKEN), "the app has no account yet")
            made = await admin.post("/admin/setup", data={
                "token": SETUP_TOKEN, "username": USER, "password": PASSWORD, "repeat": PASSWORD})
            step("the first account is made", made.headers.get("location") == "/admin/login")

        signed = await admin.post("/admin/login", data={"username": USER, "password": PASSWORD})
        step("signed in", signed.headers.get("location") == "/admin", signed.headers.get("location", ""))

        for title, artist in (("Hello", "Adele"), ("Africa", "Toto"), ("Pohoda", "Kabát")):
            await admin.post("/admin/songs", data={"title": title, "artist": artist})

        name = f"Smoke {time.strftime('%H%M%S')}"
        created = await admin.post("/admin/events", data={
            "name": name, "starts_at": "2026-12-31T20:00", "venue": "", "round_count": "2",
            "max_votes": "3"})
        event_id = found(r"/admin/events/(\d+)", created.headers.get("location", ""))
        step("an event is made", bool(event_id), name)

        for to in ("ready", "live"):
            moved = await admin.post(f"/admin/events/{event_id}/state", data={"to": to})
            step(f"the event goes {to}", moved.headers.get("location") == f"/admin/events/{event_id}",
                 moved.headers.get("location", ""))

        console = (await admin.get(f"/admin/events/{event_id}")).text
        round_id = found(r'action="/admin/rounds/(\d+)/state"', console)
        opened = await admin.post(f"/admin/rounds/{round_id}/state", data={"to": "open"})
        step("round 1 opens", opened.status_code == 303 and "flash" not in opened.headers.get("set-cookie", ""))

        share = (await admin.get(f"/admin/events/{event_id}?tab=share")).text
        band = found(r'href="[^"]*(/band/[^"]+)"', share)
        slug = found(r"/e/([a-z0-9-]+)", share)
        step("the share tab names both links", bool(band and slug), f"{slug} {band[:20]}…")

        async with websockets.connect(f"{WS_BASE}{band}/stream", open_timeout=30) as display:
            first = json.loads(await asyncio.wait_for(display.recv(), 30))
            step("the band display's socket says ready", first.get("type") == "ready", str(first))

            joined = await phone.post(f"/e/{slug}/join", data={"display_name": "Smoke"})
            ballot = (await phone.get(f"/e/{slug}")).text
            picks = re.findall(r'name="song_ids" value="(\d+)"', ballot)[:2]
            step("a phone joins and gets the ballot", joined.status_code == 303 and len(picks) == 2,
                 f"{len(picks)} songs picked")

            t = time.perf_counter()
            voted = await phone.post(f"/e/{slug}/ballot", data={
                "ballot_id": f"smoke-{time.time()}", "round_id": round_id, "song_ids": picks})
            told = json.loads(await asyncio.wait_for(display.recv(), 30))
            step("the vote reaches the band display", voted.status_code == 303
                 and told.get("kind") == "votes", f"{(time.perf_counter() - t) * 1000:.0f} ms")

        tally = (await phone.get(f"{band}/live")).text
        counts = [int(n) for n in re.findall(r'<span class="n">(\d+)</span>', tally)]
        step("the band's tally counts it", sorted(counts, reverse=True)[:2] == [1, 1], str(counts))

        receipt = (await phone.get(f"/e/{slug}")).text
        step("the phone sees its receipt", "data-voted-round" in receipt)

        await admin.post(f"/admin/rounds/{round_id}/state", data={"to": "closed"})
        standings = (await phone.get(f"/e/{slug}")).text
        step("round closed, the phone sees the standings", "Kolo právě skončilo" in standings)

        closed = await admin.post(f"/admin/events/{event_id}/state", data={"to": "closed"})
        step("the event closes", closed.status_code == 303)


asyncio.run(main())
