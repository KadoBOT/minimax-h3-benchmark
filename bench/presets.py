from __future__ import annotations

from typing import Any

from bench.models import RunConfig

# Values: moderate = v3 workflow widgets; cons/aggr from prior design tables
EASY = {
    "conservative": {"reuse_threshold": 0.1, "start_percent": 0.3, "end_percent": 0.8},
    "moderate": {"reuse_threshold": 0.2, "start_percent": 0.15, "end_percent": 0.95},
    "aggressive": {"reuse_threshold": 0.35, "start_percent": 0.2, "end_percent": 0.9},
}
H3 = {
    "conservative": {
        "reuse_threshold": 0.03,
        "start_percent": 0.15,
        "end_percent": 0.9,
        "max_steps": 1,
    },
    "moderate": {
        "reuse_threshold": 0.05,
        "start_percent": 0.15,
        "end_percent": 0.9,
        "max_steps": 2,
    },
    "aggressive": {
        "reuse_threshold": 0.1,
        "start_percent": 0.15,
        "end_percent": 0.9,
        "max_steps": 3,
    },
}
SPECTRUM = {
    "conservative": {"warmup_steps": 8, "blend_weight": 0.3, "enabled": True},
    "moderate": {"warmup_steps": 5, "blend_weight": 0.5, "enabled": True},
    "aggressive": {"warmup_steps": 3, "blend_weight": 0.7, "enabled": True},
}
SOL = {
    "conservative": {"tau": 1.0, "start_percent": 0.3, "end_percent": 0.85},
    "moderate": {"tau": 1.5, "start_percent": 0.2, "end_percent": 0.9},
    "aggressive": {"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95},
}

_CACHE_KEYS = {
    "reuse_threshold",
    "start_percent",
    "end_percent",
    "max_steps",
    "warmup_steps",
    "blend_weight",
    "enabled",
    "degree",
    "verbose",
}
_SOL_KEYS = {"tau", "start_percent", "end_percent", "min_tokens", "int8_qk", "verbose"}


def expand_presets(cfg: RunConfig) -> dict[str, Any]:
    """Return flat widget overrides for active cache + sol (if enabled)."""
    out: dict[str, Any] = {}
    if cfg.cache_enabled and cfg.cache != "none":
        if cfg.cache_preset == "custom":
            out.update({k: v for k, v in (cfg.widgets or {}).items() if k in _CACHE_KEYS})
        else:
            table = {"easy": EASY, "h3": H3, "spectrum": SPECTRUM}[cfg.cache]
            out.update(table[cfg.cache_preset])
    if cfg.sol_attn:
        if cfg.sol_preset == "custom":
            out.update({k: v for k, v in (cfg.widgets or {}).items() if k in _SOL_KEYS})
        else:
            out.update(SOL[cfg.sol_preset])
    return out
