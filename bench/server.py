# bench/server.py
from __future__ import annotations

import json
import mimetypes
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bench.constants import BENCHMARK_JSON, RESULTS_DIR, UI_DIR

# Re-bind for monkeypatch.setattr("bench.server.BENCHMARK_JSON", ...) in tests

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


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

    def do_HEAD(self):
        # Browsers often HEAD video URLs before GET.
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/videos/"):
            return self._send_file(
                RESULTS_DIR / "videos" / unquote(path[len("/videos/") :]),
                head_only=True,
            )
        if path.startswith("/results/"):
            return self._send_file(
                RESULTS_DIR / unquote(path[len("/results/") :]),
                head_only=True,
            )
        return self.do_GET()

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

    def _send_file(self, path: Path, head_only: bool = False):
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

        file_size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix.lower() == ".mp4" and ctype == "application/octet-stream":
            ctype = "video/mp4"

        range_header = self.headers.get("Range")
        if range_header:
            m = _RANGE_RE.match(range_header.strip())
            if not m:
                self.send_error(416, "Invalid Range")
                return
            start_s, end_s = m.group(1), m.group(2)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            if start >= file_size or end >= file_size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not head_only:
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)


def start_server(port: int = 8787) -> ThreadingHTTPServer:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BenchHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
