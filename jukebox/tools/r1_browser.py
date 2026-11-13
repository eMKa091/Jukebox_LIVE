"""R1 in a real browser, against any running copy (docs/08 steps 4.3 and 5.3).

    python tools/r1_browser.py <base url> <admin user> <admin password>

Needs Playwright (`pip install playwright`, `playwright install chromium`),
which the app itself does not; CHROME=<path> uses a Chromium already there.

Makes its own event (two songs, one round), then:
1. a phone joins and sits on the ballot; its socket says `ready`;
2. the console closes the round while the phone's socket is made deaf to
   updates (Playwright routes the socket and drops them): the phone slept
   through it. Woken (hidden 6 s, shown again), it must reload onto the
   standings by itself;
3. updates flow again; the console reopens the round; the phone must be told
   and reload onto the ballot within the 3 s spread.
"""

import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

base, user, password = sys.argv[1:4]
results = []
deaf = {"on": False}


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""), flush=True)


def route(ws):
    server = ws.connect_to_server()
    ws.on_message(lambda m: server.send(m))

    def down(m):
        if deaf["on"] and '"update"' in str(m):
            return
        ws.send(m)

    server.on_message(down)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROME") or None)

    admin = browser.new_context()
    a = admin.request
    a.post(f"{base}/admin/login", form={"username": user, "password": password})
    for title, artist in (("Hello", "Adele"), ("Africa", "Toto")):
        a.post(f"{base}/admin/songs", form={"title": title, "artist": artist})
    made = a.post(f"{base}/admin/events", max_redirects=0, form={
        "name": f"R1 {time.strftime('%H%M%S')}", "starts_at": "2026-12-31T20:00", "venue": "",
        "round_count": "1", "max_votes": "2"})
    event_id = re.search(r"/admin/events/(\d+)", made.headers["location"]).group(1)
    for to in ("ready", "live"):
        a.post(f"{base}/admin/events/{event_id}/state", form={"to": to})
    console = a.get(f"{base}/admin/events/{event_id}").text()
    round_id = re.search(r'action="/admin/rounds/(\d+)/state"', console).group(1)
    a.post(f"{base}/admin/rounds/{round_id}/state", form={"to": "open"})
    slug = re.search(r"/e/([a-z0-9-]+)", a.get(f"{base}/admin/events/{event_id}?tab=share").text()).group(1)

    phone = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    phone.route_web_socket(re.compile(r".*/stream$"), route)
    frames = []
    phone.on("websocket", lambda ws: ws.on("framereceived", lambda f: frames.append(f)))
    phone.goto(f"{base}/e/{slug}")
    phone.fill("input[name=display_name]", "Prohlížeč")
    phone.click("button[type=submit]")
    phone.wait_for_selector("#ballot", timeout=15000)
    deadline = time.time() + 15
    while not any('"ready"' in str(f) for f in frames) and time.time() < deadline:
        phone.wait_for_timeout(100)
    check("the ballot's socket says ready", any('"ready"' in str(f) for f in frames))

    # -- 2: closed while the phone hears nothing, then woken --------------
    deaf["on"] = True
    a.post(f"{base}/admin/rounds/{round_id}/state", form={"to": "closed"})
    phone.wait_for_timeout(1500)
    check("deaf, the phone is still on the ballot", phone.query_selector("#ballot") is not None)
    deaf["on"] = False
    phone.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    phone.wait_for_timeout(6000)
    phone.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    try:
        phone.wait_for_selector("text=Kolo právě skončilo", timeout=10000)
        check("woken, it reloads onto the standings", True)
    except Exception as exc:  # noqa: BLE001
        check("woken, it reloads onto the standings", False, phone.url + " " + str(exc)[:200])

    # -- 3: the console reopens the round; the phone is told -------------
    phone.wait_for_timeout(1500)  # the reloaded page's socket comes up
    t = time.time()
    a.post(f"{base}/admin/rounds/{round_id}/state", form={"to": "open"})
    try:
        phone.wait_for_selector("#ballot", timeout=10000)
        check("the phone is told and reloads onto the ballot", True, f"{time.time() - t:.1f} s")
    except Exception as exc:  # noqa: BLE001
        check("the phone is told and reloads onto the ballot", False, str(exc)[:200])

    a.post(f"{base}/admin/rounds/{round_id}/state", form={"to": "closed"})
    a.post(f"{base}/admin/events/{event_id}/state", form={"to": "closed"})
    browser.close()

sys.exit(0 if all(results) else 1)
