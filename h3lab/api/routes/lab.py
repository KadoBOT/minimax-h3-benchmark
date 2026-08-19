"""Status, catalog, and the static vocabulary the UI builds its forms from."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from h3lab.api.deps import LabDep, SettingsDep
from h3lab.comfy.catalog import Catalog
from h3lab.domain.config import (
    CACHE_NAMES,
    FIELD_LABELS,
    INTERP_LABELS,
    INTERP_MODES,
    MODE_NEEDS,
    PRESET_LEVELS,
    GenerationConfig,
    ModeNeeds,
    field_defaults,
)
from h3lab.domain.insights import AXES, AxisDef
from h3lab.domain.rating import CRITERIA, CRITERION_LABELS, STARS_MAX, STARS_MIN
from h3lab.domain.sweeps import SEED_STRATEGIES
from h3lab.engine.lab import LabStatus

router = APIRouter(tags=["lab"])


class Health(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    worker_alive: bool
    paused: bool


class StarRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: int
    max: int


class Meta(BaseModel):
    """Stable benchmark vocabulary fetched once and cached forever.

    Every list here comes from the same constants the validators use, so a control can never
    offer a value the API would reject.
    """

    model_config = ConfigDict(frozen=True)

    axes: list[AxisDef]
    criteria: list[str]
    criterion_labels: dict[str, str]
    stars: StarRange
    seed_strategies: list[str]
    field_labels: dict[str, str]
    modes: list[ModeNeeds]
    caches: list[str]
    interpolations: list[str]
    interpolation_labels: dict[str, str]
    preset_levels: list[str]
    config_fields: list[str]
    defaults: dict[str, Any] = Field(default_factory=dict)
    comfy_url: str


@router.get("/health")
def health(lab: LabDep) -> Health:
    """Cheap liveness answer: is the process up and is the worker thread alive?"""
    return Health(ok=True, worker_alive=lab.runner.running, paused=lab.runner.paused)


@router.get("/status")
def status(lab: LabDep) -> LabStatus:
    return lab.status()


@router.get("/catalog")
def catalog(lab: LabDep, refresh: bool = False) -> Catalog:
    return lab.catalog(refresh=refresh)


@router.get("/meta")
def meta(lab: LabDep, settings: SettingsDep) -> Meta:
    return Meta(
        axes=list(AXES),
        criteria=list(CRITERIA),
        criterion_labels=dict(CRITERION_LABELS),
        stars=StarRange(min=STARS_MIN, max=STARS_MAX),
        seed_strategies=list(SEED_STRATEGIES),
        field_labels=dict(FIELD_LABELS),
        modes=list(MODE_NEEDS),
        caches=list(CACHE_NAMES),
        interpolations=list(INTERP_MODES),
        interpolation_labels=dict(INTERP_LABELS),
        preset_levels=list(PRESET_LEVELS),
        config_fields=sorted(GenerationConfig.model_fields),
        defaults=field_defaults(),
        comfy_url=settings.comfy_url,
    )
