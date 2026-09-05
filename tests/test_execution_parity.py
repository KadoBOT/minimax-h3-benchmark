from __future__ import annotations

from collections import Counter

import pytest

from h3lab.comfy.graph import load_workflow, missing_links
from h3lab.comfy.presets import SOL, SPECTRUM
from h3lab.comfy.schema import static_schemas
from h3lab.comfy.studio import prepare_prompt
from h3lab.domain.config import GenerationConfig
from tests.conftest import unified_workflow_path


def _config(**overrides) -> GenerationConfig:
    values = {
        "mode": "t2v",
        "diffusion_model": "minimax-h3/parity-model.safetensors",
        "prompt": "configuration parity",
        "seed": 42,
    }
    values.update(overrides)
    return GenerationConfig(**values)


def _prepare(stub, config: GenerationConfig):
    return prepare_prompt(
        stub,
        load_workflow(unified_workflow_path()),
        config,
        schemas=static_schemas(),
    ).prompt


def _nodes(prompt, class_type: str):
    return [node for node in prompt.values() if node["class_type"] == class_type]


def test_benchmark_only_values_reach_the_nodes_that_execute_them(stub):
    config = _config(
        turbo=True,
        turbo_lora="minimax-h3/custom_8step.safetensors",
        turbo_lora_strength=0.65,
        cache_preset="aggressive",
        sol_preset="aggressive",
        widgets={"attn": "sol"},
    )
    prompt = _prepare(stub, config)

    studio_id, studio = next(
        (node_id, node)
        for node_id, node in prompt.items()
        if node["class_type"] == "MiniMaxH3Studio"
    )
    model_nodes = (
        _nodes(prompt, "UNETLoader")
        or _nodes(prompt, "MiniMaxH3HybridLoader")
        or _nodes(prompt, "MiniMaxH3ModelLoader")
    )
    model = model_nodes[0]["inputs"]
    if "hybrid_model_name" in model:
        assert model["hybrid_model_name"] == [studio_id, 38]
    else:
        assert (model.get("unet_name") or model.get("base_model")) == (
            "minimax-h3/parity-model.safetensors"
        )
    turbo = _nodes(prompt, "MiniMaxH3TurboLoRA")[0]["inputs"]
    assert turbo["lora_name"] == [studio_id, 10]
    assert studio["inputs"]["turbo_lora"] == "minimax-h3/custom_8step.safetensors"
    assert turbo["strength"] == 0.65
    cache = _nodes(prompt, "SpectrumApplyMiniMaxH3")[0]["inputs"]
    assert cache["enabled"] == [studio_id, 11]
    for name, value in SPECTRUM["aggressive"].items():
        if name != "enabled":
            assert cache[name] == value
    assert _nodes(prompt, "SolAttnPatch")[0]["inputs"].items() >= SOL["aggressive"].items()


@pytest.mark.parametrize(
    ("mode", "sol", "kitchen"),
    [
        ("off", 0, 0),
        ("sol", 1, 0),
        ("comfy_kitchen", 0, 1),
    ],
)
def test_attention_choice_selects_exactly_one_requested_backend(stub, mode, sol, kitchen):
    prompt = _prepare(stub, _config(widgets={"attn": mode}))
    classes = Counter(node["class_type"] for node in prompt.values())

    assert classes["SolAttnPatch"] == sol
    assert classes["ModelAttentionBackend"] == kitchen
    assert missing_links(prompt) == []


@pytest.mark.parametrize(
    ("interpolation", "expected", "fps"),
    [
        ("off", None, 24),
        ("film", "FrameInterpolate", 48),
        ("rife", "RIFEInterpolation", 120),
        ("gmfss", "GMFSS Fortuna VFI", 96),
    ],
)
def test_interpolation_choice_reaches_the_image_path(stub, interpolation, expected, fps):
    prompt = _prepare(stub, _config(interp=interpolation))
    classes = Counter(node["class_type"] for node in prompt.values())
    interpolation_classes = {
        "FrameInterpolate",
        "RIFEInterpolation",
        "GMFSS Fortuna VFI",
    }

    assert {name for name in interpolation_classes if classes[name]} == (
        {expected} if expected else set()
    )
    assert _nodes(prompt, "VHS_VideoCombine")[0]["inputs"]["frame_rate"] == fps
    assert missing_links(prompt) == []


@pytest.mark.parametrize("enabled", [False, True])
def test_rtx_upscale_choice_reaches_the_image_path(stub, enabled):
    prompt = _prepare(stub, _config(upscaler=enabled))
    assert bool(_nodes(prompt, "RTXVideoSuperResolution")) is enabled
    assert missing_links(prompt) == []


@pytest.mark.parametrize("enabled", [False, True])
def test_clean_vram_choice_controls_every_tagged_cleanup(stub, enabled):
    prompt = _prepare(stub, _config(clean_vram=enabled))
    cleanups = [
        node
        for node in prompt.values()
        if "[h3s:clean-vram]" in str(node.get("_meta", {}).get("title", "")).lower()
    ]
    assert bool(cleanups) is enabled
    assert missing_links(prompt) == []


@pytest.mark.parametrize(
    ("widget", "class_type"),
    [
        ("post_grade", "MSFastPostGrade"),
        ("upscale_ltx", "LTXVTiledVAEDecode"),
    ],
)
def test_template_only_image_features_reach_the_image_path(stub, widget, class_type):
    off = _prepare(stub, _config(widgets={widget: False}))
    on = _prepare(stub, _config(widgets={widget: True}))

    assert not _nodes(off, class_type)
    assert _nodes(on, class_type)
    assert missing_links(on) == []


def test_derope_keeps_its_internal_audio_source_but_not_muxed_audio(stub):
    prompt = _prepare(stub, _config(widgets={"derope": True}))
    smear = _nodes(prompt, "H3AudioSmear")[0]
    source_id = smear["inputs"]["audio"][0]
    source = prompt[source_id]
    video = _nodes(prompt, "VHS_VideoCombine")[0]

    assert source["inputs"]
    assert _nodes(prompt, "VAEDecodeAudio")
    assert "audio" not in video["inputs"]
    assert missing_links(prompt) == []


def test_derope_final_pass_inherits_studio_sampling_and_reanchors_guides(stub):
    prompt = _prepare(
        stub,
        _config(
            steps=28,
            seed=123,
            scheduler="beta57",
            sampler="euler",
            widgets={
                "derope": True,
                "guides": '[{"time":1.0,"image":"guide.png"}]',
                "er_sde": True,
                "er_sde_solver": "ODE",
                "er_sde_max_stage": 2,
                "er_sde_eta": 0.25,
                "er_sde_s_noise": 0.75,
            },
        ),
    )
    studio_id = next(
        node_id
        for node_id, node in prompt.items()
        if node["class_type"] == "MiniMaxH3Studio"
    )
    schedule_id, schedule = next(
        (node_id, node)
        for node_id, node in prompt.items()
        if node["class_type"] == "H3InjectSchedule"
    )
    sampler = next(
        node
        for node in _nodes(prompt, "SamplerCustomAdvanced")
        if node["inputs"]["sigmas"] == [schedule_id, 0]
    )

    assert schedule["inputs"]["scheduler"] == [studio_id, 8]
    assert schedule["inputs"]["total_steps"] == [studio_id, 6]
    assert schedule["inputs"]["inject"] == 0.5

    noise = prompt[sampler["inputs"]["noise"][0]]
    assert noise["inputs"]["noise_seed"] == [studio_id, 7]

    sampler_switch = prompt[sampler["inputs"]["sampler"][0]]
    assert sampler_switch["_meta"]["title"] == "DEROPE_ER_SDE_GATE"
    assert sampler_switch["inputs"]["switch"] == [studio_id, 27]
    ordinary = prompt[sampler_switch["inputs"]["on_false"][0]]
    er_sde = prompt[sampler_switch["inputs"]["on_true"][0]]
    assert ordinary["inputs"]["sampler_name"] == [studio_id, 9]
    assert er_sde["inputs"] == {
        "solver_type": [studio_id, 28],
        "max_stage": [studio_id, 29],
        "eta": [studio_id, 30],
        "s_noise": [studio_id, 31],
    }

    guider = prompt[sampler["inputs"]["guider"][0]]
    anchor = prompt[guider["inputs"]["conditioning"][0]]
    smear_id, _smear = next(
        (node_id, node)
        for node_id, node in prompt.items()
        if node["class_type"] == "H3TimeSmear"
    )
    assert anchor["class_type"] == "MiniMaxH3AnchorGuides"
    assert anchor["inputs"]["positive"] == [studio_id, 14]
    assert anchor["inputs"]["guides"] == [studio_id, 15]
    assert anchor["inputs"]["length"] == [smear_id, 2]
    assert anchor["inputs"]["hold_map"] == [smear_id, 1]
    assert anchor["inputs"]["latent"] == sampler["inputs"]["latent_image"]
    assert prompt[anchor["inputs"]["latent"][0]]["class_type"] == "H3V2VInit"
    assert missing_links(prompt) == []


def test_every_studio_output_driven_parameter_stays_connected(stub):
    config = _config(
        steps=28,
        scheduler="beta57",
        sampler="euler",
        widgets={
            "shift_video": 13.0,
            "shift_audio": 2.5,
            "derope": False,
            "sla": True,
            "sla_sparsity": 0.85,
            "sla_block_size": "128",
            "sla_dense_last_steps": 2,
            "sla_protect_audio": False,
            "sla_stabilize_motion": False,
            "adaln": "port",
            "fp16_accum": True,
            "er_sde": True,
            "er_sde_solver": "ODE",
            "er_sde_max_stage": 2,
            "er_sde_eta": 0.7,
            "er_sde_s_noise": 1.2,
        },
    )
    prompt = _prepare(stub, config)
    studio_id, studio = next(
        (node_id, node)
        for node_id, node in prompt.items()
        if node["class_type"] == "MiniMaxH3Studio"
    )
    expected_inputs = {
        "steps": 28,
        "scheduler": "beta57",
        "sampler_name": "euler",
        "shift_video": 13.0,
        "shift_audio": 2.5,
        "derope": False,
        "sla": True,
        "sla_sparsity": 0.85,
        "sla_block_size": "128",
        "sla_dense_last_steps": 2,
        "sla_protect_audio": False,
        "sla_stabilize_motion": False,
        "adaln": "port",
        "fp16_accum": True,
        "er_sde": True,
        "er_sde_solver": "ODE",
        "er_sde_max_stage": 2,
        "er_sde_eta": 0.7,
        "er_sde_s_noise": 1.2,
    }
    output_slots = {
        "steps": 6,
        "scheduler": 8,
        "sampler_name": 9,
        "shift_video": 13,
        "shift_audio": 16,
        "derope": 17,
        "sla": 18,
        "sla_sparsity": 19,
        "sla_block_size": 20,
        "sla_dense_last_steps": 21,
        "sla_protect_audio": 22,
        "sla_stabilize_motion": 23,
        "adaln": 25,
        "fp16_accum": 26,
        "er_sde": 27,
        "er_sde_solver": 28,
        "er_sde_max_stage": 29,
        "er_sde_eta": 30,
        "er_sde_s_noise": 31,
    }

    assert studio["inputs"].items() >= expected_inputs.items()
    links = {
        tuple(value)
        for node in prompt.values()
        for value in node.get("inputs", {}).values()
        if isinstance(value, list) and len(value) == 2
    }
    for name, slot in output_slots.items():
        assert (studio_id, slot) in links, f"{name} is not connected to an executing node"
    derope_gate = next(
        node
        for node in (
            _nodes(prompt, "MiniMaxH3OptionalSwitch")
            + _nodes(prompt, "ComfySwitchNode")
        )
        if node.get("_meta", {}).get("title") == "DEROPE_GATE H3ExactRecover"
    )
    assert derope_gate["inputs"]["switch"] == [studio_id, 17]
    assert (
        prompt[derope_gate["inputs"]["on_false"][0]]["class_type"] != "H3ExactRecover"
    )
    assert (
        prompt[derope_gate["inputs"]["on_true"][0]]["class_type"] == "H3ExactRecover"
    )
