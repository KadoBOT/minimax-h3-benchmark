from pathlib import Path

from bench.diffusion_models import (
    default_diffusion_model,
    infer_loader,
    is_minimax_h3_model,
    list_diffusion_models,
    resolve_model_filename,
)
from bench.models import RunConfig
from bench.constants import (
    GGUF_UNET,
    INT8_UNET,
    NODE_GGUF,
    NODE_INT8,
    NODE_UNET,
    NVFP4_UNET,
    WORKFLOW_PATH,
)
from bench.workflow import apply_config, load_ui_workflow


def test_is_minimax_h3_filter():
    assert is_minimax_h3_model("minimax_h3_fl2va_pruned_nvfp4.safetensors")
    assert is_minimax_h3_model("MiniMax-H3-FL2VA-Q4_K_M.gguf")
    assert not is_minimax_h3_model("sdxl_base.safetensors")
    assert not is_minimax_h3_model("minimax_only.safetensors")
    assert not is_minimax_h3_model("h3_only.safetensors")


def test_list_diffusion_models_scans_dir(tmp_path):
    (tmp_path / "minimax_h3_a.safetensors").write_bytes(b"x")
    (tmp_path / "MiniMax-H3-B.gguf").write_bytes(b"x")
    (tmp_path / "other.safetensors").write_bytes(b"x")
    (tmp_path / "minimax_nope.safetensors").write_bytes(b"x")
    (tmp_path / "readme.txt").write_text("no")
    names = list_diffusion_models(tmp_path)
    assert names == ["MiniMax-H3-B.gguf", "minimax_h3_a.safetensors"] or set(names) == {
        "MiniMax-H3-B.gguf",
        "minimax_h3_a.safetensors",
    }
    assert "other.safetensors" not in names


def test_list_missing_dir():
    assert list_diffusion_models(Path("/nonexistent/diffusion_models_xyz")) == []


def test_infer_loader():
    assert infer_loader("MiniMax-H3-FL2VA-Q4_K_M.gguf") == ("gguf", "nvfp4")
    assert infer_loader("minimax_h3_fl2va_pruned_nvfp4.safetensors") == (
        "safetensor",
        "nvfp4",
    )
    # All safetensors use UNETLoader path (quant=nvfp4), including int8/convrot packs
    assert infer_loader("minimax_h3_fl2va_pruned_int8_convrot.safetensors") == (
        "safetensor",
        "nvfp4",
    )
    assert infer_loader("minimax_h3_fl2va_pruned_int4_convrot.safetensors") == (
        "safetensor",
        "nvfp4",
    )
    assert infer_loader("MiniMax_H3_FL2VA_pruned_mixed_int4_int8_convrot.safetensors") == (
        "safetensor",
        "nvfp4",
    )
    assert infer_loader("minimax_h3_fl2va_pruned_INT4Q.safetensors") == (
        "safetensor",
        "nvfp4",
    )


def test_runconfig_aligns_path_from_diffusion_model():
    c = RunConfig(diffusion_model="MiniMax-H3-REF2VA-Q4_K_M.gguf")
    assert c.model_path == "gguf"
    c2 = RunConfig(diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors")
    assert c2.model_path == "safetensor" and c2.quant == "nvfp4"


def test_resolve_model_filename():
    assert (
        resolve_model_filename("custom_minimax_h3.safetensors", "safetensor", "nvfp4")
        == "custom_minimax_h3.safetensors"
    )
    assert resolve_model_filename("", "gguf", "nvfp4") == GGUF_UNET
    assert resolve_model_filename("", "safetensor", "int8") == NVFP4_UNET
    assert resolve_model_filename("", "safetensor", "nvfp4") == NVFP4_UNET


def test_apply_config_uses_diffusion_model_filename():
    ui = load_ui_workflow(WORKFLOW_PATH)
    name = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
    api = apply_config(ui, RunConfig(diffusion_model=name))
    assert str(NODE_UNET) in api
    assert str(NODE_INT8) not in api
    assert api[str(NODE_UNET)]["inputs"]["unet_name"] == name

    name_i = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    api2 = apply_config(ui, RunConfig(diffusion_model=name_i))
    assert str(NODE_UNET) in api2
    assert str(NODE_INT8) not in api2
    assert api2[str(NODE_UNET)]["inputs"]["unet_name"] == name_i

    name_g = "MiniMax-H3-FL2VA-Q4_K_M.gguf"
    api3 = apply_config(ui, RunConfig(diffusion_model=name_g))
    assert str(NODE_GGUF) in api3
    assert api3[str(NODE_GGUF)]["inputs"]["model_name"] == name_g


def test_default_diffusion_model_prefers_nvfp4():
    names = [
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "minimax_h3_fl2va_pruned_nvfp4.safetensors",
        "MiniMax-H3-FL2VA-Q4_K_M.gguf",
    ]
    assert default_diffusion_model(names) == "minimax_h3_fl2va_pruned_nvfp4.safetensors"
