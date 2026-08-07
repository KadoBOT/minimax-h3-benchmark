# bench/server.py
from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import traceback
import urllib.error
import urllib.request
from email import policy
from email.parser import BytesParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bench.constants import (
    BENCHMARK_JSON,
    COMFY_INPUT_DIR,
    DEFAULT_COMFY_URL,
    DEFAULT_FIRST_FRAME,
    RESULTS_DIR,
    UI_DIR,
)
from bench import store
from bench.models import RunConfig
from bench.options import fetch_comfy_options

# Re-bind for monkeypatch.setattr("bench.server.BENCHMARK_JSON", ...) in tests

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

# Browser cancels video range requests on seek/reload — not a server bug.
_CLIENT_DISCONNECT = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


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

    def log_error(self, fmt, *args):
        # Suppress expected disconnect noise from video clients
        msg = fmt % args if args else str(fmt)
        if "ConnectionResetError" in msg or "BrokenPipeError" in msg:
            return
        if "10054" in msg or "10053" in msg:
            return
        super().log_error(fmt, *args)

    def finish(self) -> None:
        try:
            super().finish()
        except _CLIENT_DISCONNECT:
            pass

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except _CLIENT_DISCONNECT:
            pass

    def _safe_write(self, data: bytes) -> bool:
        """Write body bytes; return False if the client already disconnected."""
        try:
            self.wfile.write(data)
            return True
        except _CLIENT_DISCONNECT:
            return False

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
        if path.startswith("/api/input-preview/"):
            return self._send_input_preview(unquote(path[len("/api/input-preview/") :]))
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload-image":
            return self._handle_upload_image()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if parsed.path == "/api/run":
            return self._handle_run(raw)
        if parsed.path == "/api/abort":
            return self._handle_abort()
        if parsed.path == "/api/rate":
            return self._handle_rate(raw)
        if parsed.path == "/api/exclude":
            return self._handle_exclude(raw)
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
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
        except _CLIENT_DISCONNECT:
            return

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
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
        except _CLIENT_DISCONNECT:
            return

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

    def _handle_rate(self, raw: bytes):
        """POST { run_id, rating: 1..10 | null } — human quality score."""
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})
        run_id = body.get("run_id")
        if not run_id or not isinstance(run_id, str):
            return self._json(400, {"error": "run_id required"})
        rating = body.get("rating", None)
        if rating is not None and rating != "":
            try:
                rating = int(rating)
            except (TypeError, ValueError):
                return self._json(400, {"error": "rating must be int 1–10 or null"})
        else:
            rating = None
        try:
            suite = store.set_run_rating(run_id, rating, suite=APP.suite)
            if APP.suite is None:
                # Disk-only path still ok
                pass
            else:
                APP.suite = suite
        except KeyError:
            return self._json(404, {"error": f"run {run_id} not found"})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except FileNotFoundError:
            return self._json(404, {"error": "no suite on disk"})
        return self._json(200, {"ok": True, "run_id": run_id, "rating": rating})

    def _handle_exclude(self, raw: bytes):
        """POST { run_id, excluded: bool } — hide from compare/scores/heatmap."""
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})
        run_id = body.get("run_id")
        if not run_id or not isinstance(run_id, str):
            return self._json(400, {"error": "run_id required"})
        excluded = bool(body.get("excluded", True))
        try:
            suite = store.set_run_excluded(run_id, excluded, suite=APP.suite)
            if APP.suite is not None:
                APP.suite = suite
        except KeyError:
            return self._json(404, {"error": f"run {run_id} not found"})
        except FileNotFoundError:
            return self._json(404, {"error": "no suite on disk"})
        return self._json(200, {"ok": True, "run_id": run_id, "excluded": excluded})

    def _handle_upload_image(self):
        """Accept multipart image, write into ComfyUI input/, return basename for LoadImage."""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype.lower():
            return self._json(400, {"error": "expected multipart/form-data"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 40 * 1024 * 1024:
            return self._json(400, {"error": "invalid content length"})
        body = self.rfile.read(length)
        try:
            filename, data = _extract_multipart_file(ctype, body)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        safe = _safe_image_name(filename)
        if not data:
            return self._json(400, {"error": "empty file"})
        try:
            COMFY_INPUT_DIR.mkdir(parents=True, exist_ok=True)
            dest = COMFY_INPUT_DIR / safe
            dest.write_bytes(data)
        except OSError as e:
            return self._json(500, {"error": f"failed to write Comfy input: {e}"})
        return self._json(200, {"first_frame": safe, "path": str(dest)})

    def _send_input_preview(self, name: str):
        """Serve a file from ComfyUI input/ for the Run panel thumbnail."""
        safe = Path(name.replace("\\", "/")).name
        if not safe or safe in (".", ".."):
            self.send_error(404)
            return
        path = (COMFY_INPUT_DIR / safe).resolve()
        try:
            path.relative_to(COMFY_INPUT_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self._safe_write(data)
        except _CLIENT_DISCONNECT:
            return

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

        try:
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
                            if not self._safe_write(chunk):
                                return
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
                        if not self._safe_write(chunk):
                            return
        except _CLIENT_DISCONNECT:
            return


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server that does not dump client-disconnect stack traces."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_DISCONNECT):
            return
        # Also match nested OSError with WinError 10054/10053
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
            return
        super().handle_error(request, client_address)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _safe_image_name(filename: str) -> str:
    base = Path(filename.replace("\\", "/")).name
    if not base or base in (".", ".."):
        raise ValueError("invalid filename")
    if Path(base).suffix.lower() not in _IMAGE_EXTS:
        raise ValueError("unsupported image type")
    # Keep alnum, dash, underscore, dot
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    if not safe:
        raise ValueError("invalid filename")
    return safe


def _extract_multipart_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    """Return (filename, bytes) from a multipart/form-data body (field name image|file)."""
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    msg = BytesParser(policy=policy.default).parsebytes(header + body)
    for part in msg.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if not filename:
            continue
        if name not in (None, "image", "file", "first_frame"):
            # still accept any file part if filename present
            pass
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload)
        return filename, bytes(payload)
    raise ValueError("no file field in multipart body")


def start_server(port: int = 8787) -> ThreadingHTTPServer:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    httpd = QuietThreadingHTTPServer(("127.0.0.1", port), BenchHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
