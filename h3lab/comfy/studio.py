"""Versioned MiniMax H3 Studio contract boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from h3lab.comfy.schema import Schemas
from h3lab.comfy.experiment import apply_experiment
from h3lab.comfy.workflow import Graph, Prompt, executable, read
from h3lab.domain.config import DEFAULT_ASPECT, GenerationConfig

STUDIO_CONTRACT_VERSION = 1
STUDIO_UI_SCHEMA_VERSION = 1
STUDIO_TEMPLATE_CATALOG_VERSION = 2
STUDIO_SUPPORTED_TEMPLATE_CATALOG_VERSIONS = {1, 2}
STUDIO_API_ROOT = "/h3_clean/v1"
_MODE_TO_STUDIO = {"t2v": "T2V", "flf2v": "FLF2V", "r2v": "R2V"}
_MODE_FROM_STUDIO = {value: key for key, value in _MODE_TO_STUDIO.items()}
_INTERP_TO_STUDIO = {"off": "none", "film": "film", "rife": "rife", "gmfss": "gmfss"}
_INTERP_FROM_STUDIO = {value: key for key, value in _INTERP_TO_STUDIO.items()}
_INPUT_FIELDS = {
    "prompt": "prompt",
    "duration": "duration_s",
    "aspect_ratio": "aspect_ratio",
    "megapixels": "mp",
    "ref_image_size": "ref_image_size",
    "first_frame": "first_frame",
    "last_frame": "last_frame",
    "steps": "steps",
    "turbo": "turbo",
    "turbo_lora": "turbo_lora",
    "turbo_lora_strength": "turbo_lora_strength",
    "scheduler": "scheduler",
    "sampler_name": "sampler",
    "upscale_rtx": "upscaler",
    "seed": "seed",
    "clean_vram": "clean_vram",
}
_CONNECTION_INPUTS = {"clip", "vae", "audio_vae", "opt_connections", "h3s_ui"}
_WIDGET_DEFAULTS = {"guides": "[]", "upscale_ltx": False, "seed_mode": "fixed"}


class StudioContractError(ValueError):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def validate_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise StudioContractError(
            "contract_unavailable",
            "Studio manifest response must be a JSON object",
        )
    version = payload.get("contract_version")
    if version != STUDIO_CONTRACT_VERSION:
        raise StudioContractError(
            "contract_unavailable",
            f"unsupported Studio contract version {version!r}; "
            f"expected {STUDIO_CONTRACT_VERSION}",
        )
    if not isinstance(payload.get("prepare_url"), str):
        raise StudioContractError("contract_unavailable", "H3 manifest has no prepare_url")
    template_catalog = payload.get("template_catalog")
    if template_catalog is not None:
        if not isinstance(template_catalog, Mapping):
            raise StudioContractError(
                "contract_unavailable",
                "Studio template catalog must be a JSON object",
            )
        if template_catalog.get("version") not in STUDIO_SUPPORTED_TEMPLATE_CATALOG_VERSIONS:
            raise StudioContractError(
                "contract_unavailable",
                f"unsupported Studio template catalog version "
                f"{template_catalog.get('version')!r}; "
                f"expected one of {sorted(STUDIO_SUPPORTED_TEMPLATE_CATALOG_VERSIONS)}",
            )
        if (
            not isinstance(template_catalog.get("categories"), list)
            or not isinstance(template_catalog.get("templates"), list)
        ):
            raise StudioContractError(
                "contract_unavailable",
                "Studio template catalog is malformed",
            )
    return dict(payload)


def validate_prepare_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise StudioContractError(
            "invalid_response",
            "Studio prepare response must be a JSON object",
        )
    if payload.get("contract_version") != STUDIO_CONTRACT_VERSION:
        raise StudioContractError(
            "contract_unavailable",
            "Studio prepare response has an unsupported contract version",
        )
    if not isinstance(payload.get("workflow"), Mapping):
        raise StudioContractError(
            "invalid_response",
            "Studio prepare response workflow must be a JSON object",
        )
    if not isinstance(payload.get("inputs"), Mapping):
        raise StudioContractError(
            "invalid_response",
            "Studio prepare response inputs must be a JSON object",
        )
    return dict(payload)


def response_error(payload: Any, *, fallback: str) -> StudioContractError:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if not isinstance(error, Mapping):
        return StudioContractError("studio_error", fallback)
    code = str(error.get("code") or "studio_error")
    message = str(error.get("message") or fallback)
    details = error.get("details")
    return StudioContractError(
        code,
        message,
        details if isinstance(details, Mapping) else None,
    )


def studio_session_prompt(
    workflow: dict[str, Any],
    schemas: Schemas,
) -> Prompt:
    """Flatten the live editor workflow using ordinary ComfyUI mode semantics."""
    prompt, _graph = executable(workflow, widget_names=schemas.widget_names)
    return prompt


def _studio_json(value: Any, fallback: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else fallback, separators=(",", ":"))


def studio_inputs(config: GenerationConfig) -> dict[str, Any]:
    guides = config.widgets.get("guides", [])
    if isinstance(guides, str):
        guides = json.loads(guides)
    return {
        "preset": config.preset,
        "prompt": config.prompt,
        "width": config.width,
        "height": config.height,
        "frames": config.frames,
        "seed": config.seed,
        "ref_image_size": config.ref_image_size,
        "first_frame": config.first_frame,
        "last_frame": config.last_frame,
        "references": {
            "images": list(config.ref_images), "videos": list(config.ref_videos),
            "video_audios": list(config.ref_video_audios), "audios": list(config.ref_audios),
        },
        "guides": guides,
        "final_audio": config.widgets.get("final_audio", ""),
    }


def _references(value: Any) -> dict[str, list[Any]]:
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StudioContractError(
                "invalid_inputs",
                "Studio references must be valid JSON",
            ) from exc
    if not isinstance(payload, Mapping):
        raise StudioContractError(
            "invalid_inputs",
            "Studio references must be an object",
        )
    return {
        "ref_images": list(payload.get("images") or []),
        "ref_videos": list(payload.get("videos") or []),
        "ref_video_audios": list(payload.get("video_audios") or []),
        "ref_audios": list(payload.get("audios") or []),
    }


def studio_patch(
    current: GenerationConfig,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    widget_patch: dict[str, Any] = {}

    for name, value in inputs.items():
        if name in _CONNECTION_INPUTS:
            continue
        if name == "mode":
            field, value = "mode", _MODE_FROM_STUDIO.get(value, value)
        elif name == "interpolation":
            field, value = "interp", _INTERP_FROM_STUDIO.get(value, value)
        elif name == "references":
            for field, references in _references(value).items():
                if list(getattr(current, field)) != references:
                    patch[field] = references
            continue
        elif name == "cache":
            enabled = bool(value)
            if enabled != current.cache_active:
                patch["cache_enabled"] = enabled
                patch["cache"] = (
                    current.cache if enabled and current.cache != "none" else
                    "spectrum" if enabled else "none"
                )
            continue
        elif name == "attn":
            if value not in {"off", "sol", "comfy_kitchen"}:
                raise StudioContractError(
                    "invalid_inputs",
                    f"unsupported attention mode {value!r}",
                )
            if current.widgets.get("attn") != value:
                widget_patch["attn"] = value
            if current.sol_attn != (value == "sol"):
                patch["sol_attn"] = value == "sol"
            continue
        elif name == "sol_attn":
            if "attn" not in inputs and current.sol_attn != bool(value):
                patch["sol_attn"] = bool(value)
            continue
        elif name in _INPUT_FIELDS:
            field = _INPUT_FIELDS[name]
            if name == "turbo_lora" and value == "none":
                value = ""
        elif name in GenerationConfig.model_fields and name not in {
            "widgets",
            "ref_images",
            "ref_videos",
            "ref_video_audios",
            "ref_audios",
        }:
            field = name
        else:
            if name not in current.widgets and _WIDGET_DEFAULTS.get(name) == value:
                continue
            if current.widgets.get(name) != value:
                widget_patch[name] = value
            continue

        if getattr(current, field) != value:
            patch[field] = value

    if widget_patch:
        patch["widgets"] = widget_patch
    return patch


@dataclass(frozen=True)
class PreparedPrompt:
    prompt: Prompt
    graph: Graph
    inputs: dict[str, Any]
    editor_workflow: dict[str, Any]


def prepare_prompt(
    client: Any,
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    schemas: Schemas,
    output_tag: str = "run",
) -> PreparedPrompt:
    inputs = {**studio_inputs(config), "filename_prefix": output_tag}
    result = client.prepare_studio({}, inputs)
    experiment = dict(config.experiment)
    value = experiment.get("diffusion_model")
    if value:
        loader = "UnetLoaderGGUF" if value.lower().endswith(".gguf") else "UNETLoader"
        candidates = schemas.combo(loader, "unet_name")
        relative = value.replace("\\", "/")
        matches = [name for name in candidates if name.replace("\\", "/").endswith("/" + relative)]
        if not matches:
            matches = [name for name in candidates if name.replace("\\", "/").split("/")[-1] == relative.split("/")[-1]]
        if value not in candidates and len(matches) == 1:
            experiment["diffusion_model"] = matches[0]
    prompt = apply_experiment(result["workflow"], experiment)
    return PreparedPrompt(prompt=prompt, graph=read(prompt), inputs={**result["inputs"], "experiment": experiment},
                          editor_workflow=result.get("editor_workflow", workflow))
