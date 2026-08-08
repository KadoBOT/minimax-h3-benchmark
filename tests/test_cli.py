"""The command line, invoked as a real process.

`main()` is also called in-process for the cases that need a temp directory injected, but
every command is additionally proved by running `python -m h3lab` so the packaging, the
argument parsing, and the exit codes are all exercised the way a user meets them.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from h3lab import cli
from h3lab.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_process(*args: str, expect: int | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "h3lab", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if expect is not None:
        assert result.returncode == expect, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result


def run_inline(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(list(args), out=out)
    return code, out.getvalue()


def as_flags(settings: Settings) -> list[str]:
    return [
        "--data-dir", str(settings.data_dir),
        "--models-dir", str(settings.models_dir),
        "--comfy-input-dir", str(settings.comfy_input_dir),
        "--web-dist", str(settings.web_dist),
        "--comfy-url", settings.comfy_url,
    ]


def check_row(text: str, name: str) -> str:
    """The `check` row for one subsystem, matched on the name column.

    Temp directories in the detail column carry the test's own name, so a plain substring
    search finds the wrong row (a path holding "comfyui", say). Rows read
    `<mark>  <name padded>  <detail>`, so anchor on the mark and the name.
    """
    rows = [row for row in text.splitlines() if row[4:].strip().startswith(name)]
    assert len(rows) == 1, f"no single row for {name!r} in:\n{text}"
    return rows[0]


# --- help and usage --------------------------------------------------------


def test_help_lists_every_command():
    result = run_process("--help", expect=0)
    for command in ("serve", "check", "import-legacy", "routes"):
        assert command in result.stdout


def test_an_unknown_command_is_a_usage_error():
    result = run_process("teleport")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


# --- routes ----------------------------------------------------------------


def test_routes_lists_the_api_surface():
    result = run_process("routes", expect=0)
    pairs = {tuple(line.split()) for line in result.stdout.splitlines() if line.strip()}
    assert ("GET", "/api/runs") in pairs
    assert ("POST", "/api/runs") in pairs
    assert ("GET", "/api/leaderboard") in pairs
    assert ("GET", "/api/events") in pairs
    assert ("PUT", "/api/runs/{run_id}/rating") in pairs
    assert not any(method == "HEAD" for method, _path in pairs)


def test_routes_does_not_touch_the_database(settings: Settings):
    code, text = run_inline("--data-dir", str(settings.data_dir), "routes")
    assert code == 0
    assert "/api/runs" in text
    assert not settings.db_path.exists(), "listing routes must not open a store"


# --- check -----------------------------------------------------------------


def test_check_reports_each_subsystem_in_plain_text(settings: Settings):
    code, text = run_inline(*as_flags(settings.with_overrides(comfy_url="http://127.0.0.1:9")), "check")
    assert code == cli.EXIT_PROBLEM  # ComfyUI is not running on port 9
    for label in ("workflow t2v", "workflow flf2v", "workflow r2v", "comfyui", "models", "front end"):
        assert label in text
    assert "checks passed" in text


def test_check_builds_each_workflow_and_finds_no_dangling_links(settings: Settings):
    _code, text = run_inline(*as_flags(settings), "check")
    for mode in ("t2v", "flf2v", "r2v"):
        line = check_row(text, f"workflow {mode}")
        assert line.startswith("ok  "), line
        assert "nodes" in line


def test_check_says_comfyui_is_unreachable_rather_than_crashing(settings: Settings):
    _code, text = run_inline(*as_flags(settings.with_overrides(comfy_url="http://127.0.0.1:9")), "check")
    comfy = check_row(text, "comfyui")
    assert comfy.startswith("FAIL")
    assert "127.0.0.1:9" in comfy


def test_check_emits_machine_readable_json(settings: Settings):
    code, text = run_inline(*as_flags(settings), "check", "--json")
    payload = json.loads(text)
    assert payload["ok"] is False  # no ComfyUI in the test environment
    names = {item["check"] for item in payload["checks"]}
    assert {"comfyui", "models", "ffmpeg", "front end"} <= names
    assert all({"check", "ok", "detail"} <= set(item) for item in payload["checks"])


def test_check_notices_a_built_front_end(settings: Settings):
    settings.web_dist.mkdir(parents=True, exist_ok=True)
    (settings.web_dist / "index.html").write_text("<!doctype html>")
    _code, text = run_inline(*as_flags(settings), "check")
    assert check_row(text, "front end").startswith("ok  ")


def test_check_tells_you_the_front_end_is_not_built(settings: Settings):
    _code, text = run_inline(*as_flags(settings), "check")
    assert "npm run build" in check_row(text, "front end")


def test_check_runs_as_a_real_process_and_exits_nonzero_without_comfyui(tmp_path: Path):
    result = run_process(
        "--data-dir", str(tmp_path / "data"),
        "--comfy-url", "http://127.0.0.1:9",
        "check",
    )
    assert result.returncode == cli.EXIT_PROBLEM
    assert "comfyui" in result.stdout
    assert "FAIL" in result.stdout


def test_check_creates_the_data_directory_it_reports(settings: Settings, tmp_path: Path):
    fresh = tmp_path / "brand-new"
    code, text = run_inline("--data-dir", str(fresh), "--comfy-url", "http://127.0.0.1:9", "check")
    assert code == cli.EXIT_PROBLEM
    assert str(fresh) in text
    assert (fresh / "videos").is_dir()


# --- legacy import ---------------------------------------------------------


def test_import_legacy_reports_nothing_to_do_on_an_empty_lab(settings: Settings):
    code, text = run_inline(*as_flags(settings), "import-legacy")
    assert code == 0
    assert "imported 0 run(s)" in text


def test_import_legacy_moves_the_old_lab_in(settings: Settings, base_config):
    _seed_legacy_db(settings, base_config)
    code, text = run_inline(*as_flags(settings), "import-legacy")
    assert code == 0
    assert "imported 1 run(s), 1 rating(s)" in text

    # A second pass must not duplicate anything.
    _code, again = run_inline(*as_flags(settings), "import-legacy")
    assert "imported 0 run(s)" in again
    assert "1 already present" in again


LEGACY_SCHEMA = """
CREATE TABLE runs (
    id TEXT PRIMARY KEY, phase TEXT, status TEXT, config_json TEXT,
    warmup_s REAL, timed_s REAL, sec_per_it REAL, sampler_cached INTEGER,
    graph_cache_cleared INTEGER, video_path TEXT, prompt_id TEXT, error TEXT,
    started_at TEXT, finished_at TEXT, rating INTEGER, excluded INTEGER,
    sort_order INTEGER
);
"""


def _seed_legacy_db(settings: Settings, base_config) -> None:
    import sqlite3

    settings.ensure_dirs()
    conn = sqlite3.connect(settings.legacy_db_path)
    try:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "run_001_from_the_old_lab",
                "manual",
                "done",
                json.dumps(base_config.model_dump(mode="json")),
                None, 190.0, 9.5, 0, 1,
                None, "pid-1", None, None, None,
                8, 0, 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --- serve -----------------------------------------------------------------


def test_serve_announces_the_address_before_binding(settings: Settings, monkeypatch):
    """Serve must print where to look before uvicorn takes over the terminal."""
    started: dict[str, object] = {}

    def fake_run(app, **kwargs):
        started["kwargs"] = kwargs
        started["app"] = app

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    code, text = run_inline(*as_flags(settings), "serve", "--port", "8899", "--no-worker")
    assert code == 0
    assert "http://127.0.0.1:8899" in text
    assert settings.comfy_url in text
    assert started["kwargs"]["port"] == 8899


def test_serve_warns_when_the_front_end_is_missing(settings: Settings, monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    _code, text = run_inline(*as_flags(settings), "serve", "--no-worker")
    assert "not built yet" in text


def test_a_bare_invocation_serves(settings: Settings, monkeypatch):
    import uvicorn

    seen: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: seen.update(k))
    code, text = run_inline(*as_flags(settings))
    assert code == 0
    assert seen["host"] == settings.host
    assert "H3 Lab on" in text


@pytest.mark.parametrize(("flags", "worker"), [(["--no-worker"], False), ([], True)])
def test_serve_starts_the_worker_unless_told_otherwise(
    settings: Settings, monkeypatch, flags: list[str], worker: bool
):
    import uvicorn

    from h3lab.engine import lab as lab_module

    seen: list[bool] = []
    real_lab = lab_module.Lab

    def spy(*args, **kwargs):
        made = real_lab(*args, **kwargs)
        # Recorded while serving; `serve` closes the lab on the way out, which stops the worker.
        seen.append(made.runner.running)
        return made

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(lab_module, "Lab", spy)
    run_inline(*as_flags(settings), "serve", *flags)
    assert seen == [worker]


@pytest.mark.parametrize("flag", ["--comfy-url", "--data-dir"])
def test_global_flags_are_accepted_before_the_subcommand(settings: Settings, flag: str):
    value = "http://127.0.0.1:9" if flag == "--comfy-url" else str(settings.data_dir)
    code, _text = run_inline(flag, value, "routes")
    assert code == 0
