from __future__ import annotations

from typing import Any, Literal
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from h3lab.api.deps import LabDep
from h3lab.domain.config import GenMode
from h3lab.comfy.experiment import experiment_fields, node_roles

router = APIRouter(prefix="/studio", tags=["studio"])


class StudioPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    inputs: dict[str, Any]


@router.get("/session")
def session(lab: LabDep, mode: GenMode = "flf2v") -> JSONResponse:
    return JSONResponse(lab.studio_session(mode))


@router.get("/experiment")
def experiment_options(lab: LabDep, preset: Literal["speed", "quality", "quality_pece", "motion"] = "speed") -> dict[str, Any]:
    graph = lab.client.prepare_studio({}, {"preset": preset})["workflow"]
    schemas = lab.runner.schemas()
    defaults = {}
    options = {}
    for key, (node_id, field) in experiment_fields(graph).items():
        if node_id in graph and field in graph[node_id]["inputs"]:
            node = graph[node_id]
            defaults[key] = node["inputs"][field]
            options[key] = schemas.combo(node["class_type"], field)
    options["diffusion_model"] = sorted(set(options.get("diffusion_model", ())) | set(schemas.combo("UnetLoaderGGUF", "unet_name")))
    options["loras"] = schemas.combo("LoraLoaderModelOnly", "lora_name")
    options["refine_sampler"] = options.get("sampler", ())
    refine = node_roles(graph).get("refine")
    defaults["refine_enabled"] = refine is not None
    defaults["refine_sampler"] = graph[graph[refine]["inputs"]["sampler"][0]]["inputs"]["sampler_name"] if refine else "res_multistep"
    nodes = []
    for node_id, node in graph.items():
        schema = schemas.get(node["class_type"])
        inputs = {key: value for key, value in node["inputs"].items() if not isinstance(value, (list, dict))}
        if inputs:
            nodes.append({"id": node_id, "name": node.get("_meta", {}).get("title", node["class_type"]),
                          "class_type": node["class_type"], "inputs": inputs,
                          "specs": {key: asdict(value) for key, value in schema.specs.items()} if schema else {}})
    return {"defaults": defaults, "options": options, "nodes": nodes}


@router.post("/prepare")
def prepare(request: StudioPrepareRequest, lab: LabDep) -> JSONResponse:
    return JSONResponse(
        lab.client.prepare_studio({}, request.inputs)
    )


__all__ = ["router"]
