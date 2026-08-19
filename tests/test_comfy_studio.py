"""MiniMaxH3Studio is the workflow API: one node owns mode, media, and engine knobs."""

from __future__ import annotations

import json

import pytest

from h3lab.comfy import roles as R
from h3lab.comfy.graph import (
    STUDIO_CLASS,
    apply_config,
    build,
    load_workflow,
    missing_links,
    referenced_files,
)
from h3lab.comfy.schema import static_schemas
from h3lab.comfy.studio import studio_session_prompt
from h3lab.comfy.workflow import executable, is_link, read
from tests.conftest import unified_workflow_path


@pytest.fixture(scope="module")
def studio_workflow():
    return load_workflow(unified_workflow_path())


def studio_built(workflow, config):
    return build(workflow, config)


def studio_inputs(workflow, config) -> dict:
    prompt, graph, roles = studio_built(workflow, config)
    node_id = roles.id(R.CONDITIONING)
    assert node_id is not None
    assert prompt[node_id]["class_type"] == STUDIO_CLASS
    return prompt[node_id]["inputs"]


def test_the_unified_template_is_a_studio_graph(studio_workflow):
    graph = read(studio_workflow)
    found = R.resolve(graph)
    assert found.missing() == []
    node = found.node(graph, R.CONDITIONING)
    assert node is not None
    assert node.class_type == STUDIO_CLASS


def test_session_is_the_generic_executable_prompt(studio_workflow):
    schemas = static_schemas()
    expected, _graph = executable(
        studio_workflow,
        widget_names=schemas.widget_names,
    )

    assert studio_session_prompt(studio_workflow, schemas) == expected


def test_session_requires_only_studio_and_no_output_role():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "MiniMaxH3Studio",
                "inputs": [],
                "outputs": [],
            },
            {
                "id": 2,
                "type": "AClassH3LabDoesNotKnow",
                "inputs": [],
                "outputs": [],
                "title": "ordinary output",
            },
        ],
        "links": [],
    }

    prompt = studio_session_prompt(workflow, static_schemas())

    assert prompt["2"]["class_type"] == "AClassH3LabDoesNotKnow"


@pytest.mark.parametrize("mode", ["flf2v", "t2v", "r2v"])
def test_every_mode_is_a_studio_widget_not_a_different_template(
    studio_workflow, base_config, mode
):
    config = base_config.merged(mode=mode, ref_images=("ref.png",))
    prompt, _graph, roles = studio_built(studio_workflow, config)
    assert missing_links(prompt) == []
    inputs = prompt[roles.id(R.CONDITIONING)]["inputs"]
    assert inputs["mode"] == {"flf2v": "FLF2V", "t2v": "T2V", "r2v": "R2V"}[mode]


def test_studio_owns_the_generation_knobs(studio_workflow, base_config):
    config = base_config.merged(
        prompt="a courier on a magnetic skateboard",
        duration_s=6.0,
        mp=0.9,
        scheduler="power_shift",
        sampler="exp_heun_2_x0_sde",
        steps=12,
        seed=99,
        interp="rife",
        turbo=True,
        turbo_lora="minimax_h3_fl2v_turbo_8step_v1.0.safetensors",
        cache="spectrum",
        upscaler=True,
        clean_vram=True,
        sol_attn=False,
    )
    inputs = studio_inputs(studio_workflow, config)
    assert inputs["prompt"] == config.prompt
    assert inputs["duration"] == 6.0
    assert inputs["megapixels"] == 0.9
    assert inputs["scheduler"] == "power_shift"
    assert inputs["sampler_name"] == "exp_heun_2_x0_sde"
    assert inputs["steps"] == 8
    assert inputs["seed"] == 99
    assert inputs["seed_mode"] == "fixed"
    assert inputs["interpolation"] == "rife"
    assert inputs["turbo"] is True
    assert inputs["turbo_lora"] == config.turbo_lora
    assert inputs["cache"] is True
    assert inputs["upscale_rtx"] is True
    assert inputs["upscale_ltx"] is False
    assert inputs["clean_vram"] is True
    assert inputs["sol_attn"] is False


def test_flf2v_writes_frame_filenames_on_studio(studio_workflow, base_config):
    config = base_config.merged(last_frame="end.png")
    inputs = studio_inputs(studio_workflow, config)
    assert inputs["mode"] == "FLF2V"
    assert inputs["first_frame"] == "frame.png"
    assert inputs["last_frame"] == "end.png"
    assert "LoadImage" not in {
        node["class_type"] for node in apply_config(studio_workflow, config).values()
    }


def test_r2v_writes_references_as_json(studio_workflow, base_config):
    config = base_config.merged(
        mode="r2v",
        ref_images=("a.png", "b.png"),
        ref_videos=("move.mp4",),
        ref_audios=("voice.wav",),
    )
    inputs = studio_inputs(studio_workflow, config)
    assert inputs["mode"] == "R2V"
    assert json.loads(inputs["references"]) == {
        "images": ["a.png", "b.png"],
        "videos": ["move.mp4"],
        "video_audios": [],
        "audios": ["voice.wav"],
    }


def test_studio_media_is_visible_to_preflight(studio_workflow, base_config):
    config = base_config.merged(
        mode="r2v",
        ref_images=("hero.png",),
        last_frame="",
    )
    prompt = apply_config(studio_workflow, config)
    assert "hero.png" in referenced_files(prompt)


def test_engine_knobs_stay_wired_to_studio(studio_workflow, base_config):
    config = base_config.merged(turbo=True, turbo_lora="turbo_8step.safetensors")
    prompt, _graph, roles = studio_built(studio_workflow, config)
    studio_id = roles.id(R.CONDITIONING)
    assert studio_id in prompt
    scheduler = prompt[roles.id(R.SCHEDULER)]["inputs"]
    assert is_link(scheduler["steps"])
    assert scheduler["steps"][0] == studio_id
    assert is_link(scheduler["scheduler"])
    assert scheduler["scheduler"][0] == studio_id
    turbo = prompt[roles.id(R.TURBO_LORA)]["inputs"]
    assert is_link(turbo.get("lora_name"))
    assert turbo["lora_name"][0] == studio_id


def test_the_reference_lora_stays_in_a_studio_graph(studio_workflow, base_config):
    prompt, graph, roles = studio_built(studio_workflow, base_config)
    assert missing_links(prompt) == []
    loaders = [
        node
        for node in graph
        if node.class_type == "LoraLoaderModelOnly" and node.id in prompt
    ]
    assert loaders, "the ref LoRA is part of the engine, not an optional bench slot"


def test_turning_turbo_off_writes_none_on_studio(studio_workflow, base_config):
    inputs = studio_inputs(studio_workflow, base_config.merged(turbo=False))
    assert inputs["turbo"] is False
    assert inputs["turbo_lora"] == "none"
