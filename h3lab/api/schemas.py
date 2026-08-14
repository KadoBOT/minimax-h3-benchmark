"""Request bodies. Responses reuse the domain models, which are already Pydantic."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from h3lab.domain.config import GenerationConfig
from h3lab.domain.rating import CRITERIA, STARS_MAX, STARS_MIN
from h3lab.domain.run import RunStatus
from h3lab.domain.scoring import ScoreWeights
from h3lab.domain.sweeps import SeedStrategy, SweepAxis, SweepSpec
from h3lab.storage.runs import RunFilter, SortKey


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: GenerationConfig
    count: Annotated[int, Field(ge=1, le=64)] = 1


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, Any] = Field(default_factory=dict)


class DryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: GenerationConfig


class PatchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    favourite: bool | None = None
    archived: bool | None = None
    notes: str | None = None
    label: str | None = None
    tags: list[str] | None = None


class RateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stars: Annotated[int, Field(ge=STARS_MIN, le=STARS_MAX)]
    criteria: dict[str, Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict)

    @property
    def known_criteria(self) -> dict[str, int]:
        return {key: value for key, value in self.criteria.items() if key in CRITERIA}


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_a: str
    run_b: str
    winner: str | None = None
    axis: str | None = None


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None


class PresetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    run_id: str | None = None
    config: GenerationConfig | None = None
    replace: bool = False


class SweepAxisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    values: list[Any]


class SweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: GenerationConfig
    axes: list[SweepAxisRequest] = Field(default_factory=list)
    repeats: Annotated[int, Field(ge=1, le=32)] = 1
    seed_strategy: SeedStrategy = "fixed"
    skip_duplicates: bool = True

    def to_spec(self) -> SweepSpec:
        return SweepSpec(
            base=self.base,
            axes=tuple(
                SweepAxis(field=axis.field, values=tuple(axis.values)) for axis in self.axes
            ),
            repeats=self.repeats,
            seed_strategy=self.seed_strategy,
        )


class RunQuery(BaseModel):
    """Parsed list filters. Kept as a model so the same parsing serves every caller."""

    model_config = ConfigDict(extra="forbid")

    status: list[RunStatus] = Field(default_factory=list)
    mode: str | None = None
    favourite: bool | None = None
    archived: bool | None = False
    rated: bool | None = None
    with_video: bool | None = None
    tag: str | None = None
    config_hash: str | None = None
    recipe_hash: str | None = None
    query: str | None = None
    min_stars: Annotated[int, Field(ge=1, le=10)] | None = None
    ids: list[str] = Field(default_factory=list)
    sort: SortKey = "recent"
    limit: Annotated[int, Field(ge=1, le=500)] = 60
    offset: Annotated[int, Field(ge=0)] = 0

    def to_filter(self) -> RunFilter:
        return RunFilter(
            status=tuple(self.status),
            mode=self.mode,
            favourite=self.favourite,
            archived=self.archived,
            rated=self.rated,
            with_video=self.with_video,
            tag=self.tag,
            config_hash=self.config_hash,
            recipe_hash=self.recipe_hash,
            ids=tuple(self.ids),
            query=self.query,
            min_stars=self.min_stars,
        )


class LeaderboardQuery(BaseModel):
    """The caller's trade-off between quality and speed, plus how deep a list to return.

    Held in one model because FastAPI flattens a Pydantic query model only when it is the
    sole query parameter on the route; a stray scalar beside it makes the whole model
    arrive as one required parameter instead.
    """

    model_config = ConfigDict(extra="forbid")

    quality: Annotated[float, Field(ge=0.0)] = 0.7
    speed: Annotated[float, Field(ge=0.0)] = 0.3
    limit: Annotated[int, Field(ge=1, le=200)] = 50

    def to_weights(self) -> ScoreWeights:
        return ScoreWeights(quality=self.quality, speed=self.speed)


ProblemKind = Literal[
    "not_found",
    "invalid",
    "conflict",
    "comfy_unreachable",
    "workflow",
    "internal",
]


class Problem(BaseModel):
    """A refusal the UI can render. One shape for every failure."""

    model_config = ConfigDict(frozen=True)

    error: str
    detail: str
    kind: ProblemKind = "invalid"
    fields: dict[str, str] = Field(default_factory=dict)


class Ok(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool = True
    detail: str = ""
    count: int | None = None
