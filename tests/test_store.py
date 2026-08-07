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
    suite.runs.append(
        Run(id="r1", phase="manual", status="done", timed_s=9.1, config=RunConfig())
    )
    store.save_suite(suite)
    loaded = store.load_suite()
    assert loaded.suite_id == "abc"
    assert loaded.schema_version == 2
    assert loaded.runs[0].timed_s == 9.1
    # atomic file exists and is valid JSON
    data = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert data["suite_id"] == "abc"
    assert data["schema_version"] == 2
    assert data["runs"][0]["timed_s"] == 9.1


def test_update_run_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    suite = empty_suite("abc", "http://127.0.0.1:8188")
    suite.runs.append(Run(id="r1", phase="manual", status="queued"))
    store.save_suite(suite)
    store.patch_run("r1", status="done", timed_s=3.3)
    loaded = store.load_suite()
    assert loaded.runs[0].status == "done"
    assert loaded.runs[0].timed_s == 3.3


def test_load_migrates_v1_phases(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    raw = {
        "suite_id": "legacy",
        "status": "completed",
        "comfy_url": "http://127.0.0.1:8188",
        "baseline": {"seed": 1},
        "phases": {
            "speed": {
                "status": "done",
                "runs": [
                    {
                        "id": "speed_001",
                        "phase": "speed",
                        "status": "done",
                        "config": {"cache": "none", "quant": "nvfp4"},
                        "timed_s": 50.0,
                    }
                ],
            }
        },
    }
    (tmp_path / "benchmark.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load_suite()
    assert loaded.schema_version == 2
    assert len(loaded.runs) == 1
    assert loaded.runs[0].id == "speed_001"
    assert loaded.runs[0].config.model_path == "safetensor"


def test_clear_results_wipes_suite_videos_and_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(store, "SUITE_LOG", tmp_path / "suite.log")
    store.ensure_dirs()
    suite = empty_suite("wipe-me", "http://127.0.0.1:8188")
    suite.runs.append(Run(id="r1", phase="manual", status="done", timed_s=1.0))
    store.save_suite(suite)
    (tmp_path / "videos" / "r1.mp4").write_bytes(b"vid")
    (tmp_path / "runs" / "r1.meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "suite.log").write_text("log\n", encoding="utf-8")

    stats = store.clear_results()
    assert stats["files"] >= 3
    assert not (tmp_path / "benchmark.json").exists()
    assert not (tmp_path / "suite.log").exists()
    assert list((tmp_path / "videos").iterdir()) == []
    assert list((tmp_path / "runs").iterdir()) == []
    # dirs recreated
    assert (tmp_path / "videos").is_dir()
    assert (tmp_path / "runs").is_dir()
