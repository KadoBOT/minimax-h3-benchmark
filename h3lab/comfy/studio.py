"""Versioned MiniMax H3 Studio contract boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from h3lab.comfy.graph import build
from h3lab.comfy.schema import Schemas
from h3lab.comfy.workflow import Graph, Prompt, executable
from h3lab.domain.config import DEFAULT_ASPECT, GenerationConfig

STUDIO_CONTRACT_VERSION = 1
STUDIO_UI_SCHEMA_VERSION = 1
STUDIO_TEMPLATE_CATALOG_VERSION = 2
STUDIO_SUPPORTED_TEMPLATE_CATALOG_VERSIONS = {1, 2}
STUDIO_API_ROOT = "/minimax_h3_studio/v1"
STUDIO_CLASS = "MiniMaxH3Studio"
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


def find_studio_node(
    workflow: Mapping[str, Any],
    *,
    required: bool = True,
) -> tuple[str, Mapping[str, Any]] | None:
    found = [
        (str(node_id), node)
        for node_id, node in workflow.items()
        if isinstance(node, Mapping) and node.get("class_type") == STUDIO_CLASS
    ]
    if len(found) == 1:
        return found[0]
    if not found and not required:
        return None
    if not found:
        raise StudioContractError(
            "studio_node_missing",
            f"workflow has no {STUDIO_CLASS} node",
        )
    raise StudioContractError(
        "studio_node_ambiguous",
        f"workflow has {len(found)} {STUDIO_CLASS} nodes",
        {"node_ids": [node_id for node_id, _node in found]},
    )


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
    for field in ("module_url", "prepare_url"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise StudioContractError(
                "contract_unavailable",
                f"Studio manifest has no {field}",
            )
    ui_schema = payload.get("ui_schema")
    if not isinstance(ui_schema, Mapping):
        raise StudioContractError(
            "contract_unavailable",
            "Studio manifest has no UI schema",
        )
    if ui_schema.get("version") != STUDIO_UI_SCHEMA_VERSION:
        raise StudioContractError(
            "contract_unavailable",
            f"unsupported Studio UI schema version {ui_schema.get('version')!r}; "
            f"expected {STUDIO_UI_SCHEMA_VERSION}",
        )
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
    find_studio_node(prompt)
    return prompt


def _studio_json(value: Any, fallback: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else fallback, separators=(",", ":"))


def studio_inputs(config: GenerationConfig) -> dict[str, Any]:
    references = {
        "images": list(config.ref_images),
        "videos": list(config.ref_videos),
        "video_audios": list(config.ref_video_audios),
        "audios": list(config.ref_audios),
    }
    extras = {
        name: _studio_json(value, []) if name == "guides" else value
        for name, value in config.widgets.items()
    }
    mapped = {
        "mode": _MODE_TO_STUDIO[config.mode],
        "prompt": config.prompt,
        "duration": config.duration_s,
        "aspect_ratio": config.aspect_ratio or DEFAULT_ASPECT,
        "megapixels": config.mp,
        "ref_image_size": config.ref_image_size,
        "first_frame": config.first_frame,
        "last_frame": config.last_frame,
        "references": json.dumps(references, separators=(",", ":")),
        "steps": config.effective_steps,
        "turbo": config.turbo,
        "turbo_lora": config.turbo_lora_file or "none",
        "scheduler": config.scheduler,
        "sampler_name": config.sampler,
        "cache": config.cache_active,
        "upscale_ltx": False,
        "upscale_rtx": config.upscaler,
        "seed_mode": "fixed",
        "seed": config.seed,
        "interpolation": _INTERP_TO_STUDIO.get(config.interp, config.interp),
        "clean_vram": config.clean_vram,
        "sol_attn": config.sol_attn,
        "guides": _studio_json(config.widgets.get("guides"), []),
    }
    for name in ("seed_mode", "upscale_ltx"):
        if name in extras:
            mapped[name] = extras.pop(name)
    explicit_attention = config.widgets.get("attn")
    if explicit_attention is None:
        extras.pop("attn", None)
    return {**extras, **mapped}


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


def prepare_prompt(
    client: Any,
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    schemas: Schemas,
    output_tag: str = "run",
) -> PreparedPrompt:
    prompt, graph, _roles = build(
        workflow,
        config,
        output_tag=output_tag,
        schemas=schemas,
    )
    find_studio_node(prompt)
    result = client.prepare_studio(prompt, studio_inputs(config))
    return PreparedPrompt(
        prompt=result["workflow"],
        graph=graph,
        inputs=result["inputs"],
    )
