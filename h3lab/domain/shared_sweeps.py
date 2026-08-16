"""Server-owned sweep expansion over a pinned SDUI generation document."""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Callable, Iterator
from itertools import product
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from h3lab.shared.contracts import (
    GenerationDocument,
    InputComponent,
    JobSubmission,
    NumberComponent,
    Predicate,
    SeedComponent,
    SelectComponent,
    ToggleComponent,
)
from h3lab.shared.projection import materialize_submission, project_h3_submission

SeedStrategy = Literal["fixed", "increment", "random"]
MAX_EXPANSION = 512


class SharedSweepAxis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding: Annotated[str, Field(min_length=1, max_length=128)]
    values: tuple[JsonValue, ...]

    @field_validator("values")
    @classmethod
    def distinct_values(cls, values: tuple[JsonValue, ...]) -> tuple[JsonValue, ...]:
        unique: list[JsonValue] = []
        keys: set[str] = set()
        for value in values:
            key = _json_key(value)
            if key in keys:
                continue
            keys.add(key)
            unique.append(value)
        if len(unique) < 2:
            raise ValueError("a sweep axis requires at least two distinct values")
        return tuple(unique)


class SharedSweepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: JobSubmission
    axes: tuple[SharedSweepAxis, ...] = ()
    repeats: Annotated[int, Field(ge=1, le=32)] = 1
    seed_strategy: SeedStrategy = "fixed"

    @model_validator(mode="after")
    def unique_axes_and_budget(self) -> SharedSweepSpec:
        bindings = [axis.binding for axis in self.axes]
        if len(bindings) != len(set(bindings)):
            raise ValueError("duplicate sweep axis binding")
        combinations = math.prod(len(axis.values) for axis in self.axes)
        if combinations * self.repeats > MAX_EXPANSION:
            raise ValueError(f"sweep expansion exceeds {MAX_EXPANSION} runs")
        return self


def expand_shared_sweep(
    document: GenerationDocument,
    spec: SharedSweepSpec,
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> tuple[JobSubmission, ...]:
    base = materialize_submission(document, spec.base, randbelow=randbelow)
    inputs = {
        component.binding: component
        for component in document.components
        if isinstance(component, InputComponent)
    }
    sweepable = (NumberComponent, SelectComponent, ToggleComponent)

    for axis in spec.axes:
        component = inputs.get(axis.binding)
        if component is None:
            raise ValueError(f"unknown sweep binding {axis.binding!r}")
        if not isinstance(component, sweepable):
            raise ValueError(f"{axis.binding} is not sweepable")
        if not _visible(component, base.input):
            raise ValueError(f"{axis.binding} is not visible for the base submission")
        for value in axis.values:
            _validate_axis_value(component, value)

    seed = next(
        (
            component
            for component in document.components
            if isinstance(component, SeedComponent)
        ),
        None,
    )
    if seed is None:
        raise ValueError("the generation document has no seed component")
    base_seed = base.input.get(seed.binding)
    if not isinstance(base_seed, int) or isinstance(base_seed, bool):
        raise ValueError("the materialized base seed is not an integer")

    random_seeds = _random_seeds(
        seed,
        math.prod(len(axis.values) for axis in spec.axes) * spec.repeats,
        randbelow,
    ) if spec.seed_strategy == "random" else iter(())
    expanded: list[JobSubmission] = []
    combinations = product(*(axis.values for axis in spec.axes)) if spec.axes else [()]
    for combination in combinations:
        overrides = {
            axis.binding: value
            for axis, value in zip(spec.axes, combination, strict=True)
        }
        for repeat in range(spec.repeats):
            values = {**base.input, **overrides}
            if spec.seed_strategy == "increment":
                candidate_seed = base_seed + repeat
                if candidate_seed > seed.maximum:
                    raise ValueError("incrementing seed exceeds the document maximum")
                values[seed.binding] = candidate_seed
            elif spec.seed_strategy == "random":
                values[seed.binding] = next(random_seeds)
            for axis in spec.axes:
                component = inputs[axis.binding]
                if not _visible(component, values):
                    raise ValueError(
                        f"{axis.binding} is not visible for every expanded submission"
                    )
            candidate = JobSubmission(
                workflowRevision=base.workflow_revision,
                schemaRevision=base.schema_revision,
                input=values,
            )
            materialized = materialize_submission(document, candidate, randbelow=randbelow)
            project_h3_submission(materialized)
            expanded.append(materialized)
    return tuple(expanded)


def _random_seeds(
    component: SeedComponent,
    count: int,
    randbelow: Callable[[int], int],
) -> Iterator[int]:
    span = component.maximum - component.minimum + 1
    if count > span:
        raise ValueError("the seed range is too small for unique random sweep seeds")
    used: set[int] = set()
    while len(used) < count:
        offset = randbelow(span)
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset < span:
            raise ValueError("random seed source returned an out-of-range value")
        candidate = component.minimum + offset
        if candidate in used:
            continue
        used.add(candidate)
        yield candidate


def _visible(component: InputComponent, values: dict[str, JsonValue]) -> bool:
    return all(_predicate_matches(predicate, values) for predicate in component.visible_when or ())


def _predicate_matches(predicate: Predicate, values: dict[str, JsonValue]) -> bool:
    actual = values.get(predicate.field)
    if predicate.operator == "equals":
        return _json_key(actual) == _json_key(predicate.value)
    if predicate.operator == "not_equals":
        return _json_key(actual) != _json_key(predicate.value)
    expected = predicate.value
    return isinstance(expected, list) and any(
        _json_key(actual) == _json_key(candidate) for candidate in expected
    )


def _validate_axis_value(
    component: NumberComponent | SelectComponent | ToggleComponent,
    value: JsonValue,
) -> None:
    if isinstance(component, ToggleComponent):
        if not isinstance(value, bool):
            raise ValueError(f"{component.binding} requires boolean sweep values")
        return
    if isinstance(component, SelectComponent):
        valid = {
            _json_key(option.value)
            for option in component.options
            if not option.disabled
        }
        if _json_key(value) not in valid:
            raise ValueError(f"{component.binding} contains an unavailable option")
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{component.binding} requires finite numeric sweep values")
    if component.integer and not float(value).is_integer():
        raise ValueError(f"{component.binding} requires integer sweep values")
    if component.minimum is not None and value < component.minimum:
        raise ValueError(f"{component.binding} is below its minimum")
    if component.maximum is not None and value > component.maximum:
        raise ValueError(f"{component.binding} is above its maximum")
    if component.step is not None:
        origin = component.minimum or 0
        units = (float(value) - origin) / component.step
        if not math.isclose(units, round(units), rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{component.binding} does not align with its step")


def _json_key(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "MAX_EXPANSION",
    "SeedStrategy",
    "SharedSweepAxis",
    "SharedSweepSpec",
    "expand_shared_sweep",
]
