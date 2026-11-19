"""Loopback-only bridge between the local first-car history and its existing UI."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dzen_first_car import connect, mark, queue_snapshot
from dzen_first_car_signals import mark_signal, signal_snapshot

LAB = Path(__file__).resolve().parents[1] / "lab" / "dzen-first-car"
ASSETS = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/queue.js": ("queue.js", "application/javascript"), "/queue.css": ("queue.css", "text/css")}


def serve(db_path, port, replay, replay_at):
    if replay and replay_at is None:
        raise ValueError("Local replay requires an explicit --as-of")
    archive = json.loads((LAB / "snapshots.js").read_text().partition(" = ")[2].strip().removesuffix(";"))

    class Handler(BaseHTTPRequestHandler):
        def now(self):
            return replay_at if replay_at is not None else int(datetime.now(UTC).timestamp())

        def send(self, data, media_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", media_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def local_origin(self):
            return f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if self.headers.get("Host") != self.local_origin():
                self.send_error(403)
                return
            if self.path in ASSETS:
                filename, media_type = ASSETS[self.path]
                self.send((LAB / filename).read_bytes(), media_type)
            elif self.path == "/snapshots.js":
                now = self.now()
                with closing(connect(db_path, replay=replay)) as db:
                    data = queue_snapshot(db, now, replay=replay)
                    data["signals"] = signal_snapshot(db, now)
                data.update(bridge=True, demo=archive["demo"], demo_observed_at=archive["demo_observed_at"])
                self.send(("window.firstCarSnapshots = " + json.dumps(data) + ";").encode(), "application/javascript")
            else:
                self.send_error(404)

        def do_POST(self):
            origin = f"http://{self.local_origin()}"
            if (self.headers.get("Host") != self.local_origin() or self.headers.get("Origin") != origin
                    or self.headers.get_content_type() != "application/json"):
                self.send_error(403)
                return
            actions = {"/decision": mark, "/signal-decision": mark_signal}
            if self.path not in actions:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid request length")
                data = json.loads(self.rfile.read(length))
                with closing(connect(db_path, replay=replay)) as db:
                    actions[self.path](db, data["url"], data["action"], self.now())
            except (ValueError, KeyError, TypeError, sqlite3.Error):
                self.send(b'{"saved":false}', "application/json", 400)
                return
            self.send(b'{"saved":true}', "application/json")

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Local queue: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
