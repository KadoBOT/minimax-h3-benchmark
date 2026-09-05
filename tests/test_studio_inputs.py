from __future__ import annotations

import json

from h3lab.comfy.form import studio_bindings
from h3lab.comfy.studio import studio_inputs, studio_patch
from h3lab.domain.config import GenerationConfig, config_attention, config_hash


def test_config_projects_complete_component_inputs(base_config):
    inputs = studio_inputs(base_config)
    assert inputs["mode"] == "FLF2V"
    assert inputs["prompt"] == base_config.prompt
    assert inputs["duration"] == base_config.duration_s
    assert inputs["megapixels"] == base_config.mp
    assert inputs["sampler_name"] == base_config.sampler
    assert inputs["interpolation"] == "none"
    assert inputs["upscale_rtx"] is False
    assert inputs["cache"] is True
    assert inputs["sol_attn"] is True
    assert inputs["turbo_lora_strength"] == base_config.turbo_lora_strength
    assert "attn" not in inputs


def test_complete_inputs_become_a_minimal_config_patch(base_config):
    inputs = studio_inputs(base_config)
    inputs.update(
        {
            "duration": 7.5,
            "megapixels": 0.8,
            "sampler_name": "heun",
            "interpolation": "film",
            "upscale_rtx": True,
            "turbo_lora_strength": 0.6,
        }
    )
    patch = studio_patch(base_config, inputs)
    assert patch == {
        "duration_s": 7.5,
        "mp": 0.8,
        "sampler": "heun",
        "interp": "film",
        "upscaler": True,
        "turbo_lora_strength": 0.6,
    }


def test_unknown_future_fields_round_trip_through_widgets(base_config):
    inputs = studio_inputs(base_config)
    inputs["future_widget"] = {"amount": 7}
    updated = base_config.merged(**studio_patch(base_config, inputs))
    assert updated.widgets["future_widget"] == {"amount": 7}
    assert studio_inputs(updated)["future_widget"] == {"amount": 7}


def test_experimental_runtime_fields_are_sweepable(base_config):
    updated = base_config.merged(
        use_trt_vae=True,
        trt_vae_decoder="minimax_h3_vae_decoder.engine",
        trt_vae_encoder="minimax_h3_vae_encoder.engine",
        use_vdn=True,
        vdn_checkpoint="stage-dmd-step-250",
        vdn_apply_turbo_adapter=True,
        vdn_strength=1.0,
        vdn_lora_mode="merge",
        vdn_branch_weights="stream",
        vdn_attention_backend="grouped",
        vdn_verbose=False,
    )

    inputs = studio_inputs(updated)
    assert inputs["use_trt_vae"] is True
    assert inputs["trt_vae_decoder"] == "minimax_h3_vae_decoder.engine"
    assert inputs["use_vdn"] is True
    assert inputs["vdn_checkpoint"] == "stage-dmd-step-250"
    assert inputs["vdn_lora_mode"] == "merge"


def test_attention_projects_to_legacy_field_and_explicit_widget(base_config):
    for attention, legacy in (("sol", True), ("off", False), ("comfy_kitchen", False)):
        inputs = studio_inputs(base_config)
        inputs["attn"] = attention
        updated = base_config.merged(**studio_patch(base_config, inputs))
        assert updated.sol_attn is legacy
        assert updated.widgets["attn"] == attention
        assert config_attention(updated) == attention


def test_historical_attention_is_emitted_without_becoming_explicit():
    sol = GenerationConfig(mode="t2v", prompt="legacy", sol_attn=True)
    off = GenerationConfig(mode="t2v", prompt="legacy", sol_attn=False)
    assert studio_inputs(sol)["sol_attn"] is True
    assert studio_inputs(off)["sol_attn"] is False
    assert "attn" not in studio_inputs(sol)
    assert config_attention(sol) == "sol"
    assert config_attention(off) == "off"


def test_legacy_attention_hashes_stay_stable():
    assert config_hash(
        GenerationConfig(mode="t2v", prompt="legacy", sol_attn=True)
    ) == "cdaa0882d03e96fac382f63824619f24"
    assert config_hash(
        GenerationConfig(mode="t2v", prompt="legacy", sol_attn=False)
    ) == "45b91f625bd839e7be0744648777514b"


def test_explicit_legacy_equivalents_share_hash_but_kitchen_is_distinct():
    sol = GenerationConfig(mode="t2v", prompt="legacy", sol_attn=True)
    off = GenerationConfig(mode="t2v", prompt="legacy", sol_attn=False)
    explicit_sol = GenerationConfig(
        mode="t2v", prompt="legacy", widgets={"attn": "sol"}, sol_attn=True
    )
    explicit_off = GenerationConfig(
        mode="t2v", prompt="legacy", widgets={"attn": "off"}, sol_attn=False
    )
    kitchen = GenerationConfig(
        mode="t2v",
        prompt="legacy",
        widgets={"attn": "comfy_kitchen"},
        sol_attn=False,
    )
    assert config_hash(explicit_sol) == config_hash(sol)
    assert config_hash(explicit_off) == config_hash(off)
    assert config_hash(kitchen) not in {config_hash(sol), config_hash(off)}


def test_references_round_trip_all_arrays():
    config = GenerationConfig(
        mode="r2v",
        prompt="references",
        ref_images=["image.png"],
        ref_videos=["video.mp4"],
        ref_video_audios=["video.wav"],
        ref_audios=["audio.wav"],
    )
    inputs = studio_inputs(config)
    assert json.loads(inputs["references"]) == {
        "images": ["image.png"],
        "videos": ["video.mp4"],
        "video_audios": ["video.wav"],
        "audios": ["audio.wav"],
    }
    assert studio_patch(config, inputs) == {}


def test_enabling_cache_from_historical_none_selects_spectrum():
    off = GenerationConfig(mode="t2v", prompt="cache", cache="none")
    inputs = studio_inputs(off)
    assert inputs["cache"] is False
    inputs["cache"] = True
    updated = off.merged(**studio_patch(off, inputs))
    assert updated.cache_enabled is True
    assert updated.cache == "spectrum"
    assert "cache" not in updated.widgets


def test_bindings_only_describe_unavoidable_persistence_projections():
    bindings = studio_bindings()
    assert bindings["duration"] == {"key": "duration_s", "store": "config"}
    assert bindings["mode"]["values"]["FLF2V"] == "flf2v"
    assert bindings["references"]["store"] == "references"
    assert "prompt" not in bindings
