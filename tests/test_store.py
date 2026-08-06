import json
from pathlib import Path

from bench.models import Run, RunConfig, empty_suite
from bench import store


def test_save_and_load_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    suite = empty_suite("abc", "http://127.0.0.1:8188")
    suite.phases["speed"].runs.append(
        Run(id="r1", phase="speed", status="done", timed_s=9.1, config=RunConfig())
    )
    store.save_suite(suite)
    loaded = store.load_suite()
    assert loaded.suite_id == "abc"
    assert loaded.phases["speed"].runs[0].timed_s == 9.1
    # atomic file exists and is valid JSON
    data = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert data["suite_id"] == "abc"


def test_update_run_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    suite = empty_suite("abc", "http://127.0.0.1:8188")
    suite.phases["speed"].runs.append(Run(id="r1", phase="speed", status="queued"))
    store.save_suite(suite)
    store.patch_run("speed", "r1", status="done", timed_s=3.3)
    loaded = store.load_suite()
    assert loaded.phases["speed"].runs[0].status == "done"
    assert loaded.phases["speed"].runs[0].timed_s == 3.3
