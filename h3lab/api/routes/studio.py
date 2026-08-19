from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from h3lab.api.deps import LabDep
from h3lab.domain.config import GenMode

router = APIRouter(prefix="/studio", tags=["studio"])


class StudioPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    workflow: dict[str, Any]
    inputs: dict[str, Any]


@router.get("/session")
def session(lab: LabDep, mode: GenMode = "flf2v") -> JSONResponse:
    return JSONResponse(lab.studio_session(mode))


@router.get("/component.js")
def component(lab: LabDep) -> Response:
    source, content_type = lab.client.studio_component()
    return Response(
        source,
        headers={
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
        },
    )


@router.post("/prepare")
def prepare(request: StudioPrepareRequest, lab: LabDep) -> JSONResponse:
    return JSONResponse(
        lab.client.prepare_studio(request.workflow, request.inputs)
    )


__all__ = ["router"]
