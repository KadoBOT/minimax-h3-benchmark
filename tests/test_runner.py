from pathlib import Path

from bench import store
from bench.models import Run, RunConfig
from bench.runner import BenchmarkRunner


class FakeComfy:
    base_url = "http://fake"

    def __init__(self, fail_on: set[int] | None = None):
        self.n = 0
        self.fail_on = fail_on or set()
        self.downloaded: list[tuple[str, Path]] = []

    def run_prompt(self, prompt):
        self.n += 1
        if self.n in self.fail_on:
            raise RuntimeError(f"boom at call {self.n}")
        return (
            f"p{self.n}",
            1.5 + self.n * 0.01,
            {
                "outputs": {
                    "110": {
                        "gifs": [
                            {
                                "filename": "t.mp4",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            },
        )

    def find_first_video(self, hist):
        return "t.mp4", "", "output"

    def download_output_file(self, fn, sub, typ, dest):
        dest.write_bytes(b"fake")
        self.downloaded.append((fn, dest))
        return dest


def _patch_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")


def _patch_matrix_and_workflow(monkeypatch, speed_runs=None, quality_runs=None, scale_runs=None):
    from bench.models import Run as RunCls

    if speed_runs is None:
        speed_runs = [
            RunCls(id="s1", phase="speed", config=RunConfig(cache="none")),
            RunCls(id="s2", phase="speed", config=RunConfig(cache="easy")),
        ]
    monkeypatch.setattr(
        "bench.runner.build_speed_runs",
        lambda: [RunCls(id=r.id, phase=r.phase, config=r.config) for r in speed_runs],
    )
    monkeypatch.setattr(
        "bench.runner.build_quality_runs",
        quality_runs if quality_runs is not None else (lambda base: []),
    )
    monkeypatch.setattr(
        "bench.runner.build_scale_runs",
        scale_runs if scale_runs is not None else (lambda base: []),
    )
    monkeypatch.setattr("bench.runner.apply_config", lambda ui, cfg: {"1": {}})
    monkeypatch.setattr("bench.runner.load_ui_workflow", lambda p: {})


def test_runner_speed_then_base(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    _patch_matrix_and_workflow(monkeypatch)

    r = BenchmarkRunner(FakeComfy())
    suite = r.init_suite()
    r.run_phase(suite, "speed")
    assert all(x.status == "done" for x in suite.phases["speed"].runs)
    assert suite.phases["speed"].runs[0].timed_s is not None
    assert suite.phases["speed"].runs[0].warmup_s is not None
    assert suite.phases["speed"].runs[0].video_path == "videos/s1.mp4"
    assert (tmp_path / "videos" / "s1.mp4").read_bytes() == b"fake"


def test_run_all_picks_fastest_and_completes(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    from bench.models import Run as RunCls

    quality = [
        RunCls(id="q1", phase="quality", config=RunConfig(cache="easy", steps=16)),
    ]
    scale = [
        RunCls(id="sc1", phase="scale", config=RunConfig(cache="easy", mp=0.5)),
    ]
    _patch_matrix_and_workflow(
        monkeypatch,
        quality_runs=lambda base: [
            RunCls(id="q1", phase="quality", config=RunConfig(cache=base.cache, steps=16))
        ],
        scale_runs=lambda base: [
            RunCls(id="sc1", phase="scale", config=RunConfig(cache=base.cache, mp=0.5))
        ],
    )

    updates: list[str] = []
    r = BenchmarkRunner(FakeComfy(), on_update=lambda s: updates.append(s.status))
    suite = r.run_all()
    assert suite.status == "completed"
    assert suite.base_config is not None
    # FakeComfy times: call1 warm s1=1.51, call2 timed s1=1.52, call3 warm s2=1.53, call4 timed s2=1.54
    # fastest timed is s1
    assert suite.base_config["cache"] == "none"
    assert all(x.status == "done" for x in suite.phases["speed"].runs)
    assert suite.phases["quality"].runs[0].status == "done"
    assert suite.phases["scale"].runs[0].status == "done"
    assert "completed" in updates
    loaded = store.load_suite()
    assert loaded.suite_id == suite.suite_id
    assert loaded.status == "completed"


def test_resume_skips_done(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    _patch_matrix_and_workflow(monkeypatch)

    comfy = FakeComfy()
    r = BenchmarkRunner(comfy)
    suite = r.init_suite()
    r.run_phase(suite, "speed")
    n_after = comfy.n
    assert n_after == 4  # 2 runs × (warmup + timed)

    r2 = BenchmarkRunner(FakeComfy(), resume=True)
    # re-use suite with both done
    r2.run_phase(suite, "speed")
    assert r2.comfy.n == 0  # nothing re-executed


def test_resume_skips_failed_unless_retry(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    _patch_matrix_and_workflow(monkeypatch)

    # Fail timed run for first cell (call 2), second cell succeeds
    comfy = FakeComfy(fail_on={2})
    r = BenchmarkRunner(comfy)
    suite = r.init_suite()
    r.run_phase(suite, "speed")
    assert suite.phases["speed"].runs[0].status == "failed"
    assert suite.phases["speed"].runs[1].status == "done"

    # resume without retry: skip failed and done
    r2 = BenchmarkRunner(FakeComfy(), resume=True, retry_failed=False)
    n_before = r2.comfy.n
    r2.run_phase(suite, "speed")
    assert r2.comfy.n == n_before
    assert suite.phases["speed"].runs[0].status == "failed"

    # resume with retry_failed: re-run failed only
    r3 = BenchmarkRunner(FakeComfy(), resume=True, retry_failed=True)
    r3.run_phase(suite, "speed")
    assert suite.phases["speed"].runs[0].status == "done"
    assert suite.phases["speed"].runs[0].timed_s is not None
    assert r3.comfy.n == 2  # warmup + timed for the one failed cell


def test_failure_continues_to_next_run(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    _patch_matrix_and_workflow(monkeypatch)

    # Fail warmup of first run (call 1); second run both succeed
    comfy = FakeComfy(fail_on={1})
    r = BenchmarkRunner(comfy)
    suite = r.init_suite()
    r.run_phase(suite, "speed")
    assert suite.phases["speed"].runs[0].status == "failed"
    assert "warmup:" in (suite.phases["speed"].runs[0].error or "")
    assert suite.phases["speed"].runs[1].status == "done"
    assert suite.phases["speed"].status == "done"


def test_run_all_no_successful_speed_skips_later_phases(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    _patch_matrix_and_workflow(monkeypatch)

    comfy = FakeComfy(fail_on={1, 2, 3, 4})  # all prompts fail
    r = BenchmarkRunner(comfy)
    suite = r.run_all()
    assert suite.status == "completed"
    assert suite.base_config is None
    assert suite.phases["quality"].runs == []
    assert suite.phases["scale"].runs == []
