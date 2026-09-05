from __future__ import annotations

import copy
import json
import re
import time

from h3lab.comfy.client import ComfyError
from h3lab.comfy.graph import apply_config, load_workflow
from h3lab.comfy.schema import static_schemas
from h3lab.comfy.studio import StudioContractError, prepare_prompt
from h3lab.domain.config import GenerationConfig
from h3lab.engine.events import EventBus
from h3lab.engine.runner import Runner
from h3lab.storage import open_store
from h3lab.storage.runs import RunRepository
from tests.conftest import unified_workflow_path

TEST_MODEL = "minimax-h3/test-model.safetensors"


class RecordingPrepare:
    def __init__(self) -> None:
        self.calls = []

    def prepare_studio(self, workflow, inputs):
        self.calls.append((workflow, inputs))
        prepared = copy.deepcopy(workflow)
        prepared["contract-marker"] = {
            "class_type": "ContractPrepared",
            "inputs": {},
        }
        return {
            "contract_version": 1,
            "workflow": prepared,
            "inputs": {**inputs, "prepared": True},
            "capabilities": {},
            "warnings": [],
        }


def live_dual_with_rtx_multiplier():
    workflow = load_workflow(unified_workflow_path())

    def update(value):
        if isinstance(value, list):
            for child in value:
                update(child)
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("title"), str):
            value["title"] = re.sub(r"\s*\[H3S:[^\]]+\]", "", value["title"]).strip()
        if value.get("type") == "RTXVideoSuperResolution":
            value["inputs"] = [
                item
                for item in value["inputs"]
                if item.get("name") not in {"resize_type.width", "resize_type.height"}
            ]
            value["inputs"].append(
                {
                    "name": "resize_type.scale",
                    "type": "FLOAT",
                    "widget": {"name": "resize_type.scale"},
                    "link": None,
                }
            )
            value["widgets_values"] = ["scale by multiplier", 2, "ULTRA"]
            value["widgets_values_named"] = {
                "resize_type": "scale by multiplier",
                "resize_type.scale": 2,
                "quality": "ULTRA",
            }
        for child in value.values():
            update(child)

    update(workflow)
    return workflow


def test_prepare_helper_returns_the_exact_contract_workflow():
    client = RecordingPrepare()
    config = GenerationConfig(
        mode="t2v",
        prompt="prepare this",
        widgets={"attn": "comfy_kitchen"},
    )
    prepared = prepare_prompt(
        client,
        load_workflow(unified_workflow_path()),
        config,
        schemas=static_schemas(),
    )
    assert len(client.calls) == 1
    source, inputs = client.calls[0]
    assert "contract-marker" not in source
    assert inputs["attn"] == "comfy_kitchen"
    assert prepared.prompt["contract-marker"]["class_type"] == "ContractPrepared"
    assert prepared.inputs["prepared"] is True


def test_source_is_configured_before_the_studio_contract_is_requested():
    client = RecordingPrepare()
    config = GenerationConfig(
        mode="t2v",
        prompt="benchmark",
        cache="spectrum",
        cache_preset="aggressive",
        sol_preset="aggressive",
        turbo=True,
        turbo_lora="custom_8step.safetensors",
        turbo_lora_strength=0.65,
        widgets={"attn": "sol", "post_grade": True, "dual": True},
    )
    workflow = load_workflow(unified_workflow_path())
    prepare_prompt(
        client,
        workflow,
        config,
        schemas=static_schemas(),
    )
    source, inputs = client.calls[0]
    expected = apply_config(
        workflow,
        config,
        schemas=static_schemas(),
    )
    assert source == expected
    assert inputs["turbo_lora"] == "custom_8step.safetensors"
    assert inputs["attn"] == "sol"
    assert inputs["post_grade"] is True
    assert inputs["dual"] is True


def test_prepare_preserves_every_non_studio_node(stub):
    workflow = load_workflow(unified_workflow_path())
    config = GenerationConfig(mode="t2v", prompt="opaque", widgets={"attn": "sol"})
    source = apply_config(
        workflow,
        config,
        schemas=static_schemas(),
    )
    prepared = prepare_prompt(
        stub,
        workflow,
        config,
        schemas=static_schemas(),
    )

    def without_studio(prompt):
        return {
            node_id: node
            for node_id, node in prompt.items()
            if node["class_type"] != "MiniMaxH3Studio"
        }

    assert without_studio(prepared.prompt) == without_studio(source)


def _runner(lab_settings, stub):
    runs = RunRepository(open_store(lab_settings.db_path))
    events = EventBus()
    return (
        Runner(runs=runs, settings=lab_settings, events=events, client=stub),
        runs,
        events,
    )


def _wait_for(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return False


def test_runner_prepares_once_and_submits_the_returned_workflow(
    lab_settings,
    stub,
):
    runner, runs, events = _runner(lab_settings, stub)
    original = stub.prepare_studio
    returned = []

    def marked(workflow, inputs):
        result = original(workflow, inputs)
        result["workflow"] = copy.deepcopy(result["workflow"])
        result["workflow"]["contract-marker"] = {
            "class_type": "ContractPrepared",
            "inputs": {},
        }
        returned.append(copy.deepcopy(result["workflow"]))
        return result

    stub.prepare_studio = marked
    run = runs.create(
        GenerationConfig(
            mode="t2v",
            prompt="runner",
            diffusion_model="legacy-model-not-installed.safetensors",
        )
    )
    try:
        runner.start()
        assert _wait_for(lambda: runs.require(run.id).status == "succeeded")
        assert len(stub.prepare_calls) == 1
        assert stub.submitted[0] == returned[0]
    finally:
        runner.stop()
        events.close()


def test_runner_prepares_the_current_untagged_live_save(
    lab_settings,
    stub,
    tmp_path,
):
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    live = live_dual_with_rtx_multiplier()
    (workflow_dir / "minimax_h3_unified_guided_dual.json").write_text(
        json.dumps(live),
        encoding="utf-8",
    )
    runner, runs, events = _runner(
        lab_settings.with_overrides(workflow_dir=workflow_dir),
        stub,
    )
    run = runs.create(
        GenerationConfig(
            mode="t2v",
            diffusion_model=TEST_MODEL,
            prompt="live",
            upscaler=True,
        )
    )
    try:
        runner.start()
        assert _wait_for(lambda: runs.require(run.id).status == "succeeded")
        source, _inputs = stub.prepare_calls[0]
        expected = apply_config(
            live,
            run.config,
            output_tag=run.id,
            schemas=static_schemas(),
        )
        assert source == expected
    finally:
        runner.stop()
        events.close()


def test_runner_fails_when_comfyui_emits_no_video(lab_settings, stub):
    runner, runs, events = _runner(lab_settings, stub)
    execute = stub.execute

    def still_only(*args, **kwargs):
        outcome = execute(*args, **kwargs)
        outcome.history = {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {
                "preview": {
                    "images": [{"filename": "preview.png", "type": "temp"}],
                },
            },
        }
        return outcome

    stub.execute = still_only
    run = runs.create(
        GenerationConfig(mode="t2v", diffusion_model=TEST_MODEL, prompt="no video")
    )
    try:
        runner.start()
        assert _wait_for(lambda: runs.require(run.id).status == "failed")
        assert runs.require(run.id).error == "ComfyUI completed without a video output"
        assert stub.downloads == []
    finally:
        runner.stop()
        events.close()


def test_structured_contract_error_fails_without_submission(lab_settings, stub):
    runner, runs, events = _runner(lab_settings, stub)

    def reject(_workflow, _inputs):
        raise StudioContractError(
            "contract_unavailable",
            "Studio contract v1 is missing",
        )

    stub.prepare_studio = reject
    run = runs.create(
        GenerationConfig(mode="t2v", diffusion_model=TEST_MODEL, prompt="reject")
    )
    try:
        runner.start()
        assert _wait_for(lambda: runs.require(run.id).status == "failed")
        assert "contract v1" in (runs.require(run.id).error or "")
        assert "unexpected" not in (runs.require(run.id).error or "")
        assert stub.submitted == []
    finally:
        runner.stop()
        events.close()


def test_prepare_transport_failure_requeues_without_submission(lab_settings, stub):
    runner, runs, events = _runner(lab_settings, stub)

    def offline(_workflow, _inputs):
        raise ComfyError("temporary prepare failure")

    stub.prepare_studio = offline
    run = runs.create(
        GenerationConfig(mode="t2v", diffusion_model=TEST_MODEL, prompt="retry")
    )
    claimed = runs.claim_next()
    runner._stop.set()
    try:
        runner._execute(claimed)
        assert runs.require(run.id).status == "queued"
        assert stub.submitted == []
    finally:
        runner.stop()
        events.close()
