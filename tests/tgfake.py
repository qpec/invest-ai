"""In-process stdlib Telegram Bot API fake (tech-arch §13 'against an in-process http.server fake').

Each test constructs FakeTelegram(), sets .responses per-method, and points the
client at .base_url. Captured requests land in .requests for shape assertions.

The autouse no-network guard (conftest §a) blocks socket.connect AND
socket.create_connection. The fake's *server* side (bind/accept) is unaffected, but
the client's outbound urllib call reaches http.client -> socket.create_connection,
which is blocked. allow_loopback() re-permits connections to 127.0.0.1 ONLY, so the
in-process fake is reachable while any real off-box network stays blocked. Pristine
originals are captured here at import (before any per-test guard patch runs).
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Pristine originals, captured at import (collection time) before the per-test
# autouse guard swaps them for the blocker.
_ORIG_CONNECT = socket.socket.connect
_ORIG_CREATE_CONNECTION = socket.create_connection

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def allow_loopback(monkeypatch) -> None:
    """Re-permit loopback-only sockets for a test that talks to the in-process fake.

    Keeps the no-network guard's intent intact: connections to any non-loopback
    host still raise. Install AFTER the autouse guard (i.e. inside a fixture that
    depends on monkeypatch) so this override wins for the test's duration.
    """

    def _connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise RuntimeError(
                f"non-loopback connect to {host!r} blocked (no-network guard, tech-arch §13)"
            )
        return _ORIG_CONNECT(self, address, *args, **kwargs)

    def _create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise RuntimeError(
                f"non-loopback create_connection to {host!r} blocked (no-network guard, tech-arch §13)"
            )
        return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket, "create_connection", _create_connection)


class FakeTelegram:
    def __init__(self):
        self.requests = []           # list of (method_name, parsed_json_or_raw_bytes, headers)
        self.responses = {}          # method_name -> dict body OR list of dict bodies (popped in order)
        self.files = {}              # file_path -> bytes (for the file download GET)
        server = self  # noqa

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):  # keep test output quiet
                pass

            def _send_json(self, body, code=200):
                raw = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = urlparse(self.path).path
                # file download: /file/bot<token>/<file_path>
                marker = "/file/bot"
                if marker in path:
                    fp = path.split("/", 3)[-1]
                    data = server.files.get(fp, b"")
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self._route(path, raw=b"")

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                self._route(urlparse(self.path).path, raw=raw)

            def _route(self, path, *, raw):
                method = path.rstrip("/").split("/")[-1]  # /bot<token>/<method>
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("application/json") and raw:
                    parsed = json.loads(raw)
                else:
                    parsed = raw  # multipart or empty
                server.requests.append((method, parsed, dict(self.headers)))
                resp = server.responses.get(method, {"ok": True, "result": {}})
                if isinstance(resp, list):
                    resp = resp.pop(0) if len(resp) > 1 else resp[0]
                code = 429 if resp.get("error_code") == 429 else (
                    200 if resp.get("ok", True) else 400)
                self._send_json(resp, code=code)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address
        self.base_url = f"http://{host}:{port}"

    def calls(self, method_name):
        return [r for r in self.requests if r[0] == method_name]

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()
