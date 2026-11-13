"""N phones across several processes, plus one band display and one admin console.

Phases: everyone scans the QR (ARRIVE s), joins, loads the ballot, holds the live
WebSocket, votes inside WINDOW s. Then the admin closes round 1 (every phone reloads
onto the standings), carries the songs forward and opens round 2 (every phone
reloads onto a fresh ballot). Transport errors are retried like a browser on
Linux would see them (a dropped SYN is a delay there, a refusal on macOS).

The optional eighth argument is the reload spread in seconds: each phone waits
a random moment up to it before reloading, as app.js does (data-jitter, 3 s).
Without it every phone reloads in the same instant, the harder case. A reload
that fails is tried again, as a person would, up to five times.
"""
import asyncio
import json
import multiprocessing as mp
import random
import re
import statistics
import sys
import time

import httpx
import websockets

BASE, SLUG, ROUND_ID, EVENT_ID = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
N, ARRIVE, WINDOW, PROCS = int(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7]), 5
JITTER = float(sys.argv[8]) if len(sys.argv) > 8 else 0.0
KINDS = ["page", "join", "ballot_page", "vote", "reload_closed", "reload_open"]
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")
SOCKET_ERRORS = (OSError, asyncio.TimeoutError, websockets.WebSocketException)


async def phones(proc, count, t_start, out):
    lat = {k: [] for k in KINDS}
    errors, retries, frames, done = [], 0, 0, {"closed": 0, "open": 0, "voted": 0}

    async def req(kind, c, method, url, **kw):
        nonlocal retries
        t = time.perf_counter()
        for attempt in range(6):
            try:
                r = await c.request(method, url, **kw)
                break
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectTimeout):
                retries += 1
                await asyncio.sleep(0.5 + attempt * 0.5)
        else:
            errors.append((kind, "transport"))
            return None
        lat[kind].append(time.perf_counter() - t)
        if r.status_code >= 400:
            errors.append((kind, r.status_code))
        return r

    async def phone(i):
        nonlocal frames, retries
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        async with httpx.AsyncClient(base_url=BASE, timeout=60, limits=limits, follow_redirects=True) as c:
            await asyncio.sleep(max(0, t_start - time.time()) + random.uniform(0, ARRIVE))
            await req("page", c, "GET", f"/e/{SLUG}")
            await req("join", c, "POST", f"/e/{SLUG}/join", data={"display_name": f"Host {proc}-{i}"})
            page = await req("ballot_page", c, "GET", f"/e/{SLUG}")
            ids = re.findall(r'name="song_ids" value="(\d+)"', page.text) if page else []

            async def vote():
                await asyncio.sleep(random.uniform(3, WINDOW))
                r = await req("vote", c, "POST", f"/e/{SLUG}/ballot", data={
                    "ballot_id": f"b{proc}-{i}", "round_id": ROUND_ID, "song_ids": random.sample(ids, 5)})
                if r is not None and "Díky" in r.text:
                    done["voted"] += 1
                else:
                    errors.append(("vote-page", r.status_code if r is not None else "none"))

            voter = asyncio.create_task(vote())
            stage = "closed"
            while stage:
                try:
                    async with websockets.connect(f"{WS_BASE}/e/{SLUG}/stream", open_timeout=60) as s:
                        async for message in s:
                            frames += 1
                            if '"reload": true' in message:
                                break
                        else:
                            continue  # closed without a reload: connect again
                except SOCKET_ERRORS:
                    retries += 1
                    await asyncio.sleep(1)
                    continue
                await asyncio.sleep(random.uniform(0, JITTER))
                for _attempt in range(5):
                    r = await req("reload_" + stage, c, "GET", f"/e/{SLUG}")
                    if r is not None and r.status_code < 500:
                        break
                    await asyncio.sleep(1)
                else:
                    errors.append(("gave up reloading", stage))
                    break
                text = r.text
                if stage == "closed" and "Kolo právě skončilo" in text:
                    done["closed"] += 1
                    stage = "open"
                elif stage == "open" and 'id="ballot"' in text:
                    done["open"] += 1
                    stage = None
                # otherwise: a songs/carry-forward reload in between; keep listening
            await voter

    await asyncio.gather(*(phone(i) for i in range(count)))
    out.put({"lat": lat, "errors": errors[:8], "n_errors": len(errors), "retries": retries,
             "frames": frames, "done": done})


def worker(proc, count, t_start, out):
    asyncio.run(phones(proc, count, t_start, out))


async def staff(t_start, stats):
    """One band display and one admin console, each re-fetching its fragment on every update."""
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        r = await c.post("/admin/login", data={"username": "load", "password": "load-test-password"})
        assert r.status_code == 303
        share = await c.get(f"/admin/events/{EVENT_ID}?tab=share")
        band = re.search(r"/band/([A-Za-z0-9_.\-]+)", share.text).group(1)

        # The console's socket is signed in like its page: the session cookie.
        cookie = {"Cookie": "; ".join(f"{k}={v}" for k, v in c.cookies.items())}

        async def screen(stream_url, fragment_url, key):
            while True:
                try:
                    async with websockets.connect(f"{WS_BASE}{stream_url}", open_timeout=60,
                                                  additional_headers=cookie) as s:
                        async for _message in s:
                            t = time.perf_counter()
                            await c.get(fragment_url)
                            stats[key].append(time.perf_counter() - t)
                except SOCKET_ERRORS:
                    await asyncio.sleep(0.5)

        tasks = [
            asyncio.create_task(screen(f"/band/{band}/stream", f"/band/{band}/live", "band")),
            asyncio.create_task(screen(f"/admin/events/{EVENT_ID}/stream",
                                       f"/admin/events/{EVENT_ID}/live?round={ROUND_ID}", "admin")),
        ]
        await asyncio.sleep(max(0, t_start - time.time()) + ARRIVE + WINDOW + 12)
        stats["t_close"] = time.time()
        r = await c.post(f"/admin/rounds/{ROUND_ID}/state", data={"to": "closed", "tab": "run"})
        assert r.status_code == 303
        await asyncio.sleep(15)
        r = await c.post(f"/admin/rounds/{ROUND_ID}/carry-forward")
        assert r.status_code == 303
        page = await c.get(f"/admin/events/{EVENT_ID}")
        rounds = sorted({int(x) for x in re.findall(r"round=(\d+)", page.text)})
        stats["t_open"] = time.time()
        r = await c.post(f"/admin/rounds/{rounds[-1]}/state", data={"to": "open", "tab": "run"})
        assert r.status_code == 303, r.status_code
        await asyncio.sleep(25)
        for t in tasks:
            t.cancel()


def main():
    out = mp.Queue()
    t_start = time.time() + 3
    per = N // PROCS
    procs = [mp.Process(target=worker, args=(p, per, t_start, out)) for p in range(PROCS)]
    for p in procs:
        p.start()
    stats = {"band": [], "admin": []}
    asyncio.run(staff(t_start, stats))
    results = [out.get(timeout=120) for _ in procs]
    for p in procs:
        p.join(timeout=10)

    def row(name, v):
        v = sorted(v)
        if not v:
            return f"{name:14} none"
        return (f"{name:14} n={len(v):4}  median {statistics.median(v)*1000:6.0f} ms"
                f"  p95 {v[max(0, int(len(v)*.95)-1)]*1000:6.0f} ms  max {v[-1]*1000:6.0f} ms")

    for k in KINDS:
        print(row(k, [x for r in results for x in r["lat"][k]]))
    print(row("band fragment", stats["band"]))
    print(row("admin fragment", stats["admin"]))
    tot = lambda key: sum(r["done"][key] for r in results)  # noqa: E731
    print(f"voted {tot('voted')}/{N}, reloaded after close {tot('closed')}/{N}, after open {tot('open')}/{N}")
    print(f"errors {sum(r['n_errors'] for r in results)} {[e for r in results for e in r['errors']][:6]}"
          f"  transport retries {sum(r['retries'] for r in results)}")
    print(f"socket messages delivered to phones: {sum(r['frames'] for r in results)}")


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
