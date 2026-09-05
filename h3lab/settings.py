"""Runtime settings. Every filesystem path the lab touches resolves through here."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_COMFY_URL = "https://olares.hake-skink.ts.net:8443"
DEFAULT_PORT = 8787
DEFAULT_HOST = "0.0.0.0"
if os.name == "nt":
    DEFAULT_MODELS_DIR = Path(r"E:\AI\Models\diffusion_models")
    DEFAULT_COMFY_INPUT_DIR = Path(r"C:\Users\ricar\Documents\ComfyUI\ComfyUI\input")
    DEFAULT_COMFY_WORKFLOW_DIR = DEFAULT_COMFY_INPUT_DIR.parent / "user" / "default" / "workflows"
else:
    DEFAULT_MODELS_DIR = Path.home() / "ComfyUI" / "models" / "diffusion_models"
    DEFAULT_COMFY_INPUT_DIR = Path.home() / "ComfyUI" / "input"
    DEFAULT_COMFY_WORKFLOW_DIR = Path.home() / "ComfyUI" / "user" / "default" / "workflows"

UNIFIED_WORKFLOW_NAME = "minimax_h3_unified_guided_dual.json"

_ENV_PREFIX = "H3LAB_"

# env suffix -> (attribute, coercion)
_ENV_FIELDS: dict[str, tuple[str, str]] = {
    "COMFY_URL": ("comfy_url", "str"),
    "HOST": ("host", "str"),
    "PORT": ("port", "int"),
    "DATA_DIR": ("data_dir", "path"),
    "MODELS_DIR": ("models_dir", "path"),
    "LORAS_DIR": ("loras_dir", "path"),
    "COMFY_INPUT_DIR": ("comfy_input_dir", "path"),
    "WORKFLOW_DIR": ("workflow_dir", "path"),
    "WEB_DIST": ("web_dist", "path"),
    "FFMPEG": ("ffmpeg", "str"),
    "FFPROBE": ("ffprobe", "str"),
    "COMFY_TIMEOUT_S": ("comfy_timeout_s", "float"),
}


def _coerce(kind: str, raw: str) -> Any:
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "path":
        return Path(raw).expanduser()
    return raw


@dataclass(frozen=True, slots=True)
class Settings:
    comfy_url: str = DEFAULT_COMFY_URL
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    data_dir: Path = REPO_ROOT / "results"
    models_dir: Path = DEFAULT_MODELS_DIR
    # None means the sibling of the diffusion models, which is where ComfyUI keeps LoRAs.
    loras_dir: Path | None = None
    comfy_input_dir: Path = DEFAULT_COMFY_INPUT_DIR
    workflow_dir: Path = DEFAULT_COMFY_WORKFLOW_DIR
    web_dist: Path = REPO_ROOT / "web" / "dist"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    comfy_timeout_s: float = 36000.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "h3lab.db"

    @property
    def diffusion_models_dir(self) -> Path:
        return self.models_dir

    @property
    def lora_models_dir(self) -> Path:
        return self.loras_dir or self.models_dir.parent / "loras"

    def workflow_path(self, _mode: str) -> Path:
        return self.workflow_dir / UNIFIED_WORKFLOW_NAME

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def posters_dir(self) -> Path:
        return self.data_dir / "posters"

    @property
    def strips_dir(self) -> Path:
        return self.data_dir / "strips"

    @property
    def legacy_db_path(self) -> Path:
        return self.data_dir / "benchmark.db"

    @property
    def legacy_videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def media_dirs(self) -> tuple[Path, ...]:
        return (self.data_dir, self.videos_dir, self.posters_dir, self.strips_dir)

    def ensure_dirs(self) -> None:
        for directory in self.media_dirs:
            directory.mkdir(parents=True, exist_ok=True)

    def with_overrides(self, **overrides: Any) -> Settings:
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **clean) if clean else self

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> Settings:
        """Build settings from ``H3LAB_*`` environment variables.

        Explicit ``overrides`` win over the environment, which wins over defaults.
        Malformed numeric values are ignored rather than crashing startup.
        """
        source = os.environ if env is None else env
        from_env: dict[str, Any] = {}
        for suffix, (attr, kind) in _ENV_FIELDS.items():
            raw = source.get(_ENV_PREFIX + suffix)
            if raw is None or raw == "":
                continue
            try:
                from_env[attr] = _coerce(kind, raw)
            except (TypeError, ValueError):
                continue
        if "workflow_dir" not in from_env and overrides.get("workflow_dir") is None:
            discovered = discover_comfy_workflow_dir()
            if discovered is not None:
                from_env["workflow_dir"] = discovered
        if "comfy_input_dir" not in from_env and overrides.get("comfy_input_dir") is None:
            discovered = discover_comfy_input_dir()
            if discovered is not None:
                from_env["comfy_input_dir"] = discovered
        if "models_dir" not in from_env and overrides.get("models_dir") is None:
            discovered = discover_models_dir()
            if discovered is not None:
                from_env["models_dir"] = discovered
        merged = {**from_env, **{k: v for k, v in overrides.items() if v is not None}}
        return cls(**merged)


def comfy_workflow_dir_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [
        DEFAULT_COMFY_WORKFLOW_DIR,
        Path("/mnt/c/Users/ricar/Documents/ComfyUI/ComfyUI/user/default/workflows"),
        Path("/home/kadobot/ComfyUI/user/default/workflows"),
        home / "Documents" / "ComfyUI" / "ComfyUI" / "user" / "default" / "workflows",
        home / "ComfyUI" / "user" / "default" / "workflows",
    ]


def discover_comfy_workflow_dir() -> Path | None:
    for candidate in comfy_workflow_dir_candidates():
        if candidate.is_dir():
            return candidate
    return None


def comfy_input_dir_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [
        home / "ComfyUI" / "input",
        home / "Documents" / "ComfyUI" / "ComfyUI" / "input",
        Path("/run/media/kadobot/12TB_P/Documents/ComfyUI/ComfyUI/input"),
        Path("/mnt/c/Users/ricar/Documents/ComfyUI/ComfyUI/input"),
        DEFAULT_COMFY_INPUT_DIR,
        REPO_ROOT / "inputs",
    ]


def discover_comfy_input_dir() -> Path | None:
    for candidate in comfy_input_dir_candidates():
        if candidate.is_dir():
            return candidate
    return None


def models_dir_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [
        home / "ComfyUI" / "models" / "diffusion_models",
        Path("/run/media/kadobot/12TB_P/Documents/ComfyUI/ComfyUI/models/diffusion_models"),
        home / "Documents" / "ComfyUI" / "ComfyUI" / "models" / "diffusion_models",
        Path("/mnt/c/Users/ricar/Documents/ComfyUI/ComfyUI/models/diffusion_models"),
        DEFAULT_MODELS_DIR,
    ]


def discover_models_dir() -> Path | None:
    for candidate in models_dir_candidates():
        if candidate.is_dir():
            return candidate
    return None
