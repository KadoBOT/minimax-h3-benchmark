"""Reading the results back: leaderboard, diffs, axis insights, recipe groups."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from h3lab.api.deps import LabDep
from h3lab.api.errors import problem
from h3lab.api.schemas import LeaderboardQuery
from h3lab.domain.insights import AxisDef, AxisInsight
from h3lab.engine.lab import Comparison, Leaderboard, RecipeGroup

router = APIRouter(tags=["analysis"])


@router.get("/leaderboard")
def leaderboard(lab: LabDep, query: Annotated[LeaderboardQuery, Query()]) -> Leaderboard:
    """Ranked runs under the caller's quality/speed trade-off, with the score broken out."""
    return lab.leaderboard(weights=query.to_weights(), limit=query.limit)


@router.get("/compare")
def compare(lab: LabDep, ids: Annotated[list[str], Query(min_length=2, max_length=8)]) -> Comparison:
    """Side-by-side runs: what differs between them, and what they hold in common."""
    return lab.compare(ids)


@router.get("/insights/axes")
def insight_axes(lab: LabDep) -> list[AxisDef]:
    return lab.axes()


@router.get("/insights/{axis}", response_model=AxisInsight)
def insight(lab: LabDep, axis: str) -> Any:
    try:
        return lab.insight(axis)
    except KeyError as exc:
        return problem(404, "not_found", "unknown axis", str(exc), axis=axis)


@router.get("/recipes")
def recipes(lab: LabDep, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[RecipeGroup]:
    """Runs grouped by recipe, so replicates of one experiment read as a single row."""
    return lab.recipes(limit=limit)


@router.get("/tags")
def tags(lab: LabDep) -> list[str]:
    return lab.tags()
