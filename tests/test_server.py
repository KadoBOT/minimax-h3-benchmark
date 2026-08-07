import json
import socket
import threading
import urllib.error
import urllib.request

from bench import store
from bench.models import empty_suite
from bench.server import attach_runner, reset_app, start_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def test_api_results(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    store.ensure_dirs()
    s = empty_suite("x", "http://127.0.0.1:8188")
    store.save_suite(s)
    port = _free_port()
    httpd = start_server(port)
    try:
        data = json.load(urllib.request.urlopen(_url(port, "/api/results")))
        assert data["suite_id"] == "x"
        assert "runs" in data
    finally:
        httpd.shutdown()
        reset_app()


def test_api_results_idle(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "missing.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    port = _free_port()
    httpd = start_server(port)
    try:
        data = json.load(urllib.request.urlopen(_url(port, "/api/results")))
        assert data["status"] == "idle"
        assert data["phases"] == {}
        assert data["runs"] == []
    finally:
        httpd.shutdown()
        reset_app()


def test_videos_and_path_traversal(tmp_path, monkeypatch):
    reset_app()
    videos = tmp_path / "videos"
    videos.mkdir(parents=True)
    (videos / "clip.mp4").write_bytes(b"fake-mp4")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    port = _free_port()
    httpd = start_server(port)
    try:
        with urllib.request.urlopen(_url(port, "/videos/clip.mp4")) as resp:
            assert resp.read() == b"fake-mp4"
        try:
            urllib.request.urlopen(_url(port, "/videos/../../secrets"))
            assert False, "expected 404 for path traversal"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
        reset_app()


def test_video_range_request(tmp_path, monkeypatch):
    reset_app()
    videos = tmp_path / "videos"
    videos.mkdir(parents=True)
    payload = b"0123456789ABCDEF"
    (videos / "clip.mp4").write_bytes(payload)
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    port = _free_port()
    httpd = start_server(port)
    try:
        req = urllib.request.Request(
            _url(port, "/videos/clip.mp4"),
            headers={"Range": "bytes=0-3"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 206
            assert resp.headers.get("Content-Range", "").startswith("bytes 0-3/")
            assert resp.read() == b"0123"
            assert "video/mp4" in (resp.headers.get("Content-Type") or "")
    finally:
        httpd.shutdown()
        reset_app()


class _FakeComfy:
    base_url = "http://127.0.0.1:8188"

    def system_stats(self):
        raise OSError("comfy down")

    def cancel_all(self):
        pass


class _FakeRunner:
    def __init__(
        self,
        hold: threading.Event | None = None,
        started: threading.Event | None = None,
    ):
        self.comfy = _FakeComfy()
        self.calls: list = []
        self._hold = hold
        self._started = started
        self.aborted = False

    def run_one(self, suite, cfg):
        self.calls.append(cfg)
        if self._started is not None:
            self._started.set()
        if self._hold is not None:
            self._hold.wait(timeout=10)

    def request_abort(self):
        self.aborted = True
        if self._hold is not None:
            self._hold.set()


def test_api_run_and_busy_409(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    store.ensure_dirs()

    hold = threading.Event()
    started = threading.Event()
    suite = empty_suite("run-suite", "http://127.0.0.1:8188")
    runner = _FakeRunner(hold=hold, started=started)
    attach_runner(runner, suite)

    port = _free_port()
    httpd = start_server(port)
    try:
        req = urllib.request.Request(
            _url(port, "/api/run"),
            data=json.dumps({"cache": "easy", "steps": 16}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 202
            body = json.load(resp)
            assert body["status"] == "started"

        assert started.wait(timeout=5), "run_one was not invoked"
        assert runner.calls

        req2 = urllib.request.Request(
            _url(port, "/api/run"),
            data=json.dumps({"cache": "h3"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req2)
            assert False, "expected 409 busy"
        except urllib.error.HTTPError as e:
            assert e.code == 409
            err = json.loads(e.read().decode())
            assert err["error"] == "busy"
    finally:
        hold.set()
        httpd.shutdown()
        reset_app()


def test_api_run_503_without_runner(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    port = _free_port()
    httpd = start_server(port)
    try:
        req = urllib.request.Request(
            _url(port, "/api/run"),
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected 503"
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        httpd.shutdown()
        reset_app()


def test_api_options(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    fake = {
        "schedulers": ["beta57"],
        "samplers": ["euler"],
        "source": "fallback",
        "defaults": {"steps": 20},
    }
    monkeypatch.setattr("bench.server.fetch_comfy_options", lambda url, timeout=3.0: fake)
    port = _free_port()
    httpd = start_server(port)
    try:
        data = json.load(urllib.request.urlopen(_url(port, "/api/options")))
        assert data["source"] == "fallback"
        assert data["schedulers"] == ["beta57"]
        assert data["samplers"] == ["euler"]
    finally:
        httpd.shutdown()
        reset_app()


def test_api_health(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    suite = empty_suite("h", "http://127.0.0.1:8188")
    runner = _FakeRunner()
    attach_runner(runner, suite)
    port = _free_port()
    httpd = start_server(port)
    try:
        data = json.load(urllib.request.urlopen(_url(port, "/api/health")))
        assert data["ok"] is True
        assert data["comfy_ok"] is False
        assert data["comfy_url"] == "http://127.0.0.1:8188"
    finally:
        httpd.shutdown()
        reset_app()


def test_api_upload_image(tmp_path, monkeypatch):
    from bench import server as server_mod
    from bench.server import attach_runner, reset_app, start_server

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(server_mod, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(server_mod, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(server_mod, "RESULTS_DIR", tmp_path)
    reset_app()
    port = _free_port()
    httpd = start_server(port)
    try:
        boundary = "----benchboundary"
        filename = "test_upload.png"
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + b"\x89PNG\r\nfake" + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/upload-image",
            data=payload,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(payload)),
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        assert data["first_frame"] == filename
        assert (input_dir / filename).is_file()

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/input-preview/{filename}"
        ) as prev:
            assert prev.read().startswith(b"\x89PNG")
    finally:
        httpd.shutdown()
        reset_app()


def test_api_abort(tmp_path, monkeypatch):
    reset_app()
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    suite = empty_suite("a", "http://127.0.0.1:8188")
    runner = _FakeRunner()
    attach_runner(runner, suite)
    port = _free_port()
    httpd = start_server(port)
    try:
        req = urllib.request.Request(
            _url(port, "/api/abort"),
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert json.load(resp)["ok"] is True
        assert runner.aborted is True
    finally:
        httpd.shutdown()
        reset_app()
