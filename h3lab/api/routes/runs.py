"""Runs, the queue, and sweeps — everything that creates or changes work."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from h3lab.api.deps import LabDep
from h3lab.api.schemas import (
    DryRunRequest,
    EnqueueRequest,
    Ok,
    PatchRunRequest,
    RerunRequest,
    RunQuery,
    SweepRequest,
)
from h3lab.domain.sweeps import SweepPreview
from h3lab.engine.lab import DryRun, Neighbors, QueueState, RunPage, RunView
from h3lab.storage.runs import RunNotFound

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(lab: LabDep, query: Annotated[RunQuery, Query()]) -> RunPage:
    return lab.list_runs(
        query.to_filter(), sort=query.sort, limit=query.limit, offset=query.offset
    )


@router.post("/runs", status_code=201)
def enqueue(lab: LabDep, body: EnqueueRequest) -> list[RunView]:
    return lab.enqueue(body.config, count=body.count)


@router.post("/runs/dry-run")
def dry_run(lab: LabDep, body: DryRunRequest) -> DryRun:
    """Build the graph and report problems without spending GPU time on them."""
    return lab.dry_run(body.config)


@router.get("/runs/{run_id}")
def get_run(lab: LabDep, run_id: str) -> RunView:
    return lab.get_run(run_id)


@router.get("/runs/{run_id}/neighbors")
def run_neighbors(
    lab: LabDep, run_id: str, query: Annotated[RunQuery, Query()]
) -> Neighbors:
    return lab.neighbors(run_id, query.to_filter(), sort=query.sort)


@router.get("/runs/{run_id}/workflow")
def run_workflow(lab: LabDep, run_id: str) -> JSONResponse:
    """The run's graph as a file ComfyUI opens.

    Not the API prompt the run was submitted as — that loads as a heap of unpositioned boxes.
    This is the template's own layout with the run's settings applied, which is the thing
    somebody asking for "the workflow for this run" means.

    Declared as a `JSONResponse` rather than a model because a ComfyUI workflow has no schema
    the lab owns; pinning one here would mean editing this file whenever ComfyUI adds a key.
    """
    workflow = lab.workflow_for_run(run_id)
    return JSONResponse(
        workflow,
        headers={"Content-Disposition": f'attachment; filename="h3lab-{run_id}.json"'},
    )


@router.get("/runs/{run_id}/preview", response_class=Response)
def run_preview(lab: LabDep, run_id: str) -> Response:
    """The frame ComfyUI is drawing right now, for the run that is rendering.

    404 is the normal answer, not an error: a run that is queued, finished, or built from a
    template with no preview override has no frame, and the page asking simply shows nothing.
    """
    frame = lab.preview(run_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="no preview frame for this run")
    return Response(
        content=frame.data,
        media_type=frame.content_type,
        # Every frame lives at the same URL for a few hundred milliseconds. A cached one is a
        # picture of a sampling step that is already over.
        headers={"Cache-Control": "no-store", "X-Preview-Seq": str(frame.seq)},
    )


@router.post("/runs/{run_id}/rerun", status_code=201)
def rerun(lab: LabDep, run_id: str, body: RerunRequest | None = None) -> RunView:
    return lab.rerun(run_id, overrides=(body.overrides if body else None))


@router.patch("/runs/{run_id}")
def patch_run(lab: LabDep, run_id: str, body: PatchRunRequest) -> RunView:
    return lab.patch(
        run_id,
        favourite=body.favourite,
        archived=body.archived,
        notes=body.notes,
        label=body.label,
        tags=body.tags,
    )


@router.delete("/runs/{run_id}")
def delete_run(lab: LabDep, run_id: str) -> Ok:
    if not lab.delete_run(run_id):
        raise RunNotFound(run_id)
    return Ok(detail="run deleted")


@router.post("/runs/{run_id}/cancel")
def cancel_run(lab: LabDep, run_id: str) -> Ok:
    cancelled = lab.cancel(run_id)
    return Ok(
        ok=cancelled,
        detail="cancelled" if cancelled else "that run had already finished",
    )


@router.get("/queue")
def queue(lab: LabDep) -> QueueState:
    return lab.queue_state()


@router.post("/queue/pause")
def pause(lab: LabDep) -> Ok:
    lab.pause()
    return Ok(detail="queue paused")


@router.post("/queue/resume")
def resume(lab: LabDep) -> Ok:
    lab.resume()
    return Ok(detail="queue resumed")


@router.post("/queue/clear")
def clear_queue(lab: LabDep) -> Ok:
    removed = lab.cancel_all()
    return Ok(detail=f"cancelled {removed} queued run(s)", count=removed)


@router.post("/sweeps/preview")
def preview_sweep(lab: LabDep, body: SweepRequest) -> SweepPreview:
    """What would this sweep queue, and how much of it is already known?"""
    return lab.preview_sweep(body.to_spec())


@router.post("/sweeps", status_code=201)
def run_sweep(lab: LabDep, body: SweepRequest) -> list[RunView]:
    return lab.run_sweep(body.to_spec(), skip_duplicates=body.skip_duplicates)
