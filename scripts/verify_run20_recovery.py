#!/usr/bin/env python3
"""Re-run failed run 20 without its incompatible Spectrum/ER-SDE pairing."""

from __future__ import annotations

import json
import time
import urllib.request

from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunRepository


API = "http://127.0.0.1:8787/api"
TAG = "run20-recovery"


def request(method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    query = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(query, timeout=30) as response:
        return json.load(response)


def main() -> int:
    runs = RunRepository(open_store(Settings.from_env().db_path))
    source = next((run for run in runs.all() if run.seq == 20), None)
    if source is None:
        raise RuntimeError("run 20 is unavailable")

    recovery = next(
        (run for run in sorted(runs.all(), key=lambda item: item.seq, reverse=True) if TAG in run.tags),
        None,
    )
    if recovery is None:
        view = request(
            "POST",
            f"/runs/{source.id}/rerun",
            {"overrides": {"cache": "none", "cache_enabled": False}},
        )
        run = view["run"]
        request("PATCH", f"/runs/{run['id']}", {"tags": [*run["tags"], TAG]})
        recovery_id = run["id"]
        print(f"queued corrected run #{run['seq']}", flush=True)
    else:
        recovery_id = recovery.id
        print(f"resuming verification of run #{recovery.seq}", flush=True)

    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        run = request("GET", f"/runs/{recovery_id}")["run"]
        if run["status"] == "succeeded":
            config = run["config"]
            widgets = config.get("widgets") or {}
            if config["cache"] != "none" or config["cache_enabled"]:
                raise RuntimeError("recovery run did not disable Spectrum")
            if not widgets.get("er_sde") or not widgets.get("derope"):
                raise RuntimeError("recovery run did not preserve ER-SDE and de-rope")
            if run["metrics"]["steps"] != config["steps"]:
                raise RuntimeError("recovery run's configured and observed steps differ")
            if not run["artifact"]["video_path"]:
                raise RuntimeError("recovery run produced no video")
            print(
                f"RUN20_RECOVERY_OK run={run['seq']} steps={run['metrics']['steps']}",
                flush=True,
            )
            return 0
        if run["status"] in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(
                f"recovery run #{run['seq']} ended as {run['status']}: {run['error']}"
            )
        time.sleep(5)

    raise RuntimeError("timed out waiting for the run 20 recovery")


if __name__ == "__main__":
    raise SystemExit(main())
