"""Same-origin browser facade for the standalone shared SDUI service."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, UploadFile
from fastapi.responses import StreamingResponse

from h3lab.api.deps import SharedClientDep
from h3lab.shared.client import SharedContentStream
from h3lab.shared.contracts import GenerationDocument, PublicMediaMetadata

router = APIRouter(prefix="/shared", tags=["shared generation"])


@router.get("/generation", response_model=GenerationDocument)
def generation_document(shared: SharedClientDep) -> GenerationDocument:
    document = shared.get_generation_document()
    actions = [
        action.model_copy(update={"endpoint": "/api/runs"})
        for action in document.actions
    ]
    return document.model_copy(update={"actions": actions})


@router.post("/assets", status_code=201, response_model=PublicMediaMetadata)
def upload_asset(
    shared: SharedClientDep,
    file: Annotated[UploadFile, File()],
) -> PublicMediaMetadata:
    metadata = shared.upload_asset(
        file.file,
        filename=file.filename or "upload",
        mime=file.content_type or "application/octet-stream",
    )
    return metadata.model_copy(
        update={"content_url": f"/api/shared/assets/{metadata.id}/content"}
    )


@router.get("/assets/{asset_id}/content")
def asset_content(
    asset_id: UUID,
    shared: SharedClientDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> StreamingResponse:
    stream = shared.open_content(
        f"/v1/assets/{asset_id}/content",
        range_header=range_header,
        if_none_match=if_none_match,
    )
    return StreamingResponse(
        _stream_and_close(stream),
        status_code=stream.status_code,
        headers=dict(stream.headers),
        media_type=stream.headers.get("content-type"),
    )


def _stream_and_close(stream: SharedContentStream) -> Iterator[bytes]:
    try:
        yield from stream.iter_bytes()
    finally:
        stream.close()


__all__ = ["router"]
