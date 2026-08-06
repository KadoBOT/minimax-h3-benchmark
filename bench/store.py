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
    return Suite.from_dict(data)


def try_load_suite() -> Suite | None:
    if not BENCHMARK_JSON.exists():
        return None
    return load_suite()


def patch_run(phase: str, run_id: str, **fields: Any) -> Suite:
    suite = load_suite()
    runs = suite.phases[phase].runs
    for r in runs:
        if r.id == run_id:
            for k, v in fields.items():
                if k == "config" and isinstance(v, dict):
                    from bench.models import RunConfig

                    setattr(r, k, RunConfig.from_dict(v))
                else:
                    setattr(r, k, v)
            break
    else:
        raise KeyError(f"run {run_id} not found in phase {phase}")
    save_suite(suite)
    return suite


def video_dest(run_id: str, ext: str = ".mp4") -> Path:
    ensure_dirs()
    return VIDEOS_DIR / f"{run_id}{ext}"
