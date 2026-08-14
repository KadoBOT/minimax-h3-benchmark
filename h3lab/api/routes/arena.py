"""The arena: what to compare next, and what the comparisons have decided."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from h3lab.api.deps import LabDep
from h3lab.api.errors import problem
from h3lab.domain.arena import ArenaStandings
from h3lab.engine.lab import ArenaMatchup

router = APIRouter(prefix="/arena", tags=["arena"])


@router.get("/next", response_model=ArenaMatchup)
def next_matchup(
    lab: LabDep,
    exclude: Annotated[list[str] | None, Query()] = None,
    min_stars: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> Any:
    """Two runs that differ only in how they were sampled.

    `exclude` carries the runs this voter has skipped, so a clip they could not judge does
    not come back on the next request.
    `min_stars` filters participants by minimum score.
    """
    offered = lab.arena_matchup(exclude=exclude or [], min_stars=min_stars)
    if offered is None:
        filter_detail = f" with score ≥ {min_stars}" if min_stars and min_stars > 0 else ""
        return problem(
            404,
            "not_found",
            "nothing fair to compare yet",
            f"The arena only pairs finished runs{filter_detail} that share the same mode, prompt, "
            "megapixels, duration, interpolation and upscaler, and differ in how they were "
            "sampled. "
            "Sweep a sampler, scheduler, or set of weights over one recipe to fill it.",
        )
    return offered


@router.get("/standings")
def standings(
    lab: LabDep,
    min_stars: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> ArenaStandings:
    """Every setting the votes rank, plus the votes that could not be counted and why."""
    return lab.arena_standings(min_stars=min_stars)
