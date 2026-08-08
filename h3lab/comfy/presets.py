"""Named strength levels for the cache and attention nodes, and the rules they must obey.

The two families share widget names (`start_percent`, `end_percent`), so they are always
expanded separately and applied to their own node. Mixing them once made an attention
window silently overwrite a cache window.

Every bound below is copied from the installed node's `INPUT_TYPES`, and the Spectrum
cross-field rules from its `SpectrumH3Config.validate`. The node checks them itself, but
only once it holds the GPU — so a graph that patches cleanly can still die minutes in.
Checking here turns that into a dry-run answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from h3lab.domain.config import CachePreset, GenerationConfig

EASY: Final[dict[str, dict[str, Any]]] = {
    "conservative": {"reuse_threshold": 0.1, "start_percent": 0.3, "end_percent": 0.8},
    "moderate": {"reuse_threshold": 0.2, "start_percent": 0.15, "end_percent": 0.95},
    "aggressive": {"reuse_threshold": 0.35, "start_percent": 0.1, "end_percent": 0.98},
}

H3: Final[dict[str, dict[str, Any]]] = {
    "conservative": {
        "reuse_threshold": 0.03,
        "start_percent": 0.2,
        "end_percent": 0.85,
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
        "start_percent": 0.1,
        "end_percent": 0.95,
        "max_steps": 4,
    },
}

# The endpoints are `CONSERVATIVE_PRESET` and `AGGRESSIVE_PRESET` from the node's own
# config.py, verbatim; moderate sits between them. The upgraded node ties `degree` to
# `warmup_steps` and `flex_window`: a higher-degree fit needs more real points before it can
# forecast anything, so a stronger level warms up *longer*, not shorter. It also refuses the
# one-point bootstrap for any degree above 1, which is why only conservative keeps it.
SPECTRUM: Final[dict[str, dict[str, Any]]] = {
    "conservative": {
        "enabled": True,
        "blend_weight": 0.5,
        "degree": 1,
        "flex_window": 0.75,
        "warmup_steps": 1,
        "tail_actual_steps": 1,
        "max_history": 8,
        "bootstrap_first_forecast": True,
    },
    "moderate": {
        "enabled": True,
        "blend_weight": 0.6,
        "degree": 2,
        "flex_window": 1.75,
        "warmup_steps": 3,
        "tail_actual_steps": 1,
        "max_history": 8,
        "bootstrap_first_forecast": False,
    },
    "aggressive": {
        "enabled": True,
        "blend_weight": 0.75,
        "degree": 4,
        "flex_window": 3.0,
        "warmup_steps": 5,
        "tail_actual_steps": 1,
        "max_history": 8,
        "bootstrap_first_forecast": False,
    },
}

SOL: Final[dict[str, dict[str, Any]]] = {
    "conservative": {"tau": 1.0, "start_percent": 0.3, "end_percent": 0.85},
    "moderate": {"tau": 1.5, "start_percent": 0.2, "end_percent": 0.9},
    "aggressive": {"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95},
}

CACHE_TABLES: Final[dict[str, dict[str, dict[str, Any]]]] = {
    "easy": EASY,
    "h3": H3,
    "spectrum": SPECTRUM,
}

CACHE_WIDGET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "reuse_threshold",
        "start_percent",
        "end_percent",
        "max_steps",
        "warmup_steps",
        "blend_weight",
        "enabled",
        "degree",
        "ridge_lambda",
        "window_size",
        "flex_window",
        "tail_actual_steps",
        "max_history",
        "verbose",
        "bootstrap_first_forecast",
        "history_storage",
        "debug",
        "device",
    }
)

SOL_WIDGET_KEYS: Final[frozenset[str]] = frozenset(
    {
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
    }
)


@dataclass(frozen=True, slots=True)
class Bound:
    """One widget's accepted range, as the node declares it."""

    low: float
    high: float | None = None
    whole: bool = False

    def describe(self, key: str) -> str:
        if self.high is not None:
            return f"{key} must be between {_plain(self.low)} and {_plain(self.high)}"
        if self.whole:
            return f"{key} must be a whole number of {_plain(self.low)} or more"
        return f"{key} must be {_plain(self.low)} or more"


def _plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


_PERCENT = Bound(0.0, 1.0)

BOUNDS: Final[dict[str, dict[str, Bound]]] = {
    "easy": {
        "reuse_threshold": Bound(0.0, 3.0),
        "start_percent": _PERCENT,
        "end_percent": _PERCENT,
    },
    "h3": {
        "reuse_threshold": _PERCENT,
        "start_percent": _PERCENT,
        "end_percent": _PERCENT,
        "max_steps": Bound(1, 10, whole=True),
    },
    "spectrum": {
        "blend_weight": _PERCENT,
        "degree": Bound(1, whole=True),
        "ridge_lambda": Bound(0.0),
        "window_size": Bound(1.0),
        "flex_window": Bound(0.0),
        "warmup_steps": Bound(0, 64, whole=True),
        "tail_actual_steps": Bound(0, 64, whole=True),
        "max_history": Bound(2, 64, whole=True),
    },
    "sol": {
        "tau": Bound(0.0, 4.0),
        "start_percent": _PERCENT,
        "end_percent": _PERCENT,
        "min_tokens": Bound(0, 1048576, whole=True),
    },
}

CHOICES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "h3": {"device": ("auto", "cuda", "cpu")},
    "spectrum": {"history_storage": ("system_ram", "vram")},
}

FLAGS: Final[dict[str, frozenset[str]]] = {
    "easy": frozenset({"verbose"}),
    "h3": frozenset({"verbose"}),
    "spectrum": frozenset({"enabled", "debug", "bootstrap_first_forecast"}),
    "sol": frozenset({"int8_qk", "morton", "verbose", "use_tma"}),
}


def _range_problems(widgets: dict[str, Any], family: str) -> list[str]:
    problems: list[str] = []
    for key, bound in BOUNDS.get(family, {}).items():
        if key not in widgets:
            continue
        value = widgets[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{key} must be a number")
        elif bound.whole and not float(value).is_integer():
            problems.append(f"{key} must be a whole number")
        elif value < bound.low or (bound.high is not None and value > bound.high):
            problems.append(bound.describe(key))
    for key, options in CHOICES.get(family, {}).items():
        if key in widgets and widgets[key] not in options:
            problems.append(f"{key} must be {' or '.join(options)}")
    for key in sorted(FLAGS.get(family, frozenset())):
        if key in widgets and not isinstance(widgets[key], bool):
            problems.append(f"{key} must be true or false")
    return problems


def _spectrum_problems(widgets: dict[str, Any]) -> list[str]:
    """The cross-field rules from `SpectrumH3Config.validate`, in the node's own words."""
    problems: list[str] = []
    degree = widgets.get("degree")
    warmup = widgets.get("warmup_steps")
    history = widgets.get("max_history")
    if widgets.get("bootstrap_first_forecast") is True:
        if isinstance(degree, int) and degree != 1:
            problems.append("bootstrap_first_forecast requires degree == 1")
        if isinstance(warmup, (int, float)) and warmup > 1:
            problems.append("bootstrap_first_forecast requires warmup_steps <= 1")
    if isinstance(degree, int) and isinstance(history, int):
        needed = max(2, degree + 1)
        if history < needed:
            problems.append(f"max_history must be at least {needed} for degree {degree}")
    return problems


def _window_problems(widgets: dict[str, Any]) -> list[str]:
    """A window that closes before it opens never caches, and never says so."""
    start = widgets.get("start_percent")
    end = widgets.get("end_percent")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start >= end:
        return [f"start_percent {_plain(start)} is not before end_percent {_plain(end)}"]
    return []


def cache_problems(widgets: dict[str, Any], *, family: str) -> list[str]:
    """Everything the node would reject about these widget values.

    Reporting beats coercing. Rewriting a widget to keep a run alive would store a config
    that differs from the one the GPU saw, and every comparison the lab draws assumes those
    are the same thing.
    """
    if not widgets:
        return []
    problems = _range_problems(widgets, family)
    if family == "spectrum":
        problems += _spectrum_problems(widgets)
    else:
        problems += _window_problems(widgets)
    return problems


def cache_widgets(config: GenerationConfig) -> dict[str, Any]:
    """Widget values for the active cache node, or ``{}`` when caching is off."""
    if not config.cache_active:
        return {}
    custom = {key: value for key, value in config.widgets.items() if key in CACHE_WIDGET_KEYS}
    if config.cache_preset == "custom":
        return custom
    table = CACHE_TABLES.get(config.cache)
    if table is None:
        return {}
    values = dict(table.get(config.cache_preset, {}))
    # Custom overrides still win on top of a named level: the sliders are the user's
    # last word about what they wanted to test.
    values.update(custom)
    return values


def sol_widgets(config: GenerationConfig) -> dict[str, Any]:
    """Widget values for the attention patch node, or ``{}`` when it is off."""
    if not config.sol_attn:
        return {}
    if config.sol_preset == "custom":
        return {key: value for key, value in config.widgets.items() if key in SOL_WIDGET_KEYS}
    values = dict(SOL.get(config.sol_preset, {}))
    values.update({key: value for key, value in config.widgets.items() if key in SOL_WIDGET_KEYS})
    return values


def preset_values(family: str, preset: CachePreset) -> dict[str, Any]:
    """The raw table entry, for the UI to show what a named level actually means."""
    if family == "sol":
        return dict(SOL.get(preset, {}))
    return dict(CACHE_TABLES.get(family, {}).get(preset, {}))
