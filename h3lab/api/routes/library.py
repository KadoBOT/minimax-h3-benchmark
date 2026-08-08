"""The keep-what-works surface: presets, the pinned baseline, and the legacy import."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from h3lab.api.deps import LabDep
from h3lab.api.errors import problem
from h3lab.api.schemas import BaselineRequest, Ok, PresetRequest
from h3lab.storage.legacy import ImportReport
from h3lab.storage.library import Preset

router = APIRouter(tags=["library"])


@router.get("/presets")
def list_presets(lab: LabDep) -> list[Preset]:
    return lab.presets.list()


@router.post("/presets", status_code=201)
def create_preset(lab: LabDep, body: PresetRequest) -> Preset:
    """Save a config worth returning to, taken either from a run or sent directly."""
    return lab.save_preset(body.name, run_id=body.run_id, config=body.config, replace=body.replace)


@router.delete("/presets/{preset_id}", response_model=Ok)
def delete_preset(lab: LabDep, preset_id: str) -> Any:
    if not lab.presets.delete(preset_id):
        return problem(404, "not_found", "no such preset", preset_id, preset=preset_id)
    return Ok(detail="preset deleted")


@router.put("/baseline")
def set_baseline(lab: LabDep, body: BaselineRequest) -> dict[str, str | None]:
    """Pin the run everything else is read against. Send null to unpin."""
    return {"baseline_run_id": lab.set_baseline(body.run_id)}


@router.post("/legacy-import")
def legacy_import(lab: LabDep) -> ImportReport:
    """Pull runs and ratings out of the previous lab's database. Safe to call twice."""
    return lab.import_legacy()
