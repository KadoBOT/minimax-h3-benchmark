from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.constants import (
    BENCHMARK_JSON,
    RESULTS_DIR,
    RUNS_DIR,
    SUITE_LOG,
    VIDEOS_DIR,
)
from bench.models import Suite

# Re-bind for monkeypatch.setattr(store, "RESULTS_DIR", ...) in tests
# (names already live in this module via the import above)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def clear_results() -> dict[str, int]:
    """Delete suite JSON, videos, run metas, and suite log. Recreate empty dirs.

    Returns counts of removed files for logging.
    """
    removed = {"files": 0, "dirs_cleared": 0}

    def _rm_file(path: Path) -> None:
        nonlocal removed
        if path.is_file():
            path.unlink()
            removed["files"] += 1

    def _rm_tree_contents(path: Path) -> None:
        nonlocal removed
        if not path.is_dir():
            return
        for child in path.iterdir():
            if child.is_file():
                child.unlink()
                removed["files"] += 1
            elif child.is_dir():
                # Nested dirs under videos/runs (rare)
                for sub in child.rglob("*"):
                    if sub.is_file():
                        sub.unlink()
                        removed["files"] += 1
                # remove empty subdirs bottom-up
                for sub in sorted(child.rglob("*"), reverse=True):
                    if sub.is_dir():
                        try:
                            sub.rmdir()
                        except OSError:
                            pass
                try:
                    child.rmdir()
                except OSError:
                    pass
        removed["dirs_cleared"] += 1

    _rm_file(BENCHMARK_JSON)
    _rm_file(SUITE_LOG)
    _rm_tree_contents(VIDEOS_DIR)
    _rm_tree_contents(RUNS_DIR)
    ensure_dirs()
    return removed


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_suite(suite: Suite) -> None:
    ensure_dirs()
    suite.updated_at = _utc_now()
    atomic_write_json(BENCHMARK_JSON, suite.to_dict())


def load_suite(path: Path | None = None) -> Suite:
    p = path or BENCHMARK_JSON
    data = json.loads(p.read_text(encoding="utf-8"))
    from bench.models import migrate_suite_dict

    return migrate_suite_dict(data)


def try_load_suite() -> Suite | None:
    if not BENCHMARK_JSON.exists():
        return None
    return load_suite()


def patch_run(run_id: str, **fields: Any) -> Suite:
    """Patch a run by id in suite.runs (after migration) or legacy phases."""
    suite = load_suite()
    # Ensure flat list is the source of truth after load/migrate
    if not suite.runs:
        suite.runs = suite.all_runs()
    found = False
    for r in suite.all_runs():
        if r.id == run_id:
            for k, v in fields.items():
                if k == "config" and isinstance(v, dict):
                    from bench.models import RunConfig

                    setattr(r, k, RunConfig.from_dict(v))
                elif k == "rating":
                    if v is None or v == "" or v == "null":
                        setattr(r, k, None)
                    else:
                        iv = int(v)
                        if not 1 <= iv <= 10:
                            raise ValueError("rating must be 1–10 or null")
                        setattr(r, k, iv)
                else:
                    setattr(r, k, v)
            found = True
            break
    if not found:
        raise KeyError(f"run {run_id} not found")
    save_suite(suite)
    return suite


def set_run_rating(run_id: str, rating: int | None, suite: Suite | None = None) -> Suite:
    """Set quality rating (1–10) or clear with None. Optionally patch live suite."""
    if rating is not None:
        rating = int(rating)
        if not 1 <= rating <= 10:
            raise ValueError("rating must be 1–10 or null")
    target = suite
    if target is None:
        return patch_run(run_id, rating=rating)
    if not target.runs:
        target.runs = target.all_runs()
    for r in target.all_runs():
        if r.id == run_id:
            r.rating = rating
            save_suite(target)
            return target
    raise KeyError(f"run {run_id} not found")


def set_run_excluded(
    run_id: str, excluded: bool, suite: Suite | None = None
) -> Suite:
    """Mark a run excluded from compare/scores/heatmap (still in list)."""
    excluded = bool(excluded)
    target = suite
    if target is None:
        return patch_run(run_id, excluded=excluded)
    if not target.runs:
        target.runs = target.all_runs()
    for r in target.all_runs():
        if r.id == run_id:
            r.excluded = excluded
            save_suite(target)
            return target
    raise KeyError(f"run {run_id} not found")


def video_dest(run_id: str, ext: str = ".mp4") -> Path:
    ensure_dirs()
    return VIDEOS_DIR / f"{run_id}{ext}"
