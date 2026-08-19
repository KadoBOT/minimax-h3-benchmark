"""Persistence bindings between Studio inputs and benchmark configuration."""

from __future__ import annotations

import copy
from typing import Any


STUDIO_BINDINGS: dict[str, dict[str, Any]] = {
    "mode": {
        "key": "mode",
        "store": "config",
        "values": {"T2V": "t2v", "FLF2V": "flf2v", "R2V": "r2v"},
    },
    "duration": {"key": "duration_s", "store": "config"},
    "megapixels": {"key": "mp", "store": "config"},
    "sampler_name": {"key": "sampler", "store": "config"},
    "cache": {"key": "cache_enabled", "store": "config"},
    "interpolation": {
        "key": "interp",
        "store": "config",
        "values": {"none": "off"},
    },
    "upscale_rtx": {"key": "upscaler", "store": "config"},
    "references": {"key": "references", "store": "references"},
}


def studio_bindings() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(STUDIO_BINDINGS)
