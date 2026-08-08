"""Turning an editor workflow into an executable ComfyUI prompt.

Two jobs live here. `to_api_prompt` translates the editor's node/link format into the flat
`{id: {class_type, inputs}}` shape the API wants. `apply_config` then rewires that graph to
match one `GenerationConfig`: it drops the nodes this run does not use and relinks the
survivors so no link points at a hole.

The rewiring is explicit rather than switch-driven because ComfyUI validates the whole
prompt before running anything. One dangling link fails the submission, and one orphan
output node fails it too — so both are removed here rather than hoped away.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from h3lab.comfy import nodes as N
from h3lab.comfy.presets import cache_widgets, sol_widgets
from h3lab.domain.config import (
    DEFAULT_ASPECT,
    MAX_REF_AUDIOS,
    MAX_REF_IMAGES,
    MAX_REF_VIDEOS,
    GenerationConfig,
    resolve_model_filename,
)

Prompt = dict[str, dict[str, Any]]

DEFAULT_BASE_FPS = 24
DEFAULT_INTERP_FPS = 60


class WorkflowError(RuntimeError):
    """The workflow template cannot express the requested configuration."""


def load_workflow(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- editor format → api format -------------------------------------------


def _widget_inputs(class_type: str, widgets_values: Any, inputs: dict[str, Any]) -> None:
    """Fold positional editor widget values into named inputs. Links always win."""
    if widgets_values is None:
        return

    if class_type == "VHS_VideoCombine" and isinstance(widgets_values, dict):
        for key, value in widgets_values.items():
            if key != "videopreview" and key not in inputs:
                inputs[key] = value
        return

    names = N.WIDGET_ORDER.get(class_type)
    if not names:
        return

    if not isinstance(widgets_values, (list, tuple)):
        if len(names) == 1 and names[0] not in inputs:
            inputs[names[0]] = widgets_values
        return

    for index, name in enumerate(names):
        if index >= len(widgets_values):
            break
        if name in inputs:
            continue
        value = widgets_values[index]
        # A null widget means "leave the node's own default alone", except for lora_mode
        # where null is the meaningful "no LoRA" value.
        if value is None and name != "lora_mode":
            continue
        inputs[name] = value


def to_api_prompt(workflow: dict[str, Any]) -> Prompt:
    """Flatten an editor workflow into the API prompt shape.

    Autogrow inputs keep their dotted names (``ref_images.ref_image_0``); nesting them
    under a dict fails validation as soon as another node depends on the result.
    """
    links = {link[0]: link for link in workflow.get("links") or []}

    prompt: Prompt = {}
    for node in workflow.get("nodes") or []:
        class_type = node.get("type") or node.get("class_type")
        if not class_type or class_type in N.UI_ONLY_TYPES:
            continue
        inputs: dict[str, Any] = {}
        for slot in node.get("inputs") or []:
            name = slot.get("name")
            link_id = slot.get("link")
            if name is None or link_id is None:
                continue
            link = links.get(link_id)
            if not link:
                continue
            inputs[name] = [str(link[1]), int(link[2])]
        _widget_inputs(class_type, node.get("widgets_values"), inputs)
        prompt[str(node["id"])] = {"class_type": class_type, "inputs": inputs}

    return prompt


# --- small helpers ---------------------------------------------------------


def link(prompt: Prompt, node: int | str, name: str, source: int | str, slot: int = 0) -> None:
    prompt[str(node)]["inputs"][name] = [str(source), slot]


def widget(prompt: Prompt, node: int | str, name: str, value: Any) -> None:
    prompt[str(node)]["inputs"][name] = value


def drop(prompt: Prompt, *ids: int | str) -> None:
    for node_id in ids:
        prompt.pop(str(node_id), None)


def has(prompt: Prompt, node_id: int | str) -> bool:
    return str(node_id) in prompt


def _require(prompt: Prompt, node_id: int, what: str) -> None:
    if not has(prompt, node_id):
        raise WorkflowError(f"the workflow has no {what} (node {node_id})")


def _basename(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name


def _primitive(prompt: Prompt, node_id: int, default: Any) -> Any:
    if not has(prompt, node_id):
        return default
    return prompt[str(node_id)]["inputs"].get("value", default)


def _set_known_widgets(prompt: Prompt, node_id: int | str, values: dict[str, Any]) -> None:
    """Write widget values, but only names this node actually understands."""
    key = str(node_id)
    if key not in prompt:
        return
    inputs = prompt[key]["inputs"]
    known = set(N.WIDGET_ORDER.get(prompt[key]["class_type"]) or ())
    known.add("model")
    for name, value in values.items():
        if name in inputs or name in known:
            inputs[name] = value


# --- media wiring ----------------------------------------------------------


def _ensure(prompt: Prompt, node_id: int, class_type: str, inputs: dict[str, Any]) -> None:
    """Create a node the editor graph left out (a bypassed loader has no export)."""
    key = str(node_id)
    if key not in prompt:
        prompt[key] = {"class_type": class_type, "inputs": dict(inputs)}
    else:
        prompt[key]["inputs"].update(inputs)


def _ref_node_ids() -> tuple[int, ...]:
    ids: list[int] = [N.REF_IMAGE_BASE + i for i in range(MAX_REF_IMAGES)]
    for index in range(MAX_REF_VIDEOS):
        ids.append(N.REF_VIDEO_BASE + index)
        ids.append(N.REF_VIDEO_COMPONENTS_BASE + index)
        ids.append(N.REF_VIDEO_AUDIO_BASE + index)
    ids.extend(N.REF_AUDIO_BASE + i for i in range(MAX_REF_AUDIOS))
    return tuple(ids)


def _clear_autogrow(inputs: dict[str, Any]) -> None:
    prefixes = ("ref_images.", "ref_videos.", "ref_video_audios.", "ref_audios.")
    for key in [key for key in inputs if key.startswith(prefixes)]:
        del inputs[key]


def _wire_keyframes(prompt: Prompt, config: GenerationConfig) -> None:
    drop(prompt, *_ref_node_ids())
    if not has(prompt, N.CONDITIONING):
        return

    first = _basename(config.first_frame)
    if has(prompt, N.LOAD_FIRST_FRAME):
        widget(prompt, N.LOAD_FIRST_FRAME, "image", first)
        source = N.FIT_FIRST if has(prompt, N.FIT_FIRST) else N.LOAD_FIRST_FRAME
        link(prompt, N.CONDITIONING, "first_frame", source, 0)

    if config.last_frame and has(prompt, N.LOAD_LAST_FRAME):
        widget(prompt, N.LOAD_LAST_FRAME, "image", _basename(config.last_frame))
        source = N.FIT_LAST if has(prompt, N.FIT_LAST) else N.LOAD_LAST_FRAME
        link(prompt, N.CONDITIONING, "last_frame", source, 0)
    else:
        drop(prompt, N.LOAD_LAST_FRAME, N.FIT_LAST)
        prompt[str(N.CONDITIONING)]["inputs"].pop("last_frame", None)


def _wire_references(prompt: Prompt, config: GenerationConfig) -> None:
    drop(prompt, N.LOAD_FIRST_FRAME, N.LOAD_LAST_FRAME, N.FIT_FIRST, N.FIT_LAST)
    if not has(prompt, N.CONDITIONING):
        return

    conditioning = prompt[str(N.CONDITIONING)]
    # Guard against the wrong template being paired with the mode.
    if conditioning["class_type"] == "MiniMaxH3ImageToVideo":
        conditioning["class_type"] = "MiniMaxH3ReferenceToVideo"
    conditioning["inputs"].pop("first_frame", None)
    conditioning["inputs"].pop("last_frame", None)
    _clear_autogrow(conditioning["inputs"])

    # Reference conditioning declares audio_vae as required even when we never decode it.
    if has(prompt, N.VAE_AUDIO):
        link(prompt, N.CONDITIONING, "audio_vae", N.VAE_AUDIO, 0)
    widget(prompt, N.CONDITIONING, "ref_image_size", config.ref_image_size)

    alive: set[int] = set()

    for index, name in enumerate(config.ref_images[:MAX_REF_IMAGES]):
        node_id = N.REF_IMAGE_BASE + index
        _ensure(prompt, node_id, "LoadImage", {"image": _basename(name)})
        widget(prompt, node_id, "image", _basename(name))
        link(prompt, N.CONDITIONING, f"ref_images.ref_image_{index}", node_id, 0)
        alive.add(node_id)

    overrides = list(config.ref_video_audios[:MAX_REF_VIDEOS])
    for index, name in enumerate(config.ref_videos[:MAX_REF_VIDEOS]):
        video_id = N.REF_VIDEO_BASE + index
        components_id = N.REF_VIDEO_COMPONENTS_BASE + index
        _ensure(prompt, video_id, "LoadVideo", {"file": _basename(name)})
        widget(prompt, video_id, "file", _basename(name))
        _ensure(prompt, components_id, "GetVideoComponents", {})
        link(prompt, components_id, "video", video_id, 0)
        link(prompt, N.CONDITIONING, f"ref_videos.ref_video_{index}", components_id, 0)
        alive.update({video_id, components_id})
        # Slot 1 of GetVideoComponents is the video's own soundtrack; use it unless the
        # run supplies a separate audio file for this slot.
        if not (index < len(overrides) and overrides[index]):
            link(
                prompt,
                N.CONDITIONING,
                f"ref_video_audios.ref_video_audio_{index}",
                components_id,
                1,
            )

    for index, name in enumerate(overrides):
        if not name:
            continue
        audio_id = N.REF_VIDEO_AUDIO_BASE + index
        _ensure(prompt, audio_id, "LoadAudio", {"audio": _basename(name)})
        widget(prompt, audio_id, "audio", _basename(name))
        link(prompt, N.CONDITIONING, f"ref_video_audios.ref_video_audio_{index}", audio_id, 0)
        alive.add(audio_id)

    for index, name in enumerate(config.ref_audios[:MAX_REF_AUDIOS]):
        audio_id = N.REF_AUDIO_BASE + index
        _ensure(prompt, audio_id, "LoadAudio", {"audio": _basename(name)})
        widget(prompt, audio_id, "audio", _basename(name))
        link(prompt, N.CONDITIONING, f"ref_audios.ref_audio_{index}", audio_id, 0)
        alive.add(audio_id)

    drop(prompt, *(node_id for node_id in _ref_node_ids() if node_id not in alive))


def _wire_text_only(prompt: Prompt) -> None:
    drop(prompt, N.LOAD_FIRST_FRAME, N.LOAD_LAST_FRAME, N.FIT_FIRST, N.FIT_LAST)
    drop(prompt, *_ref_node_ids())
    if has(prompt, N.CONDITIONING):
        prompt[str(N.CONDITIONING)]["inputs"].pop("first_frame", None)
        prompt[str(N.CONDITIONING)]["inputs"].pop("last_frame", None)


# --- model path ------------------------------------------------------------


def _wire_model_loader(prompt: Prompt, config: GenerationConfig) -> int:
    """Select the loader for this model file and point the encoder at its CLIP."""
    filename = resolve_model_filename(config.diffusion_model)
    if config.uses_gguf:
        drop(prompt, N.UNET, N.INT8_UNET, N.CLIP)
        if has(prompt, N.GGUF_UNET):
            widget(prompt, N.GGUF_UNET, "model_name", filename)
        if has(prompt, N.GGUF_CLIP):
            # The template's saved clip_name stands: which text encoder pairs with which
            # quantised model is knowledge the lab does not have and should not invent.
            if has(prompt, N.CONDITIONING):
                link(prompt, N.CONDITIONING, "clip", N.GGUF_CLIP, 0)
        _require(prompt, N.GGUF_UNET, "GGUF model loader")
        return N.GGUF_UNET

    drop(prompt, N.GGUF_UNET, N.GGUF_CLIP, N.INT8_UNET)
    if has(prompt, N.UNET):
        widget(prompt, N.UNET, "unet_name", filename)
    if has(prompt, N.CONDITIONING) and has(prompt, N.CLIP):
        link(prompt, N.CONDITIONING, "clip", N.CLIP, 0)
    _require(prompt, N.UNET, "diffusion model loader")
    return N.UNET


def _wire_model_chain(prompt: Prompt, config: GenerationConfig, loader: int) -> None:
    """loader → [turbo LoRA] → [attention patch] → sage → sigma shift → [cache] → sampling.

    The attention patch and Sage attention stack rather than exclude each other. Omitting
    Sage while the patch was active diverged from the graphs that ran successfully in
    ComfyUI, so both stay in the chain.
    """
    previous: int | str = loader

    if config.turbo and has(prompt, N.TURBO_LORA):
        link(prompt, N.TURBO_LORA, "model", previous, 0)
        previous = N.TURBO_LORA
    else:
        drop(prompt, N.TURBO_LORA)

    # The optional LoRA slot is never part of a benchmark; link past it.
    drop(prompt, N.OPTIONAL_LORA)

    if config.sol_attn and has(prompt, N.SOL_ATTN):
        link(prompt, N.SOL_ATTN, "model", previous, 0)
        previous = N.SOL_ATTN
    else:
        drop(prompt, N.SOL_ATTN)

    _require(prompt, N.SAGE_ATTN, "Sage attention patch")
    link(prompt, N.SAGE_ATTN, "model", previous, 0)
    previous = N.SAGE_ATTN

    _require(prompt, N.SIGMA_SHIFT, "sigma shift node")
    link(prompt, N.SIGMA_SHIFT, "model", previous, 0)
    previous = N.SIGMA_SHIFT

    active_cache = N.CACHE_NODE_BY_NAME.get(config.cache) if config.cache_active else None
    drop(prompt, *(node for node in N.CACHE_NODES if node != active_cache))
    if active_cache is not None:
        if not has(prompt, active_cache):
            raise WorkflowError(
                f"the workflow has no {config.cache} cache node (node {active_cache})"
            )
        link(prompt, active_cache, "model", previous, 0)
        previous = active_cache

    _require(prompt, N.SCHEDULER, "scheduler")
    _require(prompt, N.GUIDER, "guider")
    link(prompt, N.SCHEDULER, "model", previous, 0)
    link(prompt, N.GUIDER, "model", previous, 0)

    if active_cache is not None:
        _set_known_widgets(prompt, active_cache, cache_widgets(config))
    if config.sol_attn and has(prompt, N.SOL_ATTN):
        _set_known_widgets(prompt, N.SOL_ATTN, sol_widgets(config))


# --- video path ------------------------------------------------------------


def _wire_video_path(prompt: Prompt, config: GenerationConfig) -> None:
    if config.clean_vram and has(prompt, N.CLEAN_VRAM):
        link(prompt, N.CLEAN_VRAM, "anything", N.SAMPLER, 0)
        if has(prompt, N.VAE_DECODE):
            link(prompt, N.VAE_DECODE, "samples", N.CLEAN_VRAM, 0)
    else:
        drop(prompt, N.CLEAN_VRAM)
        if has(prompt, N.VAE_DECODE) and has(prompt, N.SAMPLER):
            link(prompt, N.VAE_DECODE, "samples", N.SAMPLER, 0)

    images: int | None = N.VAE_DECODE if has(prompt, N.VAE_DECODE) else None

    if config.rife and has(prompt, N.RIFE) and images is not None:
        link(prompt, N.RIFE, "images", images, 0)
        images = N.RIFE
    else:
        drop(prompt, N.RIFE)
        if not config.rife:
            drop(prompt, N.INTERP_FPS)

    if config.upscaler and has(prompt, N.UPSCALER) and images is not None:
        link(prompt, N.UPSCALER, "images", images, 0)
        images = N.UPSCALER
    else:
        drop(prompt, N.UPSCALER)

    if images is not None and has(prompt, N.VIDEO_COMBINE):
        link(prompt, N.VIDEO_COMBINE, "images", images, 0)

    # Video-only output. MiniMax audio latents frequently contain NaN or +Inf, which makes
    # the ffmpeg AAC mux fail after the picture track is already written — losing the whole
    # file. A benchmark only needs the picture track.
    drop(prompt, N.VAE_DECODE_AUDIO)
    if config.mode != "r2v":
        drop(prompt, N.VAE_AUDIO)
    if has(prompt, N.VIDEO_COMBINE):
        prompt[str(N.VIDEO_COMBINE)]["inputs"].pop("audio", None)
        widget(prompt, N.VIDEO_COMBINE, "trim_to_audio", False)
        fps = (
            _primitive(prompt, N.INTERP_FPS, DEFAULT_INTERP_FPS)
            if config.rife
            else _primitive(prompt, N.BASE_FPS, DEFAULT_BASE_FPS)
        )
        widget(prompt, N.VIDEO_COMBINE, "frame_rate", fps)


def _wire_conditioning_output(prompt: Prompt, config: GenerationConfig) -> None:
    if config.clean_vram and has(prompt, N.CLEAN_TEXT_ENCODER) and has(prompt, N.CONDITIONING):
        link(prompt, N.CLEAN_TEXT_ENCODER, "anything", N.CONDITIONING, 0)
        link(prompt, N.GUIDER, "conditioning", N.CLEAN_TEXT_ENCODER, 0)
        return
    drop(prompt, N.CLEAN_TEXT_ENCODER)
    if has(prompt, N.GUIDER) and has(prompt, N.CONDITIONING):
        link(prompt, N.GUIDER, "conditioning", N.CONDITIONING, 0)


# --- pruning ---------------------------------------------------------------


def _prune_dangling_links(prompt: Prompt) -> None:
    """Remove every input that points at a node no longer in the prompt."""
    alive = set(prompt)
    for node in prompt.values():
        for name, value in list(node["inputs"].items()):
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] not in alive
            ):
                del node["inputs"][name]


def _prune_incomplete_outputs(prompt: Prompt) -> None:
    """Drop save nodes left without their required inputs.

    ComfyUI validates output nodes as graph roots, so an orphan `SaveImage` rejects the
    whole prompt even though nothing depends on it.
    """
    required = {"SaveImage": "images", "SaveAudio": "audio", "SaveVideo": "video"}
    for node_id, node in list(prompt.items()):
        needed = required.get(node.get("class_type") or "")
        if needed is None:
            continue
        inputs = node.get("inputs") or {}
        if needed not in inputs or "filename_prefix" not in inputs:
            drop(prompt, node_id)


def output_filename_prefix(tag: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in tag)[:120]
    return f"h3lab/{safe or 'run'}"


# --- entry point -----------------------------------------------------------


def apply_config(
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    output_tag: str = "run",
) -> Prompt:
    """Build an executable prompt for exactly this configuration.

    *output_tag* only affects the output filename. It must never touch a sampling input,
    or two runs of the same configuration would stop being comparable.
    """
    prompt = to_api_prompt(workflow)

    if has(prompt, N.PROMPT):
        widget(prompt, N.PROMPT, "value", config.prompt)
    if has(prompt, N.SEED):
        widget(prompt, N.SEED, "seed", config.seed)
    if has(prompt, N.NOISE):
        noise_inputs = prompt[str(N.NOISE)]["inputs"]
        existing = noise_inputs.get("noise_seed")
        # Keep the link from the seed node when the template has one; only an unlinked
        # noise node needs the literal.
        if not (isinstance(existing, list) and len(existing) == 2):
            widget(prompt, N.NOISE, "noise_seed", config.seed)
    if has(prompt, N.SCHEDULER):
        widget(prompt, N.SCHEDULER, "scheduler", config.scheduler)
        # A scalar replaces whatever step plumbing the editor used, so the run's step
        # count is the one recorded in the config.
        widget(prompt, N.SCHEDULER, "steps", config.effective_steps)
    if has(prompt, N.SAMPLER_SELECT):
        widget(prompt, N.SAMPLER_SELECT, "sampler_name", config.sampler)
    if has(prompt, N.RESOLUTION):
        widget(prompt, N.RESOLUTION, "aspect_ratio", config.aspect_ratio or DEFAULT_ASPECT)
        widget(prompt, N.RESOLUTION, "megapixels", config.mp)
    if has(prompt, N.DURATION):
        widget(prompt, N.DURATION, "value", config.duration_s)
    if has(prompt, N.VIDEO_COMBINE):
        widget(prompt, N.VIDEO_COMBINE, "filename_prefix", output_filename_prefix(output_tag))

    if config.mode == "t2v":
        _wire_text_only(prompt)
    elif config.mode == "r2v":
        _wire_references(prompt, config)
    else:
        _wire_keyframes(prompt, config)

    loader = _wire_model_loader(prompt, config)
    _wire_model_chain(prompt, config, loader)
    _wire_conditioning_output(prompt, config)
    _wire_video_path(prompt, config)

    drop(prompt, *N.EDITOR_ONLY_NODES)
    _prune_dangling_links(prompt)
    _prune_incomplete_outputs(prompt)
    return prompt


def missing_links(prompt: Prompt) -> list[str]:
    """Every input still pointing at an absent node. Should be empty after `apply_config`."""
    alive = set(prompt)
    problems: list[str] = []
    for node_id, node in prompt.items():
        for name, value in node["inputs"].items():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] not in alive
            ):
                problems.append(f"{node_id}.{name} → {value[0]} (absent)")
    return sorted(problems)


def referenced_files(prompt: Prompt) -> list[str]:
    """Input media the prompt expects ComfyUI to already have."""
    keys = ("image", "file", "audio")
    found: list[str] = []
    for node in prompt.values():
        for key in keys:
            value = node["inputs"].get(key)
            if isinstance(value, str) and value:
                found.append(value)
    return sorted(set(found))


def describe(prompt: Prompt) -> dict[str, Any]:
    return {
        "nodes": len(prompt),
        "classes": sorted({node["class_type"] for node in prompt.values()}),
        "missing_links": missing_links(prompt),
        "files": referenced_files(prompt),
    }


def node_ids(prompt: Prompt) -> Iterable[str]:
    return prompt.keys()
