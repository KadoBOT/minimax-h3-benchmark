"""Run: one execution of one generation config."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from h3lab.domain.config import GenerationConfig

RunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]

LIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted"}
)

RunStage = Literal[
    "preparing",
    "clearing_cache",
    "sampling",
    "downloading",
    "deriving",
    "done",
]


class RunMetrics(BaseModel):
    """Measured facts. ``sec_per_it`` is the same unit ComfyUI's tqdm prints."""

    model_config = ConfigDict(frozen=True)

    wall_s: float | None = None
    sec_per_it: float | None = None
    steps: int | None = None
    sampler_cached: bool | None = None
    cache_cleared: bool | None = None

    @property
    def it_per_sec(self) -> float | None:
        if not self.sec_per_it:
            return None
        return 1.0 / self.sec_per_it


class Artifact(BaseModel):
    """The produced video plus everything derived from it."""

    model_config = ConfigDict(frozen=True)

    video_path: str | None = None
    poster_path: str | None = None
    strip_path: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frame_count: int | None = None
    size_bytes: int | None = None

    @property
    def has_video(self) -> bool:
        return bool(self.video_path)

    @property
    def resolution(self) -> str | None:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return None


class Run(BaseModel):
    """A run's config snapshot is a value: it is never edited after creation."""

    model_config = ConfigDict(frozen=True)

    id: str
    seq: int
    label: str
    status: RunStatus
    config: GenerationConfig
    config_hash: str
    recipe_hash: str

    metrics: RunMetrics = Field(default_factory=RunMetrics)
    artifact: Artifact = Field(default_factory=Artifact)

    prompt_id: str | None = None
    error: str | None = None
    favourite: bool = False
    archived: bool = False
    notes: str = ""
    tags: tuple[str, ...] = ()

    created_at: str
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class RunProgress(BaseModel):
    """Transient in-flight detail. Lives in memory and on the event stream only."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    stage: RunStage
    detail: str | None = None
    node: str | None = None
    node_label: str | None = None
    step: int | None = None
    step_total: int | None = None
    sec_per_it: float | None = None
    elapsed_s: float | None = None

    @property
    def fraction(self) -> float | None:
        if not self.step_total:
            return None
        return min(1.0, max(0.0, (self.step or 0) / self.step_total))
