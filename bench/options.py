"""Fetch ComfyUI sampler/scheduler lists via object_info, with TTL cache + fallbacks."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from bench.constants import (
    DEFAULT_FIRST_FRAME,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    FALLBACK_SAMPLERS,
    FALLBACK_SCHEDULERS,
    GGUF_UNET,
    INT8_UNET,
    NVFP4_UNET,
)
from bench.diffusion_models import default_diffusion_model, list_diffusion_models

_cache: dict[str, Any] = {"t": 0.0, "data": None}
_TTL = 60.0

_DEFAULTS = {
    "scheduler": DEFAULT_SCHEDULER,
    "sampler": DEFAULT_SAMPLER,
    "seed": 42,
    "steps": 20,
    "mp": 0.5,
    "duration_s": 5,
    "first_frame": DEFAULT_FIRST_FRAME,
}


def _diffusion_block() -> dict[str, Any]:
    """Scan local diffusion_models dir (always, independent of Comfy reachability)."""
    names = list_diffusion_models()
    if not names:
        # Constants fallback so the UI still has something selectable offline
        names = [NVFP4_UNET, INT8_UNET, GGUF_UNET]
        source = "fallback"
    else:
        source = "disk"
    default = default_diffusion_model(names)
    return {
        "diffusion_models": names,
        "diffusion_models_source": source,
        "defaults_extra": {"diffusion_model": default},
    }


def fetch_comfy_options(comfy_url: str, timeout: float = 3.0) -> dict[str, Any]:
    """Return scheduler/sampler lists from Comfy object_info, or constants fallbacks.

    Also always attaches MiniMax-H3 diffusion model basenames from the local
    models directory (see ``DIFFUSION_MODELS_DIR``).

    Cached for 60s. On any fetch/parse failure, returns FALLBACK_* with source="fallback".
    """
    now = time.time()
    if _cache["data"] is not None and now - _cache["t"] < _TTL:
        return _cache["data"]
    base = comfy_url.rstrip("/")
    diff = _diffusion_block()
    try:
        sched = _combo(f"{base}/object_info/BasicScheduler", "scheduler", timeout)
        samp = _combo(f"{base}/object_info/KSamplerSelect", "sampler_name", timeout)
        if not sched or not samp:
            raise RuntimeError("empty combo")
        defaults = dict(_DEFAULTS)
        defaults.update(diff["defaults_extra"])
        data = {
            "schedulers": sched,
            "samplers": samp,
            "source": "comfy",
            "defaults": defaults,
            "diffusion_models": diff["diffusion_models"],
            "diffusion_models_source": diff["diffusion_models_source"],
        }
    except Exception:
        defaults = dict(_DEFAULTS)
        defaults.update(diff["defaults_extra"])
        data = {
            "schedulers": list(FALLBACK_SCHEDULERS),
            "samplers": list(FALLBACK_SAMPLERS),
            "source": "fallback",
            "defaults": defaults,
            "diffusion_models": diff["diffusion_models"],
            "diffusion_models_source": diff["diffusion_models_source"],
        }
    _cache["t"] = now
    _cache["data"] = data
    return data


def clear_options_cache() -> None:
    """Reset TTL cache (for tests)."""
    _cache["t"] = 0.0
    _cache["data"] = None


def _combo(url: str, field: str, timeout: float) -> list[str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        info = json.loads(resp.read().decode())
    # object_info/{Node} → input.required[field] is a combo descriptor.
    # Legacy Comfy:  [[ "opt1", "opt2", ... ], { ... }]
    # Current Comfy: [ "COMBO", { "options": [ "opt1", ... ], "multiselect": false } ]
    node = next(iter(info.values()))
    spec = node["input"]["required"][field]
    return _parse_combo_spec(spec)


def _parse_combo_spec(spec: Any) -> list[str]:
    """Extract option strings from a ComfyUI combo input descriptor."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    head, *rest = spec
    # New format: ["COMBO", {"options": [...]}]
    if isinstance(head, str) and head.upper() == "COMBO":
        meta = rest[0] if rest else {}
        if isinstance(meta, dict):
            opts = meta.get("options") or meta.get("choices") or []
            return [str(x) for x in opts if x is not None and str(x)]
        return []
    # Legacy format: first element is the list of choices
    if isinstance(head, (list, tuple)):
        return [str(x) for x in head if x is not None and str(x)]
    # Single accidental string (would become letter-by-letter if list()'d)
    if isinstance(head, str):
        return []
    return []
