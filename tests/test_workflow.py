from bench.constants import (
    BASELINE_PROMPT,
    NODE_CLIP_GGUF,
    NODE_EASYCACHE,
    NODE_GGUF,
    NODE_H3_CACHE,
    NODE_I2V,
    NODE_INT8,
    NODE_PROMPT,
    NODE_RIFE,
    NODE_SAGE,
    NODE_SAMPLER,
    NODE_SCHEDULER,
    NODE_SEED,
    NODE_SOL_ATTN,
    NODE_SPECTRUM,
    NODE_TURBO_LORA,
    NODE_UNET,
    NODE_UPSCALER,
    WORKFLOW_PATH,
)
from bench.models import RunConfig
from bench.workflow import apply_config, load_ui_workflow, ui_to_api_prompt


def test_ui_skips_rgthree_bypassers():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = ui_to_api_prompt(ui)
    types = {n["class_type"] for n in api.values()}
    assert "Fast Groups Bypasser (rgthree)" not in types
    assert "Fast Bypasser (rgthree)" not in types


def test_gguf_omits_safetensor_loaders():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(model_path="gguf"))
    assert str(NODE_GGUF) in api
    assert str(NODE_UNET) not in api
    assert str(NODE_INT8) not in api
    assert str(NODE_CLIP_GGUF) in api
    assert api[str(NODE_I2V)]["inputs"]["clip"][0] == str(NODE_CLIP_GGUF)


def test_first_frame_sets_load_image_and_strips_last_frame():
    from bench.constants import DEFAULT_FIRST_FRAME, NODE_LAST_FRAME, NODE_LOAD_IMAGE

    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(first_frame=DEFAULT_FIRST_FRAME))
    assert api[str(NODE_LOAD_IMAGE)]["inputs"]["image"] == DEFAULT_FIRST_FRAME
    assert str(NODE_LAST_FRAME) not in api
    assert "last_frame" not in api[str(NODE_I2V)]["inputs"]
    # Custom upload basename
    api2 = apply_config(ui, RunConfig(first_frame="my_upload.png"))
    assert api2[str(NODE_LOAD_IMAGE)]["inputs"]["image"] == "my_upload.png"


def test_bench_prompt_omits_incomplete_save_outputs():
    """Secondary SaveImage/SaveAudio/last-frame helpers must not enter the prompt.

    Leaving them half-wired made Comfy fail validation (missing images /
    filename_prefix) even when the main VHS path was fine.
    """
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig())
    types = {n["class_type"] for n in api.values()}
    assert "SaveImage" not in types
    assert "SaveAudio" not in types
    assert "ImageFromBatch" not in types
    # Primary video path present and complete
    assert "VHS_VideoCombine" in types
    vc = next(n for n in api.values() if n["class_type"] == "VHS_VideoCombine")
    assert "images" in vc["inputs"]
    assert "filename_prefix" in vc["inputs"]
    # Video-only: no audio mux (NaN audio latents crash ffmpeg AAC)
    assert "audio" not in vc["inputs"]
    assert "VAEDecodeAudio" not in types
    # I2V first-frame only
    assert "first_frame" in api[str(NODE_I2V)]["inputs"]
    assert "last_frame" not in api[str(NODE_I2V)]["inputs"]


def test_safetensor_always_uses_unet_loader():
    """int8 quant flag no longer selects OTUNet — always UNETLoader for safetensors."""
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(model_path="safetensor", quant="int8"))
    assert str(NODE_UNET) in api and str(NODE_INT8) not in api
    api2 = apply_config(ui, RunConfig(model_path="safetensor", quant="nvfp4"))
    assert str(NODE_UNET) in api2 and str(NODE_INT8) not in api2


def test_single_cache_spectrum():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache_enabled=True, cache="spectrum"))
    assert str(NODE_SPECTRUM) in api
    assert str(NODE_EASYCACHE) not in api
    assert str(NODE_H3_CACHE) not in api


def test_cache_off_omits_all():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache_enabled=False))
    assert str(NODE_SPECTRUM) not in api
    assert str(NODE_EASYCACHE) not in api
    assert str(NODE_H3_CACHE) not in api


def test_sol_off_uses_sage_only():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(sol_attn=False))
    assert str(NODE_SOL_ATTN) not in api
    assert str(NODE_SAGE) in api
    # Sigma shift should take model from sage when sol is off
    assert api["123"]["inputs"]["model"][0] == str(NODE_SAGE)


def test_turbo_includes_turbo_lora_and_steps():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(turbo=True, steps=20))
    assert str(NODE_TURBO_LORA) in api
    assert api[str(NODE_SCHEDULER)]["inputs"]["steps"] == 4


def test_rife_upscaler_optional():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(rife=False, upscaler=False))
    assert str(NODE_RIFE) not in api
    assert str(NODE_UPSCALER) not in api
    api2 = apply_config(ui, RunConfig(rife=True, upscaler=True))
    assert str(NODE_RIFE) in api2
    assert str(NODE_UPSCALER) in api2


def test_scheduler_sampler_seed():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(
        ui, RunConfig(scheduler="simple", sampler="euler", seed=42, steps=18)
    )
    assert api[str(NODE_SCHEDULER)]["inputs"]["scheduler"] == "simple"
    assert api[str(NODE_SCHEDULER)]["inputs"]["steps"] == 18
    assert api[str(NODE_SAMPLER)]["inputs"]["sampler_name"] == "euler"
    assert api[str(NODE_SEED)]["inputs"]["seed"] == 42


def test_prompt_baseline_set():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig())
    val = api[str(NODE_PROMPT)]["inputs"]["value"]
    assert val == BASELINE_PROMPT
    assert "0:00" not in val


def test_prompt_and_aspect_ratio_overrides():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(
        ui,
        RunConfig(
            prompt="A cat jumps onto a table.",
            aspect_ratio="9:16 (Portrait Widescreen)",
            mp=0.6,
        ),
    )
    assert api[str(NODE_PROMPT)]["inputs"]["value"] == "A cat jumps onto a table."
    assert api["98"]["inputs"]["aspect_ratio"] == "9:16 (Portrait Widescreen)"
    assert api["98"]["inputs"]["megapixels"] == 0.6


def test_output_tag_sets_unique_filename_prefix():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(), output_tag="speed_001_timed")
    prefix = api["110"]["inputs"]["filename_prefix"]
    assert "speed_001_timed" in prefix
    assert prefix.startswith("bench/")


def test_sol_on_stacks_sage_after_sol():
    """Working Comfy exports chain Sol → Sage → Sigma (not Sol alone)."""
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(sol_attn=True))
    assert str(NODE_SOL_ATTN) in api
    assert str(NODE_SAGE) in api
    assert api[str(NODE_SAGE)]["inputs"]["model"][0] == str(NODE_SOL_ATTN)
    assert api["123"]["inputs"]["model"][0] == str(NODE_SAGE)


def test_int4q_uses_unet_loader_not_otu():
    ui = load_ui_workflow(WORKFLOW_PATH)
    name = "minimax_h3_fl2va_pruned_INT4Q.safetensors"
    api = apply_config(ui, RunConfig(diffusion_model=name))
    assert str(NODE_UNET) in api
    assert str(NODE_INT8) not in api
    assert api[str(NODE_UNET)]["inputs"]["unet_name"] == name
