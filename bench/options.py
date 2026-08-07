"""Fetch ComfyUI sampler/scheduler lists via object_info, with TTL cache + fallbacks."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from bench.constants import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    FALLBACK_SAMPLERS,
    FALLBACK_SCHEDULERS,
)

_cache: dict[str, Any] = {"t": 0.0, "data": None}
_TTL = 60.0

_DEFAULTS = {
    "scheduler": DEFAULT_SCHEDULER,
    "sampler": DEFAULT_SAMPLER,
    "seed": 42,
    "steps": 20,
    "mp": 0.5,
    "duration_s": 5,
}


def fetch_comfy_options(comfy_url: str, timeout: float = 3.0) -> dict[str, Any]:
    """Return scheduler/sampler lists from Comfy object_info, or constants fallbacks.

    Cached for 60s. On any fetch/parse failure, returns FALLBACK_* with source="fallback".
    """
    now = time.time()
    if _cache["data"] is not None and now - _cache["t"] < _TTL:
        return _cache["data"]
    base = comfy_url.rstrip("/")
    try:
        sched = _combo(f"{base}/object_info/BasicScheduler", "scheduler", timeout)
        samp = _combo(f"{base}/object_info/KSamplerSelect", "sampler_name", timeout)
        if not sched or not samp:
            raise RuntimeError("empty combo")
        data = {
            "schedulers": sched,
            "samplers": samp,
            "source": "comfy",
            "defaults": dict(_DEFAULTS),
        }
    except Exception:
        data = {
            "schedulers": list(FALLBACK_SCHEDULERS),
            "samplers": list(FALLBACK_SAMPLERS),
            "source": "fallback",
            "defaults": dict(_DEFAULTS),
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
    # object_info/{Node} → { "BasicScheduler": { "input": { "required": { field: [[...], {...}] }}}}
    node = next(iter(info.values()))
    raw = node["input"]["required"][field][0]
    return list(raw)
