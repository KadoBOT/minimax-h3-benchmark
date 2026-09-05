#!/usr/bin/env python3
"""Trace a stored benchmark value through its historical ComfyUI prompt."""

from __future__ import annotations

import argparse
import json

from h3lab.comfy.client import ComfyClient
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunFilter, RunRepository


def _main_sampler(prompt: dict) -> tuple[str, dict]:
    studios = {
        str(node_id)
        for node_id, node in prompt.items()
        if node.get("class_type") == "MiniMaxH3Studio"
    }
    samplers = [
        (str(node_id), node)
        for node_id, node in prompt.items()
        if node.get("class_type") in {"SamplerCustomAdvanced", "KSampler", "KSamplerAdvanced"}
    ]
    for node_id, node in samplers:
        latent = node.get("inputs", {}).get("latent_image")
        if isinstance(latent, list) and str(latent[0]) in studios:
            return node_id, node
    if len(samplers) == 1:
        return samplers[0]
    raise RuntimeError("historical prompt has no identifiable primary sampler")


def _schedule_path(prompt: dict, sampler: dict) -> list[tuple[str, dict]]:
    current = sampler.get("inputs", {}).get("sigmas")
    path: list[tuple[str, dict]] = []
    seen: set[str] = set()
    while isinstance(current, list) and len(current) == 2:
        node_id = str(current[0])
        if node_id in seen or node_id not in prompt:
            break
        seen.add(node_id)
        node = prompt[node_id]
        path.append((node_id, node))
        current = node.get("inputs", {}).get("sigmas")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-mismatch", choices=("steps",), required=True)
    args = parser.parse_args()

    settings = Settings.from_env()
    runs = RunRepository(open_store(settings.db_path))
    recent = runs.list(
        RunFilter(status=("succeeded",), archived=None),
        sort="recent",
        limit=50,
    ).items
    client = ComfyClient(settings.comfy_url, run_timeout_s=10)
    reproduced = 0
    try:
        for run in recent:
            if run.metrics.steps is None or run.metrics.steps == run.config.effective_steps:
                continue
            if not run.prompt_id:
                continue
            history = client.history(run.prompt_id)
            if not history or not isinstance(history.get("prompt"), list):
                continue
            prompt = history["prompt"][2]
            studios = [
                node for node in prompt.values() if node.get("class_type") == "MiniMaxH3Studio"
            ]
            if len(studios) != 1:
                raise RuntimeError(f"run #{run.seq} has {len(studios)} Studio nodes")
            _sampler_id, sampler = _main_sampler(prompt)
            schedule = _schedule_path(prompt, sampler)
            split = next(
                (node for _node_id, node in schedule if node.get("class_type") == "SplitSigmas"),
                None,
            )
            if split is None:
                continue
            record = {
                "run": run.seq,
                "configured_steps": run.config.effective_steps,
                "studio_steps": studios[0].get("inputs", {}).get("steps"),
                "recorded_execution_steps": run.metrics.steps,
                "schedule_path": [node.get("class_type") for _node_id, node in schedule],
                "split_step": (split or {}).get("inputs", {}).get("step"),
            }
            print(json.dumps(record, sort_keys=True))
            if record["studio_steps"] != record["configured_steps"]:
                raise RuntimeError(f"run #{run.seq} changed steps before Studio")
            if record["split_step"] != 4:
                raise RuntimeError(f"run #{run.seq} does not reproduce the hard-coded sigma split")
            reproduced += 1
            if reproduced == 2:
                break
    finally:
        client.close()

    if reproduced < 2:
        raise SystemExit("expected at least two historical hard-coded sigma split mismatches")
    if args.expect_mismatch == "steps":
        print("RECENT_STEPS_MISMATCH_REPRODUCED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
