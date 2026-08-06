"""UI workflow → ComfyUI API prompt conversion and RunConfig mutation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench.constants import (
    BASELINE_PROMPT,
    INT8_UNET,
    NODE_CLEAN_VRAM,
    NODE_DURATION,
    NODE_EASYCACHE,
    NODE_GUIDER,
    NODE_H3_CACHE,
    NODE_INT8,
    NODE_NOISE,
    NODE_PROMPT,
    NODE_RESOLUTION,
    NODE_RIFE,
    NODE_SAGE,
    NODE_SAMPLER,
    NODE_SCHEDULER,
    NODE_SEED,
    NODE_SIGMA_SHIFT,
    NODE_SOL_ATTN,
    NODE_SPECTRUM,
    NODE_SWITCH_CACHE,
    NODE_SWITCH_QUANT,
    NODE_UNET,
    NODE_UPSCALER,
    NODE_VAE_DECODE,
    NODE_VIDEO_COMBINE,
    NVFP4_UNET,
)
from bench.models import RunConfig

# Target-FPS primitive only used by RIFE (and optionally fps switch).
NODE_TARGET_FPS = 95
NODE_DEFAULT_FPS = 108
NODE_FPS_SWITCH = 109
NODE_MATH_LENGTH = 103
NODE_SAMPLER_ADV = 10

# Node types that exist only in the UI graph (no executable class_type).
UI_ONLY_TYPES = frozenset(
    {
        "Note",
        "Fast Groups Bypasser (rgthree)",
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
    "CLIPLoader": ["clip_name", "type", "device"],
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
    UI-only node types (Note, Fast Groups Bypasser, …) are skipped.

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


def _active_cache_node(cache: str) -> int | None:
    if cache == "easy":
        return NODE_EASYCACHE
    if cache == "spectrum":
        return NODE_SPECTRUM
    if cache == "h3":
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


def apply_config(
    ui: dict[str, Any],
    cfg: RunConfig,
    *,
    output_tag: str | None = None,
    cache_bust: int = 0,
) -> dict[str, dict[str, Any]]:
    """Build an API prompt from *ui* with *cfg* applied (omit + rewire).

    MODEL path is rebuilt explicitly::

        loader → Sage → [SolAttn?] → SigmaShift → [cache?] → Scheduler + Guider

    Unused quant loader, cache nodes, RIFE/upscaler/clean-VRAM, and Any Switches
    126/127 are omitted. Video path is rewired around the omitted post-process nodes.

    *output_tag* only changes VHS ``filename_prefix`` (unique output files). It must
    not alter sampling inputs. Graph-level re-execution after warmup is handled by
    clearing Comfy's **execution** cache — not by mutating model/cache widgets.

    *cache_bust* is deprecated/ignored (kept for call-site compatibility).
    """
    del cache_bust  # no longer used — identical graphs for warmup vs timed
    api = ui_to_api_prompt(ui)

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
        set_widget(api, NODE_SCHEDULER, "steps", int(cfg.steps))
    if str(NODE_SAMPLER) in api:
        set_widget(api, NODE_SAMPLER, "sampler_name", cfg.sampler)
    if str(NODE_RESOLUTION) in api:
        set_widget(api, NODE_RESOLUTION, "megapixels", float(cfg.mp))
    if str(NODE_DURATION) in api:
        set_widget(api, NODE_DURATION, "value", float(cfg.duration_s))

    # Unique output name per execution (warmup vs timed, etc.)
    if str(NODE_VIDEO_COMBINE) in api:
        tag = output_tag or "bench"
        # Sanitize for filenames
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:120]
        set_widget(api, NODE_VIDEO_COMBINE, "filename_prefix", f"bench/{safe}")

    # --- Quant: keep one loader, set model filename ---
    if cfg.quant == "int8":
        loader = NODE_INT8
        _omit(api, NODE_UNET)
        if str(NODE_INT8) in api:
            set_widget(api, NODE_INT8, "unet_name", INT8_UNET)
    else:
        loader = NODE_UNET
        _omit(api, NODE_INT8)
        if str(NODE_UNET) in api:
            set_widget(api, NODE_UNET, "unet_name", NVFP4_UNET)

    # Ensure loader node exists (should from UI conversion).
    if str(loader) not in api:
        raise KeyError(f"Selected quant loader node {loader} missing from workflow")

    # --- Rebuild MODEL path: loader → sage → [sol] → sigma → [cache] ---
    prev = str(loader)
    set_link(api, NODE_SAGE, "model", prev, 0)
    prev = str(NODE_SAGE)

    if cfg.sol_attn and str(NODE_SOL_ATTN) in api:
        set_link(api, NODE_SOL_ATTN, "model", prev, 0)
        prev = str(NODE_SOL_ATTN)
    else:
        _omit(api, NODE_SOL_ATTN)

    set_link(api, NODE_SIGMA_SHIFT, "model", prev, 0)
    prev = str(NODE_SIGMA_SHIFT)

    cache_node = _active_cache_node(cfg.cache)
    # Drop all three first, then re-add wiring for the active one.
    for cid in (NODE_EASYCACHE, NODE_SPECTRUM, NODE_H3_CACHE):
        if cache_node is None or cid != cache_node:
            _omit(api, cid)

    if cache_node is not None:
        if str(cache_node) not in api:
            # Active cache was omitted above only if not selected; re-convert path
            # means it should still be present. Rebuild from UI if missing.
            raise KeyError(f"Cache node {cache_node} missing from workflow")
        set_link(api, cache_node, "model", prev, 0)
        prev = str(cache_node)

    # Consumers that were fed by switch 127.
    set_link(api, NODE_SCHEDULER, "model", prev, 0)
    set_link(api, NODE_GUIDER, "model", prev, 0)

    # --- Omit switches and post-process path ---
    _omit(
        api,
        NODE_SWITCH_QUANT,
        NODE_SWITCH_CACHE,
        NODE_CLEAN_VRAM,
        NODE_RIFE,
        NODE_UPSCALER,
        NODE_TARGET_FPS,
    )

    # Rewire video: sampler → VAEDecode → VideoCombine (skip clean/rife/upscale).
    if str(NODE_VAE_DECODE) in api and str(NODE_SAMPLER_ADV) in api:
        set_link(api, NODE_VAE_DECODE, "samples", NODE_SAMPLER_ADV, 0)
    if str(NODE_VIDEO_COMBINE) in api and str(NODE_VAE_DECODE) in api:
        set_link(api, NODE_VIDEO_COMBINE, "images", NODE_VAE_DECODE, 0)

    # Drop fps switch feed from omitted target-fps; keep default fps if switch remains.
    if str(NODE_FPS_SWITCH) in api:
        fps_inputs = api[str(NODE_FPS_SWITCH)]["inputs"]
        # Remove any link pointing at omitted target fps node.
        for k, v in list(fps_inputs.items()):
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == str(NODE_TARGET_FPS):
                del fps_inputs[k]
        if str(NODE_DEFAULT_FPS) in api and not any(
            isinstance(v, list) for v in fps_inputs.values()
        ):
            set_link(api, NODE_FPS_SWITCH, "any_01", NODE_DEFAULT_FPS, 0)

    # --- Variant widgets onto active cache and/or SolAttn ---
    widgets = cfg.widgets or {}
    if widgets:
        if cache_node is not None:
            _apply_widgets_to_node(api, cache_node, widgets)
        if cfg.sol_attn and str(NODE_SOL_ATTN) in api:
            _apply_widgets_to_node(api, NODE_SOL_ATTN, widgets)

    # Keep patch/cache verbose flags at workflow defaults (no per-stage mutation).
    # Fairness: warmup and timed must use the same sampling graph.

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

    return api
