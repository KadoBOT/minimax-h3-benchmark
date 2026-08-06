from bench.constants import (
    BASELINE_PROMPT,
    INT8_UNET,
    NODE_CLEAN_VRAM,
    NODE_EASYCACHE,
    NODE_H3_CACHE,
    NODE_INT8,
    NODE_PROMPT,
    NODE_SAGE,
    NODE_SOL_ATTN,
    NODE_SPECTRUM,
    NODE_UNET,
    NVFP4_UNET,
    WORKFLOW_PATH,
)
from bench.models import RunConfig
from bench.workflow import apply_config, load_ui_workflow, ui_to_api_prompt


def test_ui_to_api_has_core_nodes():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = ui_to_api_prompt(ui)
    assert str(NODE_UNET) in api
    assert str(NODE_PROMPT) in api
    assert api[str(NODE_PROMPT)]["class_type"] == "PrimitiveStringMultiline"
    assert api[str(NODE_UNET)]["class_type"] == "UNETLoader"
    # Linked model path present in full conversion
    assert api[str(NODE_SAGE)]["inputs"]["model"][0] in {
        str(NODE_UNET),
        str(NODE_INT8),
        "126",
    }


def test_easy_cache_only_in_graph():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache="easy"))
    assert str(NODE_EASYCACHE) in api
    assert str(NODE_SPECTRUM) not in api
    assert str(NODE_H3_CACHE) not in api
    assert str(NODE_CLEAN_VRAM) not in api
    # EasyCache model should come from sigma shift chain
    assert api[str(NODE_EASYCACHE)]["inputs"]["model"][0] == "123"


def test_no_cache_omits_all_three_caches():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache="none", quant="nvfp4", sol_attn=True))
    assert str(NODE_EASYCACHE) not in api
    assert str(NODE_SPECTRUM) not in api
    assert str(NODE_H3_CACHE) not in api
    # Scheduler/guider model should come from sigma shift directly
    assert api["6"]["inputs"]["model"][0] == "123"
    assert api["8"]["inputs"]["model"][0] == "123"


def test_int8_vs_nvfp4_modes():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(quant="int8"))
    assert str(NODE_INT8) in api
    assert str(NODE_UNET) not in api
    assert api[str(NODE_INT8)]["inputs"]["unet_name"] == INT8_UNET
    assert api[str(NODE_SAGE)]["inputs"]["model"][0] == str(NODE_INT8)

    api2 = apply_config(ui, RunConfig(quant="nvfp4"))
    assert str(NODE_UNET) in api2
    assert str(NODE_INT8) not in api2
    assert api2[str(NODE_UNET)]["inputs"]["unet_name"] == NVFP4_UNET
    assert api2[str(NODE_SAGE)]["inputs"]["model"][0] == str(NODE_UNET)


def test_sol_attn_off_omits_sol():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(sol_attn=False))
    assert str(NODE_SOL_ATTN) not in api
    # Sigma shift should take model from sage when sol is off
    assert api["123"]["inputs"]["model"][0] == str(NODE_SAGE)


def test_prompt_is_timestamp_free():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig())
    val = api[str(NODE_PROMPT)]["inputs"]["value"]
    assert val == BASELINE_PROMPT
    assert "0:00" not in val


def test_clean_vram_omitted():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig())
    assert str(NODE_CLEAN_VRAM) not in api
    assert "96" not in api  # RIFE
    assert "111" not in api  # upscaler
    assert "126" not in api  # quant switch
    assert "127" not in api  # cache switch
    # Video path rewired: decode samples from sampler, combine images from decode
    assert api["125"]["inputs"]["samples"][0] == "10"
    assert api["110"]["inputs"]["images"][0] == "125"
