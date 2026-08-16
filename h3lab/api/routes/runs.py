"""Runs, the queue, and sweeps — everything that creates or changes work."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse

from h3lab.api.deps import LabDep, SharedClientDep
from h3lab.api.schemas import (
    CreateRunRequest,
    DryRunRequest,
    EnqueueRequest,
    Ok,
    PatchRunRequest,
    RerunRequest,
    RunQuery,
    SharedSweepRequest,
    SweepRequest,
)
from h3lab.domain.sweeps import SweepPreview
from h3lab.engine.lab import DryRun, Lab, QueueState, RunPage, RunView
from h3lab.shared.client import SharedContentStream
from h3lab.shared.contracts import (
    CancelAction,
    DeleteAction,
    DownloadComponent,
    JobDocument,
    JobSubmission,
    PreviewComponent,
    PublicJob,
    RetryCollectionAction,
    VideoComponent,
)
from h3lab.storage.runs import RunNotFound

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(lab: LabDep, query: Annotated[RunQuery, Query()]) -> RunPage:
    return lab.list_runs(
        query.to_filter(), sort=query.sort, limit=query.limit, offset=query.offset
    )


@router.post("/runs", status_code=201)
def enqueue(
    lab: LabDep,
    body: CreateRunRequest,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ] = None,
) -> list[RunView]:
    if isinstance(body, JobSubmission):
        if idempotency_key is None:
            raise HTTPException(status_code=422, detail="Idempotency-Key is required")
        document = lab.shared_generation_document()
        return lab.enqueue_shared(document, body, request_key=idempotency_key)
    if isinstance(body, EnqueueRequest):
        if not lab.legacy_execution_enabled:
            raise HTTPException(
                status_code=409,
                detail="legacy generation bodies are disabled; use the shared generation document",
            )
        return lab.enqueue(body.config, count=body.count)
    raise HTTPException(status_code=422, detail="invalid run request")


@router.post("/runs/dry-run")
def dry_run(lab: LabDep, body: DryRunRequest) -> DryRun:
    """Build the graph and report problems without spending GPU time on them."""
    return lab.dry_run(body.config)


@router.get("/runs/{run_id}")
def get_run(lab: LabDep, run_id: str) -> RunView:
    return lab.get_run(run_id)


@router.get("/runs/{run_id}/shared", response_model=PublicJob)
def shared_job(lab: LabDep, run_id: str) -> PublicJob:
    run, shared = _linked_shared(lab, run_id)
    job = shared.get_job(run.shared_job_id)
    base = f"/api/runs/{run_id}"
    artifact = (
        None
        if job.artifact is None
        else job.artifact.model_copy(update={"content_url": f"{base}/shared-video"})
    )
    links = job.links.model_copy(
        update={
            "self": f"{base}/shared",
            "view": f"{base}/shared-view",
            "events": f"{base}/shared-events",
            "preview": (
                None if job.links.preview is None else f"{base}/shared-preview"
            ),
            "cancel": None if job.links.cancel is None else f"{base}/cancel",
            "retry_collection": (
                None
                if job.links.retry_collection is None
                else f"{base}/retry-collection"
            ),
        }
    )
    return job.model_copy(update={"artifact": artifact, "links": links})


@router.get("/runs/{run_id}/shared-view", response_model=JobDocument)
def shared_job_view(lab: LabDep, run_id: str) -> JobDocument:
    run, shared = _linked_shared(lab, run_id)
    document = shared.get_job_document(run.shared_job_id)
    base = f"/api/runs/{run_id}"
    components = []
    for component in document.components:
        if isinstance(component, PreviewComponent):
            component = component.model_copy(update={"src": f"{base}/shared-preview"})
        elif isinstance(component, VideoComponent):
            component = component.model_copy(
                update={"src": f"{base}/shared-video", "poster": None}
            )
        elif isinstance(component, DownloadComponent):
            component = component.model_copy(update={"href": f"{base}/shared-video"})
        components.append(component)
    actions = []
    for action in document.actions:
        if isinstance(action, CancelAction):
            action = action.model_copy(update={"endpoint": f"{base}/cancel"})
        elif isinstance(action, RetryCollectionAction):
            action = action.model_copy(update={"endpoint": f"{base}/retry-collection"})
        elif isinstance(action, DeleteAction):
            action = action.model_copy(update={"endpoint": base})
        actions.append(action)
    return document.model_copy(update={"components": components, "actions": actions})


@router.get("/runs/{run_id}/shared-events")
def shared_job_events(
    lab: LabDep,
    run_id: str,
    after: Annotated[
        int | None,
        Header(alias="Last-Event-ID", ge=0),
    ] = None,
) -> StreamingResponse:
    run, shared = _linked_shared(lab, run_id)

    def stream() -> Iterator[str]:
        for event in shared.iter_events(
            run.shared_job_id,
            after_sequence=after,
        ):
            payload = event.model_dump(mode="json", by_alias=True)
            if event.type == "preview" and isinstance(payload["data"], dict):
                payload["data"].pop("url", None)
                payload["data"]["url"] = f"/api/runs/{run_id}/shared-preview"
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {event.sequence}\nevent: {event.type}\ndata: {encoded}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/shared-preview")
def shared_job_preview(
    lab: LabDep,
    run_id: str,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> StreamingResponse:
    run, shared = _linked_shared(lab, run_id)
    job = shared.get_job(run.shared_job_id)
    if job.links.preview is None:
        raise HTTPException(status_code=404, detail="no shared preview is available")
    return _stream_response(
        shared.open_content(
            f"/v1/jobs/{job.id}/preview",
            if_none_match=if_none_match,
        )
    )


@router.get("/runs/{run_id}/shared-video")
def shared_job_video(
    lab: LabDep,
    run_id: str,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> StreamingResponse:
    run, shared = _linked_shared(lab, run_id)
    job = shared.get_job(run.shared_job_id)
    if job.artifact is None:
        raise HTTPException(status_code=404, detail="no shared video is available")
    return _stream_response(
        shared.open_content(
            job.artifact.content_url,
            range_header=range_header,
            if_none_match=if_none_match,
        )
    )


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
def rerun(
    lab: LabDep,
    run_id: str,
    body: RerunRequest | None = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ] = None,
) -> RunView:
    return lab.rerun(
        run_id,
        overrides=(body.overrides if body else None),
        request_key=idempotency_key,
    )


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


@router.post("/runs/{run_id}/retry-collection")
def retry_collection(lab: LabDep, run_id: str) -> Ok:
    retried = lab.retry_collection(run_id)
    return Ok(
        ok=retried,
        detail="collection retry started" if retried else "that run is not awaiting collection",
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
def preview_sweep(
    lab: LabDep,
    body: SweepRequest | SharedSweepRequest,
    shared: SharedClientDep,
) -> SweepPreview:
    """What would this sweep queue, and how much of it is already known?"""
    if isinstance(body, SharedSweepRequest):
        return lab.preview_shared_sweep(
            shared.get_generation_document(),
            body.to_spec(),
        )
    return lab.preview_sweep(body.to_spec())


@router.post("/sweeps", status_code=201)
def run_sweep(
    lab: LabDep,
    body: SweepRequest | SharedSweepRequest,
    shared: SharedClientDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ] = None,
) -> list[RunView]:
    if isinstance(body, SharedSweepRequest):
        return lab.run_shared_sweep(
            shared.get_generation_document(),
            body.to_spec(),
            skip_duplicates=body.skip_duplicates,
            request_key=idempotency_key,
        )
    return lab.run_sweep(
        body.to_spec(),
        skip_duplicates=body.skip_duplicates,
        request_key=idempotency_key,
    )


def _linked_shared(lab: Lab, run_id: str):
    run = lab.runs.require(run_id)
    if run.shared_job_id is None or lab.shared_client is None:
        raise HTTPException(status_code=404, detail="run has no shared job")
    return run, lab.shared_client


def _stream_response(stream: SharedContentStream) -> StreamingResponse:
    def body() -> Iterator[bytes]:
        try:
            yield from stream.iter_bytes()
        finally:
            stream.close()

    return StreamingResponse(
        body(),
        status_code=stream.status_code,
        headers=dict(stream.headers),
        media_type=stream.headers.get("content-type"),
    )
