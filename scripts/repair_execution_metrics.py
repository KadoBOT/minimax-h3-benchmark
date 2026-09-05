#!/usr/bin/env python3
"""Repair stored sampler metrics from each run's queued sigma schedule."""

from __future__ import annotations

import argparse
import json

from h3lab.comfy.client import ComfyClient
from h3lab.comfy.progress import primary_sampler_nodes, primary_schedule_steps
from h3lab.domain.run import RunMetrics
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunFilter, RunRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    runs = RunRepository(open_store(settings.db_path))
    client = ComfyClient(settings.comfy_url, run_timeout_s=10)
    repaired = 0
    try:
        succeeded = runs.all(RunFilter(status=("succeeded",), archived=None))
        for run in sorted(succeeded, key=lambda item: item.seq):
            if not run.prompt_id or run.metrics.steps is None:
                continue
            history = client.history(run.prompt_id)
            if not history or not isinstance(history.get("prompt"), list):
                continue
            prompt = history["prompt"][2]
            scheduled = primary_schedule_steps(prompt, primary_sampler_nodes(prompt))
            observed = run.metrics.steps
            if scheduled is None or scheduled == observed:
                continue
            sec_per_it = run.metrics.sec_per_it
            if sec_per_it is not None and scheduled > 0:
                sec_per_it *= observed / scheduled
            record = {
                "run": run.seq,
                "configured_steps": run.config.effective_steps,
                "stored_steps": observed,
                "scheduled_steps": scheduled,
                "stored_sec_per_it": run.metrics.sec_per_it,
                "scheduled_sec_per_it": sec_per_it,
            }
            print(json.dumps(record, sort_keys=True))
            if args.apply:
                runs.update_metrics(
                    run.id,
                    RunMetrics(
                        wall_s=run.metrics.wall_s,
                        sec_per_it=sec_per_it,
                        steps=scheduled,
                        sampler_cached=run.metrics.sampler_cached,
                        cache_cleared=run.metrics.cache_cleared,
                    ),
                )
            repaired += 1
    finally:
        client.close()

    action = "EXECUTION_METRICS_REPAIRED" if args.apply else "EXECUTION_METRICS_WOULD_REPAIR"
    print(f"{action} count={repaired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
