"""Runtime settings. Every filesystem path the lab touches resolves through here."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_PORT = 8787
DEFAULT_HOST = "0.0.0.0"
DEFAULT_MODELS_DIR = Path(r"E:\AI\Models\diffusion_models")
DEFAULT_COMFY_INPUT_DIR = Path(r"C:\Users\ricar\Documents\ComfyUI\ComfyUI\input")

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
    workflow_dir: Path = REPO_ROOT
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

    def workflow_path(self, mode: str) -> Path:
        """The editor workflow template for a generation mode."""
        return self.workflow_dir / f"minimax_h3_{mode}_workflow.json"

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
        merged = {**from_env, **{k: v for k, v in overrides.items() if v is not None}}
        return cls(**merged)
