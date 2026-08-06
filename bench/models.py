from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PhaseName = Literal["speed", "quality", "scale"]
RunStatus = Literal["queued", "warmup", "timing", "done", "failed"]
SuiteStatus = Literal["idle", "running", "completed", "aborted"]
CacheName = Literal["none", "spectrum", "easy", "h3"]
QuantName = Literal["nvfp4", "int8"]


@dataclass
class RunConfig:
    cache: CacheName = "easy"
    cache_variant: str | None = None
    quant: QuantName = "nvfp4"
    sol_attn: bool = True
    sol_variant: str | None = None
    widgets: dict[str, Any] = field(default_factory=dict)
    scheduler: str = "simple"
    sampler: str = "res_multistep"
    steps: int = 20
    mp: float = 0.5
    duration_s: float = 5.0
    seed: int = 914265959575104

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Run:
    id: str
    phase: PhaseName
    status: RunStatus = "queued"
    config: RunConfig = field(default_factory=RunConfig)
    warmup_s: float | None = None
    timed_s: float | None = None
    sec_per_it: float | None = None  # ComfyUI sampler progress average (s/it)
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
        return cls(
            id=d["id"],
            phase=d["phase"],
            status=d.get("status", "queued"),
            config=cfg,
            warmup_s=d.get("warmup_s"),
            timed_s=d.get("timed_s"),
            sec_per_it=d.get("sec_per_it"),
            video_path=d.get("video_path"),
            prompt_id=d.get("prompt_id"),
            error=d.get("error"),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


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
    comfy_url: str = "http://127.0.0.1:8188"
    started_at: str | None = None
    updated_at: str | None = None
    baseline: dict[str, Any] = field(default_factory=dict)
    base_config: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    phases: dict[str, PhaseState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "status": self.status,
            "comfy_url": self.comfy_url,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "baseline": self.baseline,
            "base_config": self.base_config,
            "current": self.current,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Suite:
        phases_raw = d.get("phases") or {}
        phases = {k: PhaseState.from_dict(v) for k, v in phases_raw.items()}
        return cls(
            suite_id=d["suite_id"],
            status=d.get("status", "idle"),
            comfy_url=d.get("comfy_url", "http://127.0.0.1:8188"),
            started_at=d.get("started_at"),
            updated_at=d.get("updated_at"),
            baseline=d.get("baseline") or {},
            base_config=d.get("base_config"),
            current=d.get("current"),
            phases=phases,
        )


def empty_suite(suite_id: str, comfy_url: str) -> Suite:
    from bench.constants import FIXED_SEED

    return Suite(
        suite_id=suite_id,
        comfy_url=comfy_url,
        baseline={
            "seed": FIXED_SEED,
            "mp": 0.5,
            "duration_s": 5,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "steps": 20,
        },
        phases={
            "speed": PhaseState(),
            "quality": PhaseState(),
            "scale": PhaseState(),
        },
    )
