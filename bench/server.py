# bench/server.py
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bench.constants import BENCHMARK_JSON, RESULTS_DIR, UI_DIR

# Re-bind for monkeypatch.setattr("bench.server.BENCHMARK_JSON", ...) in tests


class BenchHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass  # quieter; optional write to suite.log

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/results":
            return self._send_results()
        if path.startswith("/results/"):
            return self._send_file(RESULTS_DIR / unquote(path[len("/results/") :]))
        if path.startswith("/videos/"):
            return self._send_file(RESULTS_DIR / "videos" / unquote(path[len("/videos/") :]))
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _send_results(self):
        if not BENCHMARK_JSON.exists():
            body = json.dumps({"status": "idle", "phases": {}}).encode()
        else:
            body = BENCHMARK_JSON.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        path = path.resolve()
        root = RESULTS_DIR.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            self.send_error(404)
            return
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_server(port: int = 8787) -> ThreadingHTTPServer:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BenchHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
