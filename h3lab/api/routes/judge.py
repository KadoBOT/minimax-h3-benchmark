"""Judging: absolute ratings and pairwise votes.

Which pair to vote on is the arena's business, not this module's — see `routes/arena.py`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from h3lab.api.deps import LabDep
from h3lab.api.schemas import RateRequest, VoteRequest
from h3lab.domain.rating import Vote
from h3lab.engine.lab import RunView

router = APIRouter(tags=["judge"])


@router.put("/runs/{run_id}/rating")
def rate(lab: LabDep, run_id: str, body: RateRequest) -> RunView:
    """Set the stars (and optional per-criterion marks) for a run. Idempotent."""
    return lab.rate(run_id, body.stars, body.known_criteria)


@router.delete("/runs/{run_id}/rating")
def unrate(lab: LabDep, run_id: str) -> RunView:
    return lab.unrate(run_id)


@router.post("/votes", status_code=201)
def vote(lab: LabDep, body: VoteRequest) -> Vote:
    """Record a head-to-head result. A null winner is a draw, which still carries signal."""
    return lab.vote(body.run_a, body.run_b, body.winner, axis=body.axis)


@router.get("/votes")
def list_votes(lab: LabDep, limit: Annotated[int, Query(ge=1, le=2000)] = 200) -> list[Vote]:
    return lab.votes.list(limit=limit)


@router.get("/elo")
def elo(lab: LabDep) -> dict[str, Any]:
    return {run_id: entry.model_dump() for run_id, entry in lab.elo_table().items()}
