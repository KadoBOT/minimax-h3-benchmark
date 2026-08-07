"""UI workflow → ComfyUI API prompt conversion and RunConfig mutation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from bench.constants import (
    BASELINE_PROMPT,
    GGUF_CLIP,
    GGUF_UNET,
    INT8_UNET,
    NODE_ATTN_SWITCH,
    NODE_BASE_FPS,
    NODE_CLEAN_TE,
    NODE_CLEAN_VRAM,
    NODE_CLIP,
    NODE_CLIP_GGUF,
    NODE_CLIP_SWITCH,
    NODE_DEFAULT_STEPS,
    NODE_DURATION,
    NODE_EASYCACHE,
    NODE_FLOAT_TO_INT,
    NODE_FPS_SWITCH,
    NODE_GGUF,
    NODE_GUIDER,
    NODE_H3_CACHE,
    NODE_FIT_FIRST,
    NODE_FIT_LAST,
    NODE_I2V,
    NODE_INT8,
    NODE_INTERP_FPS,
    NODE_LAST_FRAME,
    NODE_LOAD_IMAGE,
    NODE_MODEL_SWITCH,
    NODE_NOISE,
    NODE_OPTIONAL_LORA,
    NODE_PROMPT,
    DEFAULT_FIRST_FRAME,
    NODE_RESOLUTION,
    NODE_RIFE,
    NODE_SAGE,
    NODE_SAMPLER,
    NODE_SAMPLER_ADV,
    NODE_SCHEDULER,
    NODE_SEED,
    NODE_SIGMA_SHIFT,
    NODE_SOL_ATTN,
    NODE_SPECTRUM,
    NODE_STEPS_SWITCH,
    NODE_SWITCH_CACHE,
    NODE_SWITCH_QUANT,
    NODE_TURBO_LORA,
    NODE_TURBO_STEPS,
    NODE_UNET,
    NODE_UPSCALER,
    NODE_VAE_AUDIO,
    NODE_VAE_DECODE,
    NODE_VAE_DECODE_AUDIO,
    NODE_VIDEO_COMBINE,
    NVFP4_UNET,
)
from bench.models import RunConfig
from bench.presets import expand_presets

TURBO_STEPS_DEFAULT = 4

# Secondary / UI helper nodes not needed in the API prompt (bench only needs
# the primary VHS_VideoCombine). Including them without full wiring makes Comfy
# reject the prompt (missing images/filename_prefix) and can hard-crash.
NODE_SECONDARY_COMBINE = 150
NODE_IMAGE_FROM_BATCH = 152
NODE_SAVE_AUDIO = 149
NODE_LAST_FRAME_INDEX = 151
NODE_SAVE_LAST_FRAME = 153

# Node types that exist only in the UI graph (no executable class_type).
UI_ONLY_TYPES = frozenset(
    {
        "Note",
        "Fast Groups Bypasser (rgthree)",
        "Fast Bypasser (rgthree)",
        "Reroute",
    }
)

# Widget name order matching widgets_values for nodes we convert offline.
# control_after_generate / seed_mode entries are UI-only and omitted here.
WIDGET_MAP: dict[str, list[str] | None] = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "OTUNetLoaderW8A8": [
        "unet_name",
        "weight_dtype",
        "model_type",
        "on_the_fly_quantization",
        "enable_convrot",
        "lora_mode",
    ],
    "GGUFLoaderKJ": [
        "model_name",
        "extra_model_name",
        "dequant_dtype",
        "patch_dtype",
        "patch_on_device",
        "enable_fp16_accumulation",
        "attention_override",
    ],
    "CLIPLoader": ["clip_name", "type", "device"],
    "CLIPLoaderGGUF": ["clip_name", "type"],
    "VAELoader": ["vae_name"],
    "LoadImage": ["image"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "KSamplerSelect": ["sampler_name"],
    "EasyCache": ["reuse_threshold", "start_percent", "end_percent", "verbose"],
    "SpectrumApplyMiniMaxH3": [
        "enabled",
        "blend_weight",
        "degree",
        "ridge_lambda",
        "window_size",
        "flex_window",
        "warmup_steps",
        "tail_actual_steps",
        "max_history",
        "debug",
        "history_storage",
    ],
    "UC_MiniMaxH3Cache": [
        "reuse_threshold",
        "start_percent",
        "end_percent",
        "max_steps",
        "device",
        "verbose",
    ],
    "SolAttnPatch": [
        "tau",
        "start_percent",
        "end_percent",
        "min_tokens",
        "int8_qk",
        "sink_conditioning",
        "morton",
        "morton_curve",
        "verbose",
        "use_tma",
    ],
    "MiniMaxH3TurboLoRA": ["lora_name", "strength_model"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "ImageScale": ["upscale_method", "width", "height", "crop"],
    "CM_FloatToInt": ["a"],
    "ResolutionSelector": ["aspect_ratio", "megapixels", "multiple"],
    "PrimitiveFloat": ["value"],
    "PrimitiveStringMultiline": ["value"],
    "easy seed": ["seed"],
    "RandomNoise": ["noise_seed"],
    "PathchSageAttentionKJ": ["sage_attention", "allow_compile"],
    "MiniMaxH3SigmaShift": ["shift_video", "shift_audio"],
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],
    "ComfyMathExpression": ["expression"],
    "RIFEInterpolation": [
        "source_fps",
        "target_fps",
        "scale",
        "model_name",
        "batch_size",
        "use_fp16",
    ],
    "RTXVideoSuperResolution": ["resize_type", "scale", "quality"],
    "VHS_VideoCombine": None,  # dict widgets_values — handled specially
    "Any Switch (rgthree)": [],
    "BasicGuider": [],
    "SamplerCustomAdvanced": [],
    "VAEDecode": [],
    "VAEDecodeAudio": [],
    "easy cleanGpuUsed": [],
}


def load_ui_workflow(path: str | Path) -> dict[str, Any]:
    """Load a ComfyUI UI-format workflow JSON from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def set_link(
    api: dict[str, Any],
    node_id: str | int,
    input_name: str,
    from_id: str | int,
    from_slot: int = 0,
) -> None:
    api[str(node_id)]["inputs"][input_name] = [str(from_id), from_slot]


def set_widget(api: dict[str, Any], node_id: str | int, name: str, value: Any) -> None:
    api[str(node_id)]["inputs"][name] = value


def _apply_widgets_values(
    class_type: str, widgets_values: Any, inputs: dict[str, Any]
) -> None:
    """Map widgets_values onto inputs (does not overwrite existing linked inputs)."""
    if widgets_values is None:
        return

    if class_type == "VHS_VideoCombine" and isinstance(widgets_values, dict):
        for key, val in widgets_values.items():
            if key == "videopreview":
                continue
            if key not in inputs:
                inputs[key] = val
        return

    names = WIDGET_MAP.get(class_type)
    if names is None:
        # Unknown type with a list — best-effort skip.
        return
    if not names:
        return
    if not isinstance(widgets_values, (list, tuple)):
        if len(names) == 1:
            if names[0] not in inputs:
                inputs[names[0]] = widgets_values
        return

    for i, name in enumerate(names):
        if i >= len(widgets_values):
            break
        if name in inputs:
            continue  # linked input wins
        val = widgets_values[i]
        # Skip UI-only trailing noise (e.g. easy seed's None / mode strings already
        # excluded by WIDGET_MAP length).
        if val is None and name not in ("lora_mode",):
            continue
        inputs[name] = val


def ui_to_api_prompt(ui: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert a UI workflow dict to a ComfyUI API prompt graph.

    Returns ``{node_id_str: {"class_type": ..., "inputs": {...}}}``.
    UI-only node types (Note, Fast Groups Bypasser, Fast Bypasser, …) are skipped.

    Autogrow inputs keep dotted names (e.g. ``values.a``) — nested
    ``values: {a: ...}`` fails Comfy validation when the node is depended on.
    """
    links_by_id: dict[int, list[Any]] = {}
    for link in ui.get("links") or []:
        # [link_id, from_node, from_slot, to_node, to_slot, type]
        links_by_id[link[0]] = link

    api: dict[str, dict[str, Any]] = {}
    for node in ui.get("nodes") or []:
        class_type = node.get("type") or node.get("class_type")
        if not class_type or class_type in UI_ONLY_TYPES:
            continue
        nid = str(node["id"])
        inputs: dict[str, Any] = {}

        # Linked inputs first.
        for inp in node.get("inputs") or []:
            name = inp.get("name")
            link_id = inp.get("link")
            if name is None or link_id is None:
                continue
            link = links_by_id.get(link_id)
            if not link:
                continue
            from_node, from_slot = link[1], link[2]
            inputs[name] = [str(from_node), int(from_slot)]

        _apply_widgets_values(class_type, node.get("widgets_values"), inputs)

        api[nid] = {"class_type": class_type, "inputs": inputs}

    return api


def _omit(api: dict[str, Any], *node_ids: int | str) -> None:
    for nid in node_ids:
        api.pop(str(nid), None)


def _active_cache_node(cfg: RunConfig) -> int | None:
    if not cfg.cache_enabled or cfg.cache == "none":
        return None
    if cfg.cache == "easy":
        return NODE_EASYCACHE
    if cfg.cache == "spectrum":
        return NODE_SPECTRUM
    if cfg.cache == "h3":
        return NODE_H3_CACHE
    return None


def _apply_widgets_to_node(
    api: dict[str, Any], node_id: int | str, widgets: dict[str, Any]
) -> None:
    """Apply flat widget key/values onto a node if the key is already an input or known."""
    nid = str(node_id)
    if nid not in api:
        return
    node_inputs = api[nid]["inputs"]
    class_type = api[nid]["class_type"]
    known = set(WIDGET_MAP.get(class_type) or [])
    # model is always a link input for these patch nodes
    known.add("model")
    for key, val in widgets.items():
        if key in node_inputs or key in known:
            node_inputs[key] = val


def _primitive_value(api: dict[str, Any], node_id: int | str, default: Any) -> Any:
    nid = str(node_id)
    if nid not in api:
        return default
    return api[nid]["inputs"].get("value", default)


def apply_config(
    ui: dict[str, Any],
    cfg: RunConfig,
    *,
    output_tag: str | None = None,
    cache_bust: int = 0,
) -> dict[str, dict[str, Any]]:
    """Build an API prompt from *ui* with *cfg* applied (omit + rewire).

    MODEL path is rebuilt explicitly::

        loader → [TurboLoRA?] → Sol XOR Sage → SigmaShift → [cache?] → Scheduler + Guider

    Unused loaders, cache nodes, switches, optional LoRA, and inactive post-process
    nodes are omitted. Video path is rewired around the omitted post-process nodes.

    *output_tag* only changes VHS ``filename_prefix`` (unique output files). It must
    not alter sampling inputs. Graph-level re-execution after warmup is handled by
    clearing Comfy's **execution** cache — not by mutating model/cache widgets.

    *cache_bust* is deprecated/ignored (kept for call-site compatibility).
    """
    del cache_bust  # no longer used — identical graphs for warmup vs timed
    api = ui_to_api_prompt(ui)

    steps_eff = TURBO_STEPS_DEFAULT if cfg.turbo else int(cfg.steps)

    # --- Prompt / seed / schedule / resolution / duration ---
    if str(NODE_PROMPT) in api:
        set_widget(api, NODE_PROMPT, "value", BASELINE_PROMPT)

    if str(NODE_SEED) in api:
        set_widget(api, NODE_SEED, "seed", int(cfg.seed))
    if str(NODE_NOISE) in api:
        # Keep link from easy seed when present; also force seed value if unlinked.
        noise_in = api[str(NODE_NOISE)]["inputs"]
        if not (
            isinstance(noise_in.get("noise_seed"), list)
            and len(noise_in["noise_seed"]) == 2
        ):
            set_widget(api, NODE_NOISE, "noise_seed", int(cfg.seed))

    if str(NODE_SCHEDULER) in api:
        set_widget(api, NODE_SCHEDULER, "scheduler", cfg.scheduler)
        # Overwrite any linked steps (FloatToInt / turbo switch) with a scalar.
        set_widget(api, NODE_SCHEDULER, "steps", steps_eff)
    if str(NODE_SAMPLER) in api:
        set_widget(api, NODE_SAMPLER, "sampler_name", cfg.sampler)
    if str(NODE_RESOLUTION) in api:
        set_widget(api, NODE_RESOLUTION, "megapixels", float(cfg.mp))
    if str(NODE_DURATION) in api:
        set_widget(api, NODE_DURATION, "value", float(cfg.duration_s))

    # --- First frame (FL2V): set LoadImage; strip last-frame path (UI bypass is not API) ---
    first = (getattr(cfg, "first_frame", None) or DEFAULT_FIRST_FRAME).strip()
    first = Path(first.replace("\\", "/")).name
    if str(NODE_LOAD_IMAGE) in api:
        set_widget(api, NODE_LOAD_IMAGE, "image", first)
    # Force first-frame-only: omit last-frame load/scale even if UI had them linked
    _omit(api, NODE_LAST_FRAME, NODE_FIT_LAST)
    if str(NODE_I2V) in api:
        api[str(NODE_I2V)]["inputs"].pop("last_frame", None)
        # Ensure first_frame still comes from fit-first (146) or load image (20)
        if str(NODE_FIT_FIRST) in api:
            set_link(api, NODE_I2V, "first_frame", NODE_FIT_FIRST, 0)
        elif str(NODE_LOAD_IMAGE) in api:
            set_link(api, NODE_I2V, "first_frame", NODE_LOAD_IMAGE, 0)

    # Unique output name per execution (warmup vs timed, etc.)
    if str(NODE_VIDEO_COMBINE) in api:
        tag = output_tag or "bench"
        # Sanitize for filenames
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:120]
        set_widget(api, NODE_VIDEO_COMBINE, "filename_prefix", f"bench/{safe}")

    # --- Model loader + CLIP ---
    from bench.diffusion_models import resolve_model_filename

    model_file = resolve_model_filename(
        getattr(cfg, "diffusion_model", None) or "",
        cfg.model_path,
        cfg.quant,
    )
    # diffusion_model (if set) already aligned model_path via RunConfig.__post_init__
    # All non-GGUF models use the UNETLoader (NVFP4) node — no OTUNet / int8 split.
    if cfg.model_path == "gguf":
        loader = NODE_GGUF
        _omit(api, NODE_UNET, NODE_INT8, NODE_CLIP)
        if str(NODE_GGUF) in api:
            set_widget(api, NODE_GGUF, "model_name", model_file)
        if str(NODE_CLIP_GGUF) in api:
            set_widget(api, NODE_CLIP_GGUF, "clip_name", GGUF_CLIP)
        if str(NODE_I2V) in api and str(NODE_CLIP_GGUF) in api:
            set_link(api, NODE_I2V, "clip", NODE_CLIP_GGUF, 0)
    else:
        loader = NODE_UNET
        _omit(api, NODE_GGUF, NODE_CLIP_GGUF, NODE_INT8)
        if str(NODE_UNET) in api:
            set_widget(api, NODE_UNET, "unet_name", model_file)
        if str(NODE_I2V) in api and str(NODE_CLIP) in api:
            set_link(api, NODE_I2V, "clip", NODE_CLIP, 0)

    if str(loader) not in api:
        raise KeyError(f"Selected model loader node {loader} missing from workflow")

    # --- Rebuild MODEL path ---
    # Matches working Music Suite API exports:
    #   loader → [TurboLoRA?] → [SolAttn?] → Sage → SigmaShift → [cache?] → Scheduler/Guider
    # Sol and Sage are stacked (Sol then Sage), not exclusive. Omitting Sage when Sol
    # was on diverged from successful Comfy runs and is not needed for correctness.
    prev = str(loader)

    if cfg.turbo and str(NODE_TURBO_LORA) in api:
        set_link(api, NODE_TURBO_LORA, "model", prev, 0)
        prev = str(NODE_TURBO_LORA)
    else:
        _omit(api, NODE_TURBO_LORA)

    # Optional LoRA is always bypassed for the bench — link past it.
    _omit(api, NODE_OPTIONAL_LORA)

    if cfg.sol_attn and str(NODE_SOL_ATTN) in api:
        set_link(api, NODE_SOL_ATTN, "model", prev, 0)
        prev = str(NODE_SOL_ATTN)
    else:
        _omit(api, NODE_SOL_ATTN)

    if str(NODE_SAGE) not in api:
        raise KeyError(f"Sage attention node {NODE_SAGE} missing from workflow")
    set_link(api, NODE_SAGE, "model", prev, 0)
    prev = str(NODE_SAGE)

    set_link(api, NODE_SIGMA_SHIFT, "model", prev, 0)
    prev = str(NODE_SIGMA_SHIFT)

    cache_node = _active_cache_node(cfg)
    for cid in (NODE_EASYCACHE, NODE_SPECTRUM, NODE_H3_CACHE):
        if cache_node is None or cid != cache_node:
            _omit(api, cid)

    if cache_node is not None:
        if str(cache_node) not in api:
            raise KeyError(f"Cache node {cache_node} missing from workflow")
        set_link(api, cache_node, "model", prev, 0)
        prev = str(cache_node)

    set_link(api, NODE_SCHEDULER, "model", prev, 0)
    set_link(api, NODE_GUIDER, "model", prev, 0)

    # --- Guider conditioning (optional clean TE) ---
    if cfg.clean_vram and str(NODE_CLEAN_TE) in api and str(NODE_I2V) in api:
        set_link(api, NODE_CLEAN_TE, "anything", NODE_I2V, 0)
        set_link(api, NODE_GUIDER, "conditioning", NODE_CLEAN_TE, 0)
    else:
        _omit(api, NODE_CLEAN_TE)
        if str(NODE_GUIDER) in api and str(NODE_I2V) in api:
            set_link(api, NODE_GUIDER, "conditioning", NODE_I2V, 0)

    # --- Video post path: sampler → [clean?] → decode → [rife?] → [upscale?] → combine ---
    if cfg.clean_vram and str(NODE_CLEAN_VRAM) in api:
        set_link(api, NODE_CLEAN_VRAM, "anything", NODE_SAMPLER_ADV, 0)
        if str(NODE_VAE_DECODE) in api:
            set_link(api, NODE_VAE_DECODE, "samples", NODE_CLEAN_VRAM, 0)
    else:
        _omit(api, NODE_CLEAN_VRAM)
        if str(NODE_VAE_DECODE) in api and str(NODE_SAMPLER_ADV) in api:
            set_link(api, NODE_VAE_DECODE, "samples", NODE_SAMPLER_ADV, 0)

    prev_img = str(NODE_VAE_DECODE) if str(NODE_VAE_DECODE) in api else None

    if cfg.rife and str(NODE_RIFE) in api and prev_img is not None:
        set_link(api, NODE_RIFE, "images", prev_img, 0)
        prev_img = str(NODE_RIFE)
    else:
        _omit(api, NODE_RIFE)
        if not cfg.rife:
            _omit(api, NODE_INTERP_FPS)

    if cfg.upscaler and str(NODE_UPSCALER) in api and prev_img is not None:
        set_link(api, NODE_UPSCALER, "images", prev_img, 0)
        prev_img = str(NODE_UPSCALER)
    else:
        _omit(api, NODE_UPSCALER)

    if prev_img is not None and str(NODE_VIDEO_COMBINE) in api:
        set_link(api, NODE_VIDEO_COMBINE, "images", prev_img, 0)

    # Video-only: MiniMax audio latents often contain NaN/+Inf which makes VHS
    # ffmpeg AAC mux fail even after the video track is written (broken outputs).
    # Bench only needs the MP4 picture track.
    _omit(api, NODE_VAE_DECODE_AUDIO, NODE_VAE_AUDIO)
    if str(NODE_VIDEO_COMBINE) in api:
        api[str(NODE_VIDEO_COMBINE)]["inputs"].pop("audio", None)
        set_widget(api, NODE_VIDEO_COMBINE, "trim_to_audio", False)

    # Frame rate: RIFE uses interp FPS when active, else base FPS.
    if str(NODE_VIDEO_COMBINE) in api:
        if cfg.rife:
            fps = _primitive_value(api, NODE_INTERP_FPS, 60)
        else:
            fps = _primitive_value(api, NODE_BASE_FPS, 24)
        set_widget(api, NODE_VIDEO_COMBINE, "frame_rate", fps)

    # --- Omit switches, turbo step plumbing, and non-bench outputs ---
    # SaveAudio / SaveImage / last-frame extract are optional UI exports; their
    # links break after we rewire the video path, and Comfy validates them as
    # graph roots if left in the prompt.
    _omit(
        api,
        NODE_SWITCH_QUANT,  # v2 legacy
        NODE_SWITCH_CACHE,  # v2 legacy
        NODE_CLIP_SWITCH,
        NODE_MODEL_SWITCH,
        NODE_ATTN_SWITCH,
        NODE_STEPS_SWITCH,
        NODE_FPS_SWITCH,
        NODE_TURBO_STEPS,
        NODE_DEFAULT_STEPS,
        NODE_FLOAT_TO_INT,
        NODE_SECONDARY_COMBINE,
        NODE_IMAGE_FROM_BATCH,
        NODE_SAVE_AUDIO,
        NODE_LAST_FRAME_INDEX,
        NODE_SAVE_LAST_FRAME,
    )

    # --- Variant widgets: cache keys only on cache node; sol keys only on SolAttn ---
    # Expand separately so shared start_percent/end_percent never cross-contaminate.
    if cache_node is not None:
        cache_widgets = expand_presets(replace(cfg, sol_attn=False))
        if cfg.widgets:
            cache_widgets = {**cache_widgets, **cfg.widgets}
        _apply_widgets_to_node(api, cache_node, cache_widgets)

    if cfg.sol_attn and str(NODE_SOL_ATTN) in api:
        sol_widgets = expand_presets(replace(cfg, cache_enabled=False, cache="none"))
        if cfg.widgets:
            sol_widgets = {**sol_widgets, **cfg.widgets}
        _apply_widgets_to_node(api, NODE_SOL_ATTN, sol_widgets)

    # --- Prune dangling references to omitted nodes ---
    alive = set(api.keys())
    for nid, node in list(api.items()):
        for ikey, ival in list(node["inputs"].items()):
            if (
                isinstance(ival, list)
                and len(ival) == 2
                and isinstance(ival[0], str)
                and ival[0] not in alive
            ):
                del node["inputs"][ikey]

    # Drop any remaining incomplete terminal saves (defensive).
    for nid, node in list(api.items()):
        ct = node.get("class_type") or ""
        if ct in ("SaveImage", "SaveAudio"):
            ins = node.get("inputs") or {}
            if ct == "SaveImage" and ("images" not in ins or "filename_prefix" not in ins):
                _omit(api, nid)
            elif ct == "SaveAudio" and ("audio" not in ins or "filename_prefix" not in ins):
                _omit(api, nid)

    return api
