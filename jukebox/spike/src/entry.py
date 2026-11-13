"""Throwaway spike: one probe per open question in docs/08 section 4."""

import json
import time
import traceback

from workers import DurableObject, Response, WorkerEntrypoint


def _report(fn):
    try:
        return {"ok": True, "answer": fn()}
    except BaseException as exc:  # noqa: BLE001 - a probe reports everything
        return {"ok": False, "error": repr(exc), "trace": traceback.format_exc()[-1500:]}


def u1_imports():
    out = {}
    for name in ("fastapi", "jinja2", "multipart", "itsdangerous", "qrcode", "tzdata", "starlette", "pydantic"):
        mod = __import__(name)
        out[name] = getattr(mod, "__version__", "imported")
    from zoneinfo import ZoneInfo
    import datetime
    out["Europe/Prague now"] = datetime.datetime.now(ZoneInfo("Europe/Prague")).isoformat()
    import io, qrcode, qrcode.image.svg
    img = qrcode.make("https://hlasuj.jukeboxheroes.cz/e/x", image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO(); img.save(buf)
    out["qr svg bytes"] = len(buf.getvalue())
    return out


def u6_files():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    return {
        "here": str(here),
        "listing": sorted(str(p.relative_to(here)) for p in here.rglob("*") if "vendor" not in p.parts)[:40],
        "sql": (here / "sql" / "probe.sql").read_text(),
        "template bytes": len((here / "templates" / "rows.html").read_text()),
    }


def u7_argon2():
    from argon2 import PasswordHasher
    t = time.perf_counter()
    h = PasswordHasher().hash("correct-horse-battery-staple")
    ok = PasswordHasher().verify(h, "correct-horse-battery-staple")
    return {"hash": h[:30], "verified": ok, "ms": round((time.perf_counter() - t) * 1000)}


def u7_pbkdf2():
    import hashlib
    t = time.perf_counter()
    hashlib.pbkdf2_hmac("sha256", b"correct-horse-battery-staple", b"salt" * 4, 600_000)
    return {"ms": round((time.perf_counter() - t) * 1000)}


class Jukebox(DurableObject):
    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self.sql = ctx.storage.sql
        self._app = None

    # ---------------------------------------------------------------- U3 --
    def u3(self):
        s = self.sql
        s.exec("DROP TABLE IF EXISTS t")
        s.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        cur = s.exec("INSERT INTO t (v) VALUES (?)", "a")
        out = {"cursor rowsWritten": cur.rowsWritten, "cursor attrs": [a for a in dir(cur) if not a.startswith("_")][:30]}
        out["last_insert_rowid"] = s.exec("SELECT last_insert_rowid() AS id").one()
        s.exec("INSERT INTO t (v) VALUES (?), (?)", "b", "c")
        out["changes"] = s.exec("SELECT changes() AS n").one()
        out["returning"] = s.exec("INSERT INTO t (v) VALUES (?) RETURNING id", "d").one()
        out["toArray"] = s.exec("SELECT id, v FROM t ORDER BY id").toArray()
        out["raw"] = [list(r) for r in s.exec("SELECT id, v FROM t ORDER BY id").raw()]
        out["columnNames"] = list(s.exec("SELECT id, v FROM t").columnNames)
        out["none binds"] = s.exec("SELECT ? IS NULL AS nul", None).one()
        out["bytes"] = s.exec("SELECT typeof(?) AS ty", b"\x00\x01").one()
        out["many params"] = s.exec("SELECT " + ",".join("?" * 100), *range(100)).raw().toArray()[0][99] == 99
        return out

    # ---------------------------------------------------------------- U4 --
    def u4(self):
        s = self.sql

        class Boom(Exception):
            pass

        s.exec("DROP TABLE IF EXISTS u4")
        s.exec("CREATE TABLE u4 (id INTEGER PRIMARY KEY)")

        def work():
            s.exec("INSERT INTO u4 (id) VALUES (1)")
            raise Boom("from python")

        out = {}
        try:
            self.ctx.storage.transactionSync(work)
            out["raised"] = None
        except BaseException as exc:  # noqa: BLE001
            out["raised"] = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
            out["is Boom"] = isinstance(exc, Boom)
        out["rows after"] = s.exec("SELECT COUNT(*) AS n FROM u4").one()["n"]
        out["return value"] = self.ctx.storage.transactionSync(lambda: 42)

        # And a constraint failure: what type arrives?
        s.exec("DROP TABLE IF EXISTS u4b")
        s.exec("CREATE TABLE u4b (id INTEGER PRIMARY KEY, v TEXT UNIQUE)")
        s.exec("INSERT INTO u4b (v) VALUES ('x')")
        try:
            s.exec("INSERT INTO u4b (v) VALUES ('x')")
        except BaseException as exc:  # noqa: BLE001
            out["unique failure"] = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        try:
            s.exec("BEGIN")
        except BaseException as exc:  # noqa: BLE001
            out["BEGIN"] = f"{type(exc).__name__}: {exc}"
        try:
            s.exec("PRAGMA user_version")
            out["PRAGMA user_version"] = "allowed"
        except BaseException as exc:  # noqa: BLE001
            out["PRAGMA user_version"] = f"{type(exc).__name__}: {exc}"
        return out

    # ---------------------------------------------------------------- U5 --
    def u5(self):
        s = self.sql
        out = {"foreign_keys pragma": s.exec("PRAGMA foreign_keys").toArray()}
        for t in ("c", "p", "pi"):
            s.exec(f"DROP TABLE IF EXISTS {t}")
        s.exec("CREATE TABLE p (id INTEGER PRIMARY KEY, state TEXT CHECK (state IN ('a','live')))")
        s.exec("CREATE TABLE c (id INTEGER PRIMARY KEY, p_id INTEGER NOT NULL REFERENCES p (id) ON DELETE CASCADE)")
        s.exec("CREATE UNIQUE INDEX one_live ON p (state) WHERE state = 'live'")
        s.exec("INSERT INTO p (id, state) VALUES (1, 'a')")
        s.exec("INSERT INTO c (p_id) VALUES (1)")
        s.exec("DELETE FROM p WHERE id = 1")
        out["cascade left children"] = s.exec("SELECT COUNT(*) AS n FROM c").one()["n"]
        try:
            s.exec("INSERT INTO c (p_id) VALUES (999)")
            out["dangling fk insert"] = "accepted"
        except BaseException as exc:  # noqa: BLE001
            out["dangling fk insert"] = f"refused: {exc}"
        try:
            s.exec("INSERT INTO p (state) VALUES ('nope')")
            out["check"] = "accepted"
        except BaseException as exc:  # noqa: BLE001
            out["check"] = f"refused: {exc}"
        s.exec("INSERT INTO p (state) VALUES ('live')")
        try:
            s.exec("INSERT INTO p (state) VALUES ('live')")
            out["partial unique"] = "accepted"
        except BaseException as exc:  # noqa: BLE001
            out["partial unique"] = f"refused: {exc}"
        out["collate nocase + lower()"] = s.exec("SELECT lower('ÁBC') AS l, 'a' = 'A' COLLATE NOCASE AS eq").one()
        out["ON CONFLICT DO NOTHING / upsert"] = "see real app"
        out["fk pragma set"] = s.exec("PRAGMA foreign_keys = ON").toArray()
        return out

    # ---------------------------------------------------------------- U2 --
    def app(self):
        if self._app is None:
            from fastapi import FastAPI, Form, Request
            from fastapi.responses import HTMLResponse, RedirectResponse
            from jinja2 import Environment, FileSystemLoader, select_autoescape
            from pathlib import Path

            env = Environment(
                loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
                autoescape=select_autoescape(["html"]),
            )
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            sql = self.sql

            @app.get("/app/hello")
            async def hello(request: Request):
                return {"path": request.url.path, "cookie": request.cookies.get("x")}

            @app.get("/app/sync")
            def sync_handler():
                return {"sync": "ran"}

            @app.post("/app/form")
            async def form(name: str = Form(...), song_ids: list[int] = Form(default_factory=list)):
                r = RedirectResponse("/app/hello", status_code=303)
                r.set_cookie("x", "y", httponly=True)
                r.set_cookie("z", "w")
                return r

            @app.get("/app/ballot", response_class=HTMLResponse)
            async def ballot():
                # U9's shape: 420 songs out of SQLite, through Jinja.
                t0 = time.perf_counter()
                rows = sql.exec("SELECT id, title, artist FROM songs ORDER BY artist, title").toArray()
                t1 = time.perf_counter()
                html = env.get_template("rows.html").render(title="ballot", songs=rows)
                t2 = time.perf_counter()
                return HTMLResponse(html, headers={"Server-Timing": f"sql;dur={(t1-t0)*1000:.1f}, render;dur={(t2-t1)*1000:.1f}"})

            self._app = app
        return self._app

    def seed(self, n=420):
        s = self.sql
        s.exec("CREATE TABLE IF NOT EXISTS songs (id INTEGER PRIMARY KEY, title TEXT, artist TEXT)")
        if s.exec("SELECT COUNT(*) AS n FROM songs").one()["n"] < n:
            s.exec("DELETE FROM songs")
            for i in range(n):
                s.exec("INSERT INTO songs (title, artist) VALUES (?, ?)", f"Píseň číslo {i}", f"Umělec {i % 37}")
        return n

    # ---------------------------------------------------------------- U8 --
    def ws_accept(self, request):
        from js import WebSocketPair
        from pyodide.ffi import to_js
        client, server = WebSocketPair.new().object_values()
        self.ctx.acceptWebSocket(server, to_js(["event:1"]))
        server.serializeAttachment(json.dumps({"joined": time.time()}))
        return Response(None, status=101, web_socket=client)

    def ws_broadcast(self, tag, text):
        sockets = self.ctx.getWebSockets(tag)
        for ws in sockets:
            ws.send(text)
        return len(sockets)

    async def webSocketMessage(self, ws, message):
        ws.send(json.dumps({"echo": str(message), "tags": list(self.ctx.getTags(ws)), "attachment": ws.deserializeAttachment()}))

    async def webSocketClose(self, ws, code, reason, was_clean):
        ws.close(code, "closing")

    # -------------------------------------------------------------- fetch --
    async def fetch(self, request):
        from urllib.parse import urlparse
        path = urlparse(request.url).path
        if path.startswith("/app/"):
            from workers import asgi
            if path == "/app/ballot":
                self.seed()
            return await asgi.fetch(self.app(), request, self.env)
        if path == "/ws":
            return self.ws_accept(request)
        if path == "/ws/broadcast":
            n = self.ws_broadcast("event:1", json.dumps({"kind": "round", "reload": True}))
            return Response(json.dumps({"sent": n}), headers={"content-type": "application/json"})
        probes = {"/u3": self.u3, "/u4": self.u4, "/u5": self.u5}
        if path in probes:
            return Response(json.dumps(_report(probes[path]), default=str, ensure_ascii=False, indent=2),
                            headers={"content-type": "application/json"})
        return Response("no such probe", status=404)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        from urllib.parse import urlparse
        path = urlparse(request.url).path
        if path == "/ping":
            return Response("pong")
        local = {"/u1": u1_imports, "/u6": u6_files, "/u7": u7_argon2, "/u7/pbkdf2": u7_pbkdf2}
        if path in local:
            return Response(json.dumps(_report(local[path]), default=str, ensure_ascii=False, indent=2),
                            headers={"content-type": "application/json"})
        stub = self.env.JUKEBOX.getByName("jukebox")
        return await stub.fetch(request)
