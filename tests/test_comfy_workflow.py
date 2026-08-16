"""Reading an editor workflow, including the subgraph shape ComfyUI now exports."""

from __future__ import annotations

import pytest

from h3lab.comfy.workflow import Graph, read, to_api_prompt
from h3lab.settings import Settings

MODES = ("flf2v", "t2v", "r2v")


@pytest.fixture(scope="module")
def templates() -> dict[str, dict]:
    from h3lab.comfy.graph import load_workflow

    settings = Settings()
    return {mode: load_workflow(settings.workflow_path(mode)) for mode in MODES}


def subgraph_workflow() -> dict:
    """One instance holding two nodes: the smallest graph with every boundary case in it."""
    return {
        "nodes": [
            {
                "id": 5,
                "type": "PrimitiveFloat",
                "widgets_values": [24.0],
                "outputs": [{"name": "FLOAT", "type": "FLOAT", "links": [1]}],
            },
            {
                "id": 9,
                "type": "sub-uuid",
                "inputs": [
                    {"name": "value", "type": "FLOAT", "link": 1},
                    {"name": "scheduler", "type": "COMBO", "widget": {"name": "scheduler"}},
                    {"name": "steps", "type": "INT", "widget": {"name": "steps"}},
                ],
                "outputs": [{"name": "SIGMAS", "type": "SIGMAS", "links": []}],
                "widgets_values": ["beta57", 12],
            },
        ],
        "links": [[1, 5, 0, 9, 0, "FLOAT"]],
        "definitions": {
            "subgraphs": [
                {
                    "id": "sub-uuid",
                    "inputNode": {"id": -10},
                    "outputNode": {"id": -20},
                    "inputs": [
                        {"name": "value", "type": "FLOAT"},
                        {"name": "scheduler", "type": "COMBO"},
                        {"name": "steps", "type": "INT"},
                    ],
                    "outputs": [{"name": "SIGMAS", "type": "SIGMAS"}],
                    "nodes": [
                        {
                            "id": 1,
                            "type": "PrimitiveFloat",
                            "inputs": [
                                {"name": "value", "type": "FLOAT", "widget": {"name": "value"}}
                            ],
                            "outputs": [{"name": "FLOAT", "type": "FLOAT", "links": [11]}],
                            "widgets_values": [8.0],
                        },
                        {
                            "id": 2,
                            "type": "BasicScheduler",
                            "mode": 4,
                            "inputs": [
                                {"name": "model", "type": "MODEL", "link": None},
                                {
                                    "name": "scheduler",
                                    "type": "COMBO",
                                    "widget": {"name": "scheduler"},
                                    "link": 12,
                                },
                                {
                                    "name": "steps",
                                    "type": "INT",
                                    "widget": {"name": "steps"},
                                    "link": 13,
                                },
                                {
                                    "name": "denoise",
                                    "type": "FLOAT",
                                    "widget": {"name": "denoise"},
                                    "link": 11,
                                },
                            ],
                            "outputs": [{"name": "SIGMAS", "type": "SIGMAS", "links": [14]}],
                            "widgets_values": ["simple", 20, 1.0],
                        },
                    ],
                    "links": [
                        {
                            "id": 11,
                            "origin_id": 1,
                            "origin_slot": 0,
                            "target_id": 2,
                            "target_slot": 3,
                            "type": "FLOAT",
                        },
                        {
                            "id": 12,
                            "origin_id": -10,
                            "origin_slot": 1,
                            "target_id": 2,
                            "target_slot": 1,
                            "type": "COMBO",
                        },
                        {
                            "id": 13,
                            "origin_id": -10,
                            "origin_slot": 2,
                            "target_id": 2,
                            "target_slot": 2,
                            "type": "INT",
                        },
                        {
                            "id": 14,
                            "origin_id": 2,
                            "origin_slot": 0,
                            "target_id": -20,
                            "target_slot": 0,
                            "type": "SIGMAS",
                        },
                    ],
                }
            ]
        },
    }


# --- the subgraph shape ----------------------------------------------------


def test_a_subgraph_instance_flattens_to_comfys_execution_ids():
    graph = read(subgraph_workflow())
    assert set(graph.nodes) == {"5", "9:1", "9:2"}
    assert graph.nodes["9:2"].class_type == "BasicScheduler"
    assert graph.nodes["9:2"].path == (9,)
    assert graph.nodes["9:2"].local_id == 2


def test_a_promoted_widget_reaches_the_inner_node():
    graph = read(subgraph_workflow())
    inputs = graph.nodes["9:2"].inputs
    assert inputs["scheduler"] == "beta57"
    assert inputs["steps"] == 12


def test_an_inner_link_keeps_its_flat_source():
    graph = read(subgraph_workflow())
    assert graph.nodes["9:2"].inputs["denoise"] == ["9:1", 0]


def test_a_boundary_link_resolves_to_the_source_outside_the_subgraph():
    workflow = subgraph_workflow()
    # Promote the outer PrimitiveFloat into the inner one's `value`.
    workflow["definitions"]["subgraphs"][0]["links"].append(
        {"id": 15, "origin_id": -10, "origin_slot": 0, "target_id": 1, "target_slot": 0, "type": "FLOAT"}
    )
    workflow["definitions"]["subgraphs"][0]["nodes"][0]["inputs"][0]["link"] = 15
    graph = read(workflow)
    assert graph.nodes["9:1"].inputs["value"] == ["5", 0]


def test_bypassed_nodes_are_read_with_the_mode_the_template_gave_them():
    graph = read(subgraph_workflow())
    assert graph.nodes["9:2"].mode == 4
    assert graph.nodes["9:1"].mode == 0


def test_the_boundary_is_found_even_when_it_is_numbered_differently():
    """`inputNode.id` and the `-10` the links use have disagreed across exports."""
    workflow = subgraph_workflow()
    definition = workflow["definitions"]["subgraphs"][0]
    definition["inputNode"]["id"] = 8000
    definition["outputNode"]["id"] = 8001
    graph = read(workflow)
    assert graph.nodes["9:2"].inputs["scheduler"] == "beta57"
    assert graph.nodes["9:2"].inputs["steps"] == 12


def test_slot_types_travel_with_the_node():
    graph = read(subgraph_workflow())
    node = graph.nodes["9:2"]
    assert node.input_types["model"] == "MODEL"
    assert node.output_types == ("SIGMAS",)


# --- the flat shape still reads --------------------------------------------


def test_a_flat_workflow_reads_as_it_always_did():
    workflow = {
        "nodes": [
            {"id": 1, "type": "PrimitiveFloat", "widgets_values": [24.0]},
            {
                "id": 2,
                "type": "BasicScheduler",
                "widgets_values": ["beta57", 20, 1.0],
                "inputs": [{"name": "model", "link": 7}],
            },
            {"id": 3, "type": "Note", "widgets_values": ["ignore me"]},
        ],
        "links": [[7, 1, 0, 2, 0, "MODEL"]],
    }
    prompt = to_api_prompt(workflow)
    assert set(prompt) == {"1", "2"}
    assert prompt["1"]["inputs"] == {"value": 24.0}
    assert prompt["2"]["inputs"]["model"] == ["1", 0]
    assert prompt["2"]["inputs"]["scheduler"] == "beta57"


def test_a_linked_input_is_never_overwritten_by_a_widget_value():
    workflow = {
        "nodes": [
            {"id": 1, "type": "CM_FloatToInt", "widgets_values": [8]},
            {
                "id": 2,
                "type": "BasicScheduler",
                "widgets_values": ["beta57", 20, 1.0],
                "inputs": [{"name": "steps", "link": 5}],
            },
        ],
        "links": [[5, 1, 0, 2, 1, "INT"]],
    }
    assert to_api_prompt(workflow)["2"]["inputs"]["steps"] == ["1", 0]


def test_a_reroute_is_resolved_away():
    workflow = {
        "nodes": [
            {"id": 1, "type": "PrimitiveFloat", "widgets_values": [3.0]},
            {"id": 2, "type": "Reroute", "inputs": [{"name": "", "link": 1}]},
            {"id": 3, "type": "CM_FloatToInt", "inputs": [{"name": "a", "link": 2}]},
        ],
        "links": [[1, 1, 0, 2, 0, "FLOAT"], [2, 2, 0, 3, 0, "FLOAT"]],
    }
    prompt = to_api_prompt(workflow)
    assert "2" not in prompt
    assert prompt["3"]["inputs"]["a"] == ["1", 0]


def test_video_combine_widgets_are_read_as_a_dict():
    workflow = {
        "nodes": [
            {
                "id": 110,
                "type": "VHS_VideoCombine",
                "widgets_values": {
                    "frame_rate": 24,
                    "filename_prefix": "x",
                    "videopreview": {"noise": True},
                },
            }
        ],
        "links": [],
    }
    prompt = to_api_prompt(workflow)
    assert prompt["110"]["inputs"]["frame_rate"] == 24
    assert "videopreview" not in prompt["110"]["inputs"]


# --- the real templates ----------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_real_templates_expose_their_whole_pipeline(templates, mode):
    graph: Graph = read(templates[mode])
    classes = {node.class_type for node in graph.nodes.values()}
    assert len(graph.nodes) >= 45, f"{mode} read as {len(graph.nodes)} nodes"
    assert "UNETLoader" in classes
    assert "SamplerCustomAdvanced" in classes
    assert "VHS_VideoCombine" in classes
    assert classes & {"MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"}


@pytest.mark.parametrize("mode", MODES)
def test_no_input_of_a_read_template_points_at_a_node_that_is_not_there(templates, mode):
    graph = read(templates[mode])
    for node in graph.nodes.values():
        for name, value in node.inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in graph.nodes, f"{node.id}.{name} -> {value[0]}"


def test_the_turbo_lora_node_is_read_with_the_widgets_the_installed_node_has(templates):
    graph = read(templates["flf2v"])
    lora = next(n for n in graph.nodes.values() if n.class_type == "MiniMaxH3TurboLoRA")
    assert lora.mode == 4  # the template ships it bypassed
    assert "lora_name" in lora.inputs
    assert "strength" in lora.inputs  # not `strength_model`, which the node no longer has


def test_the_configured_seed_reaches_the_noise_node(templates, base_config):
    from h3lab.comfy.graph import apply_config

    prompt = apply_config(
        templates["t2v"],
        base_config.merged(mode="t2v", seed=123456),
        output_tag="seed-check",
    )
    noise = next(node for node in prompt.values() if node["class_type"] == "RandomNoise")
    assert noise["inputs"]["noise_seed"] == 123456
