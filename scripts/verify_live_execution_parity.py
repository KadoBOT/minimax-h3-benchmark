#!/usr/bin/env python3
"""Execute small live runs and prove configured sampler steps were observed."""

from __future__ import annotations

import argparse
import json
import time

from h3lab.comfy.catalog import list_models
from h3lab.comfy.client import ComfyClient
from h3lab.comfy.graph import load_workflow
from h3lab.comfy.progress import ProgressTracker
from h3lab.comfy.schema import Schemas
from h3lab.comfy.studio import prepare_prompt
from h3lab.domain.config import GenerationConfig
from h3lab.domain.run import RunMetrics
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunRepository


def _studio_steps(prompt: dict) -> int:
    studios = [
        node for node in prompt.values() if node.get("class_type") == "MiniMaxH3Studio"
    ]
    if len(studios) != 1:
        raise RuntimeError(f"prepared prompt has {len(studios)} Studio nodes")
    return int(studios[0]["inputs"]["steps"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", nargs="+", type=int, required=True)
    args = parser.parse_args()
    if len(args.steps) < 2:
        raise SystemExit("provide at least two step counts")

    settings = Settings.from_env()
    models = list_models(settings.diffusion_models_dir)
    if not models:
        raise SystemExit("no MiniMax H3 diffusion model is installed")
    workflow = load_workflow(settings.workflow_path("t2v"))
    client = ComfyClient(settings.comfy_url, run_timeout_s=settings.comfy_timeout_s)
    schemas = Schemas.from_client(client)
    runs = RunRepository(open_store(settings.db_path))
    observed: list[int] = []

    try:
        for index, steps in enumerate(args.steps):
            config = GenerationConfig(
                mode="t2v",
                diffusion_model=models[0],
                prompt="A locked-off test chart with one red cube on a neutral gray background.",
                scheduler="simple",
                sampler="euler",
                aspect_ratio="1:1 (Square)",
                steps=steps,
                seed=(time.time_ns() + index) % (2**63 - 1),
                mp=0.05,
                duration_s=0.5,
                cache_enabled=False,
                cache="none",
                sol_attn=False,
                clean_vram=False,
                widgets={
                    "attn": "off",
                    "derope": False,
                    "post_grade": False,
                    "upscale_ltx": False,
                },
            )
            run = runs.create(config, status="running")
            runs.set_tags(run.id, ("parity-verification",))
            try:
                prepared = prepare_prompt(
                    client,
                    workflow,
                    config,
                    schemas=schemas,
                    output_tag=run.id,
                )
                if _studio_steps(prepared.prompt) != steps:
                    raise RuntimeError("prepared Studio step count differs from the run config")
                if any(
                    node.get("class_type") == "SplitSigmas"
                    for node in prepared.prompt.values()
                ):
                    raise RuntimeError("prepared primary schedule still contains SplitSigmas")

                tracker = ProgressTracker.of(prepared.prompt)
                outcome = client.execute(prepared.prompt, tracker=tracker)
                runs.set_prompt_id(run.id, outcome.prompt_id)
                runs.update_metrics(
                    run.id,
                    RunMetrics(
                        wall_s=outcome.wall_s,
                        sec_per_it=outcome.sec_per_it,
                        steps=outcome.steps,
                        sampler_cached=False,
                        cache_cleared=False,
                    ),
                )
                if outcome.steps != steps:
                    raise RuntimeError(
                        f"configured {steps} steps but observed {outcome.steps!r}"
                    )
                runs.mark_succeeded(run.id)
                observed.append(steps)
                print(
                    json.dumps(
                        {
                            "run": runs.require(run.id).seq,
                            "prompt_id": outcome.prompt_id,
                            "configured_steps": steps,
                            "observed_steps": outcome.steps,
                            "wall_s": round(outcome.wall_s, 3),
                        },
                        sort_keys=True,
                    )
                )
            except Exception as exc:
                runs.mark_failed(run.id, str(exc))
                raise
    finally:
        client.close()

    if observed != args.steps:
        raise RuntimeError(f"observed {observed}, expected {args.steps}")
    print("LIVE_STEPS_PARITY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
