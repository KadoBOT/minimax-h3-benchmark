# bench/server.py
from __future__ import annotations

import json
import mimetypes
import re
import threading
import traceback
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bench.constants import BENCHMARK_JSON, DEFAULT_COMFY_URL, RESULTS_DIR, UI_DIR
from bench.models import RunConfig
from bench.options import fetch_comfy_options

# Re-bind for monkeypatch.setattr("bench.server.BENCHMARK_JSON", ...) in tests

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class BenchApp:
    lock = threading.Lock()
    runner = None
    suite = None
    worker = None
    comfy_url = DEFAULT_COMFY_URL


APP = BenchApp()


def attach_runner(runner, suite) -> None:
    APP.runner = runner
    APP.suite = suite
    APP.comfy_url = runner.comfy.base_url


def reset_app() -> None:
    """Clear process-global controller (for tests)."""
    with APP.lock:
        APP.runner = None
        APP.suite = None
        APP.worker = None
        APP.comfy_url = DEFAULT_COMFY_URL


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
        if path == "/api/options":
            return self._send_options()
        if path == "/api/health":
            return self._send_health()
        if path.startswith("/results/"):
            return self._send_file(RESULTS_DIR / unquote(path[len("/results/") :]))
        if path.startswith("/videos/"):
            return self._send_file(RESULTS_DIR / "videos" / unquote(path[len("/videos/") :]))
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if parsed.path == "/api/run":
            return self._handle_run(raw)
        if parsed.path == "/api/abort":
            return self._handle_abort()
        self.send_error(404)

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

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_results(self):
        # Prefer in-memory suite (same object runner updates); else disk; else idle.
        if APP.suite is not None:
            payload = APP.suite.to_dict()
            if "runs" not in payload:
                payload["runs"] = []
            body = json.dumps(payload).encode()
        elif BENCHMARK_JSON.exists():
            try:
                data = json.loads(BENCHMARK_JSON.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"status": "idle", "phases": {}, "runs": []}
            if "runs" not in data:
                data["runs"] = []
            body = json.dumps(data).encode()
        else:
            body = json.dumps({"status": "idle", "phases": {}, "runs": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_options(self):
        data = fetch_comfy_options(APP.comfy_url)
        return self._json(200, data)

    def _send_health(self):
        comfy_ok = False
        url = APP.comfy_url
        try:
            if APP.runner is not None and getattr(APP.runner, "comfy", None) is not None:
                APP.runner.comfy.system_stats()
                comfy_ok = True
            else:
                req = urllib.request.Request(f"{url.rstrip('/')}/system_stats")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    comfy_ok = 200 <= getattr(resp, "status", 200) < 300
        except Exception:
            comfy_ok = False
        return self._json(200, {"ok": True, "comfy_ok": comfy_ok, "comfy_url": url})

    def _handle_run(self, raw: bytes):
        if APP.runner is None or APP.suite is None:
            return self._json(503, {"error": "runner not attached"})
        with APP.lock:
            if APP.worker is not None and APP.worker.is_alive():
                return self._json(409, {"error": "busy"})
            try:
                body = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid json"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "body must be object"})
            cfg = RunConfig.from_dict(body)

            def job():
                try:
                    APP.runner.run_one(APP.suite, cfg)
                except KeyboardInterrupt:
                    pass
                except Exception:
                    traceback.print_exc()

            t = threading.Thread(target=job, daemon=True)
            APP.worker = t
            t.start()
        return self._json(202, {"status": "started"})

    def _handle_abort(self):
        if APP.runner is not None:
            APP.runner.request_abort()
        return self._json(200, {"ok": True})

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
