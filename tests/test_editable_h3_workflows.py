import json
import shutil

import pytest

from h3lab.api.h3_inputs import H3Inputs
from h3lab.comfy.experiment import apply_experiment, experiment_fields, node_roles
from h3lab.comfy.schema import Schemas
from h3lab.comfy.studio import prepare_prompt
from tests.clean_workflow import COMPONENT, SCHEMAS, adapter, build, editor, workflow


@pytest.fixture
def editable(tmp_path):
    directory = tmp_path / "workflows"
    shutil.copytree(COMPONENT / "workflows", directory)
    return directory


def save(directory, graph, preset="quality"):
    (directory / adapter.WORKFLOW_FILES[preset]).write_text(json.dumps(graph), encoding="utf-8")


def test_saved_widget_edits_are_read_each_request_and_not_overridden_by_lab(editable):
    graph = workflow()
    schedule = next(node for node in graph["nodes"] if node["id"] == 114)
    schedule["widgets_values"][1] = 7
    schedule["widgets_values_named"] = {"scheduler": "simple", "steps": 4, "denoise": 1}
    save(editable, graph)

    class Client:
        def prepare_studio(self, workflow, inputs):
            return build(inputs, editable)

    result = prepare_prompt(Client(), {}, H3Inputs(preset="quality", prompt="A test").to_config(), schemas=Schemas(SCHEMAS))
    assert result.prompt["114"]["inputs"]["steps"] == 7
    schedule["widgets_values"][1] = 9
    save(editable, graph)
    assert build({"preset": "quality"}, editable)["workflow"]["114"]["inputs"]["steps"] == 9


def test_added_model_node_survives_empty_experiment(editable):
    graph = workflow()
    edge = next(link for link in graph["links"] if link[1] == 104 and link[3] == 105)
    new_link = graph["last_link_id"] + 1
    graph["links"].append([new_link, 104, 0, 900, 0, "MODEL"])
    for node in graph["nodes"]:
        if node["id"] == 104:
            node["outputs"][0]["links"].remove(edge[0])
            node["outputs"][0]["links"].append(new_link)
    edge[1] = 900
    graph["nodes"].append({"id": 900, "type": "LoraLoaderModelOnly", "mode": 0,
                           "inputs": [{"name": "model", "type": "MODEL", "link": new_link}],
                           "outputs": [{"name": "MODEL", "type": "MODEL", "links": [edge[0]]}],
                           "widgets_values": ["my-lora.safetensors", 0.35], "properties": {}})
    save(editable, graph)
    prepared = build({"preset": "quality"}, editable)["workflow"]
    assert prepared["105"]["inputs"]["model"] == ["900", 0]
    assert prepared["900"]["inputs"]["strength_model"] == 0.35
    assert apply_experiment(prepared, {}) == prepared


def test_bypassed_refinement_stays_bypassed(editable):
    graph = workflow()
    next(node for node in graph["nodes"] if node["id"] == 141)["mode"] = 4
    save(editable, graph)
    prepared = build({"preset": "quality"}, editable)["workflow"]
    assert "141" not in prepared
    assert prepared["117"]["inputs"]["samples"] == ["116", 0]
    assert apply_experiment(prepared, {}) == prepared


def test_request_bindings_and_experiments_survive_node_renumbering(editable):
    graph = workflow("motion")
    for node in graph["nodes"]:
        node["id"] += 1000
    for link in graph["links"]:
        link[1] += 1000
        link[3] += 1000
    save(editable, graph, "motion")
    prepared = build({"preset": "motion", "prompt": "Run", "frames": 90, "seed": 101,
                      "references": {"images": ["hero.png"]}, "guides": [{"image": "first.png", "frame": 0}]}, editable)["workflow"]
    assert prepared["1110"]["inputs"]["prompt"] == "Run"
    assert prepared["1200"]["inputs"]["length"] == 90
    assert prepared["1207"]["inputs"]["noise_seed"] == 102
    assert experiment_fields(prepared)["steps"] == ("1114", "steps")
    changed = apply_experiment(prepared, {"steps": 8, "refine_enabled": False})
    assert changed["1114"]["inputs"]["steps"] == 8
    assert changed["1200"]["inputs"]["samples"] == ["1116", 0]


@pytest.mark.parametrize("preset", list(adapter.PRESETS))
def test_presets_are_flat_and_existing_scene_request_contract_is_preserved(preset):
    graph = workflow(preset)
    assert not graph.get("definitions")
    assert all(node["type"] != "H3CleanWorkflow" for node in graph["nodes"])
    inputs = H3Inputs(preset=preset, prompt="Test", frames=90, seed=31,
                      references={"images": ["a.png"], "videos": ["v.mp4"], "video_audios": ["v.wav"], "audios": ["voice.wav"]},
                      guides=[{"frame": 34, "video": "guide.mp4", "audio": "guide.wav"}],
                      first_frame="first.png", last_frame="last.png", final_audio="song.wav").model_dump(exclude={"experiment"})
    result = build(inputs)
    prompt = result["workflow"]
    assert result["contract_version"] == 1
    assert result["inputs"]["references"] == inputs["references"]
    assert result["dimensions"] == {"width": 1344, "height": 768, "frames": 90, "fps": 24}
    guides = [node for node in prompt.values() if node["class_type"] == "MiniMaxH3AddGuide"]
    assert [node["inputs"]["frame_idx"] for node in guides] == [0, 34, -1]
    roles = node_roles(prompt)
    final_audio = prompt[roles["output_video"]]["inputs"]["audio"]
    assert prompt[final_audio[0]]["inputs"]["audio"] == "song.wav"
    assert Schemas(SCHEMAS).problems(prompt) == []


def test_dynamic_widgets_use_saved_selection_not_stale_named_values():
    graph = workflow()
    sparse = next(node for node in graph["nodes"] if node["type"] == "BlockSparseAttention")
    sparse["widgets_values"][0:2] = ["Sol-Attn (adaptive tau)", 1.7]
    sparse["widgets_values_named"] = {"selection": "VSA (FastVideo)", "selection.keep_percent": 10}
    prompt = editor.to_prompt(graph, SCHEMAS.__getitem__)
    assert prompt[str(sparse["id"])]["inputs"]["selection.tau"] == 1.7
    assert "selection.keep_percent" not in prompt[str(sparse["id"])]["inputs"]
