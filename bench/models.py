from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

PhaseName = Literal["manual", "speed", "quality", "scale"]
RunStatus = Literal["queued", "warmup", "timing", "done", "failed", "aborted"]
SuiteStatus = Literal["idle", "running", "completed", "aborted"]
ModelPath = Literal["gguf", "safetensor"]
CacheName = Literal["none", "spectrum", "easy", "h3"]
QuantName = Literal["nvfp4", "int8"]
PresetName = Literal["conservative", "moderate", "aggressive", "custom"]


@dataclass
class RunConfig:
    model_path: ModelPath = "safetensor"
    quant: QuantName = "nvfp4"
    # Basename under Comfy diffusion_models (MiniMax H3); empty → legacy quant defaults
    diffusion_model: str = ""
    # Basename under ComfyUI input/ for LoadImage first frame (FL2V)
    first_frame: str = ""
    turbo: bool = False
    rife: bool = False
    upscaler: bool = False
    clean_vram: bool = False
    cache_enabled: bool = True
    cache: CacheName = "spectrum"
    cache_preset: PresetName = "moderate"
    sol_attn: bool = True
    sol_preset: PresetName = "moderate"
    widgets: dict[str, Any] = field(default_factory=dict)
    scheduler: str = "beta57"
    sampler: str = "euler"
    steps: int = 20
    mp: float = 0.5
    duration_s: float = 5.0
    seed: int = 42
    # Legacy optional fields still accepted on from_dict
    cache_variant: str | None = None
    sol_variant: str | None = None

    def __post_init__(self) -> None:
        # cache="none" means caching disabled (ctor and from_dict)
        if self.cache == "none":
            self.cache_enabled = False
        # When a concrete file is set, keep model_path/quant aligned with the loader
        if self.diffusion_model and str(self.diffusion_model).strip():
            from bench.diffusion_models import infer_loader

            path, quant = infer_loader(str(self.diffusion_model).strip())
            self.model_path = path
            self.quant = quant
        if not (self.first_frame and str(self.first_frame).strip()):
            from bench.constants import DEFAULT_FIRST_FRAME

            self.first_frame = DEFAULT_FIRST_FRAME
        else:
            # LoadImage expects a basename in ComfyUI/input (no path separators)
            self.first_frame = Path(str(self.first_frame).replace("\\", "/")).name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunConfig:
        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        # Defaults when missing from partial / legacy payloads
        data.setdefault("model_path", "safetensor")
        data.setdefault("seed", 42)
        return cls(**data)


@dataclass
class Run:
    id: str
    phase: PhaseName = "manual"
    status: RunStatus = "queued"
    config: RunConfig = field(default_factory=RunConfig)
    warmup_s: float | None = None
    timed_s: float | None = None
    # Sampler rate during the *timed* run (wall while sampler node ran / steps).
    sec_per_it: float | None = None
    # True if Comfy reported the sampler node as execution-cached on the timed pass.
    sampler_cached: bool | None = None
    # True if we cleared Comfy's graph execution cache before the timed pass.
    graph_cache_cleared: bool | None = None
    video_path: str | None = None
    prompt_id: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Run:
        cfg = d.get("config") or {}
        if isinstance(cfg, dict):
            cfg = RunConfig.from_dict(cfg)
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        known["config"] = cfg
        known.setdefault("id", d.get("id"))
        known.setdefault("phase", d.get("phase", "manual"))
        return cls(**{k: v for k, v in known.items() if k in cls.__dataclass_fields__})


@dataclass
class PhaseState:
    status: str = "pending"
    runs: list[Run] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "runs": [r.to_dict() for r in self.runs]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PhaseState:
        runs = [Run.from_dict(x) for x in d.get("runs") or []]
        return cls(status=d.get("status", "pending"), runs=runs)


@dataclass
class Suite:
    suite_id: str
    status: SuiteStatus = "idle"
    schema_version: int = 2
    comfy_url: str = "http://127.0.0.1:8188"
    started_at: str | None = None
    updated_at: str | None = None
    baseline: dict[str, Any] = field(default_factory=dict)
    base_config: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    runs: list[Run] = field(default_factory=list)
    phases: dict[str, PhaseState] = field(default_factory=dict)  # legacy only

    def all_runs(self) -> list[Run]:
        if self.runs:
            return list(self.runs)
        out: list[Run] = []
        for ph in self.phases.values():
            out.extend(ph.runs)
        return out

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "suite_id": self.suite_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "comfy_url": self.comfy_url,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "baseline": self.baseline,
            "base_config": self.base_config,
            "current": self.current,
            "runs": [r.to_dict() for r in self.runs],
        }
        if self.phases:
            d["phases"] = {k: v.to_dict() for k, v in self.phases.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Suite:
        phases_raw = d.get("phases") or {}
        phases = {k: PhaseState.from_dict(v) for k, v in phases_raw.items()}
        runs = [Run.from_dict(x) for x in d.get("runs") or []]
        return cls(
            suite_id=d["suite_id"],
            status=d.get("status", "idle"),
            schema_version=int(d.get("schema_version", 2)),
            comfy_url=d.get("comfy_url", "http://127.0.0.1:8188"),
            started_at=d.get("started_at"),
            updated_at=d.get("updated_at"),
            baseline=d.get("baseline") or {},
            base_config=d.get("base_config"),
            current=d.get("current"),
            runs=runs,
            phases=phases,
        )


# Written into suite.baseline so the UI/results file document metric meaning.
BENCHMARK_PROTOCOL: dict[str, Any] = {
    "warmup_s": (
        "Full pipeline wall-clock for the first gen of this cell. Discarded for ranking. "
        "May include model load on early cells; later cells keep weights in VRAM (no VRAM clean)."
    ),
    "timed_s": (
        "Full pipeline wall-clock for the second gen of this cell (same seed/settings). "
        "Ranked metric for end-to-end time. Includes VAE decode + video encode after sampling."
    ),
    "sec_per_it": (
        "Sampler-only rate during the timed gen: wall time while the sampler node ran ÷ steps. "
        "Best signal for EasyCache / Spectrum / H3 / quant / sol-attn speedups."
    ),
    "graph_execution_cache": (
        "ComfyUI node-output cache is cleared once per cell: after warmup, before timed. "
        "Not cleared between matrix cells. This is NOT Easy/Spectrum/H3 — those still apply "
        "on every real sampling pass."
    ),
    "vram_clean": False,
    "identical_graphs": (
        "Warmup and timed use the same sampling graph (same seed, cache, quant, sol-attn). "
        "Only VHS filename_prefix differs so outputs do not overwrite each other."
    ),
}


def migrate_suite_dict(d: dict[str, Any]) -> Suite:
    """Normalize v1 phases-only files into schema_version 2 flat runs.

    Flat ``runs`` is authoritative. Short-circuit only when schema_version==2
    and runs is already the product source of truth (non-empty, or present with
    empty/missing phases). Schema 2 with runs=[] and non-empty phases still
    flattens; phases are cleared after so to_dict does not persist dual copies.
    """
    d = dict(d)
    runs_val = d.get("runs")
    phases_raw = d.get("phases") or {}
    has_phases = bool(phases_raw)

    # Authoritative flat runs: schema 2 with non-empty runs, or runs present and no phases.
    if d.get("schema_version") == 2 and runs_val is not None:
        if (isinstance(runs_val, list) and len(runs_val) > 0) or not has_phases:
            d["phases"] = {}
            return Suite.from_dict(d)

    runs_raw: list = list(runs_val or [])
    if not runs_raw:
        for phase_name, phase in phases_raw.items():
            for r in (phase or {}).get("runs") or []:
                rr = dict(r)
                rr.setdefault("phase", phase_name)
                runs_raw.append(rr)
    d["runs"] = runs_raw
    d["schema_version"] = 2
    d["phases"] = {}  # clear so to_dict does not persist stale dual copies
    return Suite.from_dict(d)


def empty_suite(suite_id: str, comfy_url: str) -> Suite:
    from bench.constants import DEFAULT_SAMPLER, DEFAULT_SCHEDULER, FIXED_SEED

    return Suite(
        suite_id=suite_id,
        schema_version=2,
        comfy_url=comfy_url,
        baseline={
            "seed": FIXED_SEED,
            "mp": 0.5,
            "duration_s": 5,
            "scheduler": DEFAULT_SCHEDULER,
            "sampler": DEFAULT_SAMPLER,
            "steps": 20,
            "protocol": BENCHMARK_PROTOCOL,
        },
        runs=[],
        phases={},
    )
