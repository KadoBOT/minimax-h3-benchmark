from __future__ import annotations

from copy import deepcopy

from bench.constants import FIXED_SEED
from bench.models import Run, RunConfig

CACHES = ("none", "spectrum", "easy", "h3")
QUANTS = ("nvfp4", "int8")
SOLS = (True, False)


def _rid(phase: str, idx: int, label: str) -> str:
    safe = label.replace(" ", "_").replace("/", "-")
    return f"{phase}_{idx:03d}_{safe}"


def build_speed_runs() -> list[Run]:
    runs: list[Run] = []
    idx = 1
    for cache in CACHES:
        for quant in QUANTS:
            for sol in SOLS:
                label = f"{cache}_{quant}_sol{'on' if sol else 'off'}"
                runs.append(
                    Run(
                        id=_rid("speed", idx, label),
                        phase="speed",
                        config=RunConfig(
                            cache=cache,  # type: ignore[arg-type]
                            quant=quant,  # type: ignore[arg-type]
                            sol_attn=sol,
                            seed=FIXED_SEED,
                        ),
                    )
                )
                idx += 1

    variants = [
        ("easy_aggressive", "easy", None, {"reuse_threshold": 0.35, "start_percent": 0.2, "end_percent": 0.9}),
        ("easy_conservative", "easy", None, {"reuse_threshold": 0.1, "start_percent": 0.3, "end_percent": 0.8}),
        ("h3_aggressive", "h3", None, {"reuse_threshold": 0.1, "max_steps": 3}),
        ("h3_conservative", "h3", None, {"reuse_threshold": 0.03, "max_steps": 1}),
        ("spectrum_aggressive", "spectrum", None, {"warmup_steps": 3, "blend_weight": 0.7}),
        ("spectrum_conservative", "spectrum", None, {"warmup_steps": 8, "blend_weight": 0.3}),
        ("sol_aggressive", "easy", "sol_aggressive", {"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95}),
        ("sol_conservative", "easy", "sol_conservative", {"tau": 1.0, "start_percent": 0.3, "end_percent": 0.85}),
    ]
    for name, cache, sol_var, widgets in variants:
        runs.append(
            Run(
                id=_rid("speed", idx, name),
                phase="speed",
                config=RunConfig(
                    cache=cache,  # type: ignore[arg-type]
                    cache_variant=name if sol_var is None else None,
                    quant="nvfp4",
                    sol_attn=True,
                    sol_variant=sol_var,
                    widgets=widgets,
                    seed=FIXED_SEED,
                ),
            )
        )
        idx += 1
    return runs


def build_quality_runs(base: RunConfig) -> list[Run]:
    runs: list[Run] = []
    idx = 1

    def add(label: str, **overrides):
        nonlocal idx
        cfg = deepcopy(base)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        runs.append(Run(id=_rid("quality", idx, label), phase="quality", config=cfg))
        idx += 1

    for sched in ("simple", "beta"):
        add(f"sched_{sched}", scheduler=sched)
    for samp in ("euler", "er_sde", "res_multistep", "res_multistep_cfg_pp"):
        add(f"samp_{samp}", sampler=samp)
    for steps in (16, 17, 18, 19, 20):
        add(f"steps_{steps}", steps=steps)
    return runs


def build_scale_runs(base: RunConfig) -> list[Run]:
    runs: list[Run] = []
    idx = 1
    # Phase 3 keeps Phase-1 quality defaults
    for mp in (0.4, 0.5, 0.6, 0.7, 0.8):
        for dur in (4.0, 5.0, 6.0, 8.0, 10.0):
            cfg = deepcopy(base)
            cfg.mp = mp
            cfg.duration_s = dur
            cfg.scheduler = "simple"
            cfg.sampler = "res_multistep"
            cfg.steps = 20
            runs.append(
                Run(
                    id=_rid("scale", idx, f"mp{mp}_d{dur:g}"),
                    phase="scale",
                    config=cfg,
                )
            )
            idx += 1
    return runs


def pick_fastest(runs: list[Run]) -> RunConfig | None:
    done = [r for r in runs if r.status == "done" and r.timed_s is not None]
    if not done:
        return None
    best = min(done, key=lambda r: (r.timed_s, r.id))
    return deepcopy(best.config)
