from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.constants import BENCHMARK_JSON, RESULTS_DIR, RUNS_DIR, VIDEOS_DIR
from bench.models import Suite

# Re-bind for monkeypatch.setattr(store, "RESULTS_DIR", ...) in tests
# (names already live in this module via the import above)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


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
                else:
                    setattr(r, k, v)
            found = True
            break
    if not found:
        raise KeyError(f"run {run_id} not found")
    save_suite(suite)
    return suite


def video_dest(run_id: str, ext: str = ".mp4") -> Path:
    ensure_dirs()
    return VIDEOS_DIR / f"{run_id}{ext}"
