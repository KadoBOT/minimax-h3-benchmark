import json
import urllib.error
import urllib.request

from bench import store
from bench.models import empty_suite
from bench.server import start_server


def test_api_results(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    store.ensure_dirs()
    s = empty_suite("x", "http://127.0.0.1:8188")
    store.save_suite(s)
    httpd = start_server(9876)
    try:
        data = json.load(urllib.request.urlopen("http://127.0.0.1:9876/api/results"))
        assert data["suite_id"] == "x"
    finally:
        httpd.shutdown()


def test_api_results_idle(tmp_path, monkeypatch):
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "missing.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    httpd = start_server(9877)
    try:
        data = json.load(urllib.request.urlopen("http://127.0.0.1:9877/api/results"))
        assert data["status"] == "idle"
        assert data["phases"] == {}
    finally:
        httpd.shutdown()


def test_videos_and_path_traversal(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir(parents=True)
    (videos / "clip.mp4").write_bytes(b"fake-mp4")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    httpd = start_server(9878)
    try:
        with urllib.request.urlopen("http://127.0.0.1:9878/videos/clip.mp4") as resp:
            assert resp.read() == b"fake-mp4"
        try:
            urllib.request.urlopen("http://127.0.0.1:9878/videos/../../secrets")
            assert False, "expected 404 for path traversal"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
