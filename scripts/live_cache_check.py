"""Run one short real generation per cache level, against a live ComfyUI on a real GPU.

The cache nodes validate their own widgets inside the node, during sampling. A graph that
patches cleanly and passes a dry run can still be refused there, so the only proof that a
preset level is runnable is a run that finishes. Kept deliberately small: 4 steps at the
lowest megapixel count, just enough to get past every node and produce a file.

    python scripts/live_cache_check.py                 # every family at every level
    python scripts/live_cache_check.py spectrum        # one family
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from h3lab.domain.config import GenerationConfig
from h3lab.engine.lab import Lab
from h3lab.settings import Settings

LEVELS = ("conservative", "moderate", "aggressive")
FAMILIES = ("spectrum", "easy", "h3")
POLL_S = 2.0
BUDGET_S = 900.0


def base(lab: Lab) -> GenerationConfig:
    """The cheapest text-to-video config the live catalog will accept."""
    catalog = lab.catalog()
    models = list(catalog.diffusion_models)
    if not models:
        raise SystemExit("no diffusion models found — is ComfyUI pointing at its model folder?")
    return GenerationConfig(
        mode="t2v",
        diffusion_model=models[0],
        prompt="a red cube rotating slowly on a white table",
        steps=4,
        mp=0.1,
        duration_s=1.0,
        seed=7,
        cache_enabled=True,
        sol_attn=False,
    )


def await_finish(lab: Lab, run_id: str) -> tuple[str, str]:
    deadline = time.monotonic() + BUDGET_S
    while time.monotonic() < deadline:
        run = lab.runs.get(run_id)
        if run.is_terminal:
            return run.status, (run.error or "")
        time.sleep(POLL_S)
    lab.cancel(run_id)
    return "timeout", f"still {lab.runs.get(run_id).status} after {BUDGET_S:.0f}s"


def main() -> int:
    families = sys.argv[1:] or list(FAMILIES)
    lab = Lab(Settings.from_env())
    try:
        template = base(lab)
        print(f"model: {template.diffusion_model}")
        print(f"{template.steps} steps at {template.mp} MP, {template.duration_s}s\n")
        failures: list[str] = []
        for family in families:
            for level in LEVELS:
                config = template.merged(cache=family, cache_preset=level)
                report = lab.dry_run(config)
                if report.problems:
                    print(f"{family:9} {level:13} DRY RUN {report.problems}")
                    failures.append(f"{family}/{level}: {report.problems}")
                    continue
                started = time.monotonic()
                run_id = lab.enqueue(config)[0].run.id
                status, error = await_finish(lab, run_id)
                elapsed = time.monotonic() - started
                run = lab.runs.get(run_id)
                rate = run.metrics.sec_per_it if run.metrics else None
                pace = f"{rate:.2f}s/it" if rate else "no rate"
                mark = "ok  " if status == "succeeded" else "FAIL"
                print(f"{family:9} {level:13} {mark} {elapsed:6.1f}s  {pace}  {error[:90]}")
                if status != "succeeded":
                    failures.append(f"{family}/{level}: {status} {error[:200]}")
        print()
        if failures:
            print(f"{len(failures)} failed:")
            for line in failures:
                print(f"  {line}")
            return 1
        print("every level ran")
        return 0
    finally:
        lab.close()


if __name__ == "__main__":
    raise SystemExit(main())
