"""Sweeps: turn one base config plus a few axes into the run matrix they imply.

A sweep is how the lab stops being ad hoc. Because expansion validates every produced
config, an impossible combination fails at preview time rather than three runs into a
twenty-minute queue.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Annotated, Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from h3lab.domain.config import (
    STUDIO_EXTRA_FIELDS,
    TEMPLATE_AXIS_FIELD,
    GenerationConfig,
    config_hash,
)

SeedStrategy = Literal["fixed", "increment", "random"]
SEED_STRATEGIES: tuple[SeedStrategy, ...] = ("fixed", "increment", "random")

MAX_EXPANSION = 512
TemplateResolver = Callable[[GenerationConfig, str], GenerationConfig]
VIRTUAL_AXIS_FIELDS = frozenset({TEMPLATE_AXIS_FIELD})


class SweepAxis(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    values: tuple[Any, ...]

    @field_validator("field")
    @classmethod
    def _known_field(cls, value: str) -> str:
        if (
            value not in GenerationConfig.model_fields
            and value not in STUDIO_EXTRA_FIELDS
            and value not in VIRTUAL_AXIS_FIELDS
        ):
            raise ValueError(f"unknown config field {value!r}")
        if value == "seed":
            raise ValueError("vary the seed with repeats and seed_strategy, not as an axis")
        return value

    @field_validator("values", mode="before")
    @classmethod
    def _at_least_two(cls, value: Any) -> tuple[Any, ...]:
        items = tuple(value or ())
        if len(items) < 1:
            raise ValueError("an axis needs at least one value")
        # Preserve declared order but drop exact repeats.
        seen: list[Any] = []
        for item in items:
            if item not in seen:
                seen.append(item)
        return tuple(seen)


class SweepSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    base: GenerationConfig
    axes: tuple[SweepAxis, ...] = ()
    repeats: Annotated[int, Field(ge=1, le=32)] = 1
    seed_strategy: SeedStrategy = "fixed"

    @model_validator(mode="after")
    def _within_budget(self) -> SweepSpec:
        if self.count > MAX_EXPANSION:
            raise ValueError(
                f"sweep expands to {self.count} runs; the ceiling is {MAX_EXPANSION}. "
                "Narrow an axis or lower repeats."
            )
        return self

    @property
    def combinations(self) -> int:
        total = 1
        for axis in self.axes:
            total *= len(axis.values)
        return total

    @property
    def count(self) -> int:
        return self.combinations * self.repeats


def _product(axes: Sequence[SweepAxis]) -> list[dict[str, Any]]:
    combos: list[dict[str, Any]] = [{}]
    for axis in axes:
        combos = [{**combo, axis.field: value} for combo in combos for value in axis.values]
    return combos


def expand(
    spec: SweepSpec,
    *,
    rng: random.Random | None = None,
    template_resolver: TemplateResolver | None = None,
) -> list[GenerationConfig]:
    """Every config the sweep asks for, in declared axis order then repeat order."""
    generator = rng or random.Random()
    configs: list[GenerationConfig] = []
    used_seeds: set[int] = set()

    for combo in _product(spec.axes):
        overrides = dict(combo)
        template_id = overrides.pop(TEMPLATE_AXIS_FIELD, None)
        base = spec.base
        if template_id is not None:
            if template_resolver is None:
                raise ValueError("template axis requires the Studio template catalog")
            base = template_resolver(base, str(template_id))
        for repeat in range(spec.repeats):
            run_overrides = dict(overrides)
            if spec.seed_strategy == "increment":
                run_overrides["seed"] = base.seed + repeat
            elif spec.seed_strategy == "random":
                while True:
                    candidate = generator.randrange(0, 2**31 - 1)
                    if candidate not in used_seeds:
                        used_seeds.add(candidate)
                        break
                run_overrides["seed"] = candidate
            configs.append(base.merged(**run_overrides))
    return configs


class SweepPreviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: GenerationConfig
    config_hash: str
    already_ran: bool = False
    existing_run_id: str | None = None


class SweepPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int
    combinations: int
    repeats: int
    new_count: int
    duplicate_count: int
    items: list[SweepPreviewItem]


def preview(
    spec: SweepSpec,
    *,
    existing: dict[str, str] | None = None,
    rng: random.Random | None = None,
    template_resolver: TemplateResolver | None = None,
) -> SweepPreview:
    """Expand and mark which configs the lab has already produced."""
    known = existing or {}
    items: list[SweepPreviewItem] = []
    for cfg in expand(spec, rng=rng, template_resolver=template_resolver):
        digest = config_hash(cfg)
        run_id = known.get(digest)
        items.append(
            SweepPreviewItem(
                config=cfg,
                config_hash=digest,
                already_ran=run_id is not None,
                existing_run_id=run_id,
            )
        )
    duplicates = sum(1 for item in items if item.already_ran)
    return SweepPreview(
        count=len(items),
        combinations=spec.combinations,
        repeats=spec.repeats,
        new_count=len(items) - duplicates,
        duplicate_count=duplicates,
        items=items,
    )
