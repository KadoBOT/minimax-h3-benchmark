"""What the lab can choose from: model files, input media, sampler and scheduler lists.

Every lookup degrades instead of failing. A ComfyUI that is down or a models folder on an
unplugged drive leaves the form usable with known-good defaults, and says which parts are
guesses via the `source` fields.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from h3lab.comfy.client import ComfyClient, ComfyError
from h3lab.domain.config import (
    BASELINE_FIRST_FRAME,
    BASELINE_PROMPT,
    BASELINE_REF_IMAGES,
    DEFAULT_ASPECT,
    DEFAULT_GGUF_UNET,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    DEFAULT_UNET,
    GEN_MODES,
    MAX_REF_AUDIOS,
    MAX_REF_IMAGES,
    MAX_REF_VIDEOS,
    PRESET_LEVELS,
)
from h3lab.settings import Settings

FALLBACK_SCHEDULERS: Final[tuple[str, ...]] = (
    "simple",
    "sgm_uniform",
    "karras",
    "exponential",
    "ddim_uniform",
    "beta",
    "normal",
    "linear_quadratic",
    "kl_optimal",
    "beta57",
)

FALLBACK_SAMPLERS: Final[tuple[str, ...]] = (
    "euler",
    "euler_cfg_pp",
    "euler_ancestral",
    "heun",
    "dpmpp_2m",
    "dpmpp_2m_sde",
    "dpmpp_sde",
    "ddim",
    "uni_pc",
    "res_multistep",
)

FALLBACK_ASPECTS: Final[tuple[str, ...]] = (
    "16:9 (Widescreen)",
    "9:16 (Portrait)",
    "1:1 (Square)",
    "4:3 (Standard)",
    "3:4 (Portrait)",
    "21:9 (Cinemascope)",
)

MODEL_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".safetensors", ".gguf", ".sft", ".ckpt", ".pt", ".pth"}
)
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
)
VIDEO_SUFFIXES: Final[frozenset[str]] = frozenset({".mp4", ".webm", ".mkv", ".mov", ".avi"})
AUDIO_SUFFIXES: Final[frozenset[str]] = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a"})

_MINIMAX = re.compile(r"minimax", re.IGNORECASE)
_H3 = re.compile(r"h3", re.IGNORECASE)

CACHE_TTL_S = 45.0


def is_h3_model(name: str) -> bool:
    return bool(_MINIMAX.search(name) and _H3.search(name))


def _listdir(directory: Path, suffixes: frozenset[str], *, limit: int = 4000) -> list[str]:
    if not directory.is_dir():
        return []
    names: list[str] = []
    try:
        for entry in directory.iterdir():
            if not entry.is_file() or entry.suffix.lower() not in suffixes:
                continue
            names.append(entry.name)
            if len(names) >= limit:
                break
    except OSError:
        return []
    return sorted(names, key=str.lower)


def list_models(directory: Path) -> list[str]:
    return [name for name in _listdir(directory, MODEL_SUFFIXES) if is_h3_model(name)]


def default_model(names: list[str]) -> str:
    if DEFAULT_UNET in names:
        return DEFAULT_UNET
    for name in names:
        lowered = name.lower()
        if lowered.endswith(".safetensors") and "nvfp4" in lowered:
            return name
    for name in names:
        if name.lower().endswith(".safetensors"):
            return name
    return names[0] if names else DEFAULT_UNET


def default_first_frame(images: list[str]) -> str:
    """The baseline still if it is here, otherwise anything, otherwise nothing.

    Falling back to an arbitrary image is still worth doing: the frame modes require one, so
    a form that arrives with a file already chosen is a form you can queue.
    """
    if BASELINE_FIRST_FRAME in images:
        return BASELINE_FIRST_FRAME
    return images[0] if images else ""


def default_ref_images(images: list[str]) -> list[str]:
    """The baseline reference set, in its authored order, and only if all of it is here.

    Unlike a first frame, references say what to generate rather than where to start, so a
    partial set is not a weaker default but a different subject — and an arbitrary substitute
    would produce a confidently wrong video instead of an obviously empty form.
    """
    present = [name for name in BASELINE_REF_IMAGES if name in images]
    return present[:MAX_REF_IMAGES] if len(present) == len(BASELINE_REF_IMAGES) else []


class Catalog(BaseModel):
    """Everything a run form needs to render, with the provenance of each list."""

    model_config = ConfigDict(frozen=True)

    comfy_online: bool
    comfy_url: str
    source: str  # "comfy" or "fallback"

    schedulers: list[str]
    samplers: list[str]
    aspect_ratios: list[str]

    diffusion_models: list[str]
    diffusion_models_source: str
    default_diffusion_model: str

    images: list[str]
    videos: list[str]
    audios: list[str]
    media_source: str
    default_first_frame: str = ""
    default_ref_images: list[str] = []

    modes: list[str] = list(GEN_MODES)
    preset_levels: list[str] = list(PRESET_LEVELS)
    reference_limits: dict[str, int] = {
        "images": MAX_REF_IMAGES,
        "videos": MAX_REF_VIDEOS,
        "audios": MAX_REF_AUDIOS,
    }
    defaults: dict[str, Any] = {}


def _comfy_lists(client: ComfyClient) -> tuple[list[str], list[str], list[str]] | None:
    try:
        schedulers = client.combo_options("BasicScheduler", "scheduler")
        samplers = client.combo_options("KSamplerSelect", "sampler_name")
        aspects = client.combo_options("ResolutionSelector", "aspect_ratio")
    except ComfyError:
        return None
    if not schedulers or not samplers:
        return None
    return schedulers, samplers, aspects or list(FALLBACK_ASPECTS)


def build_catalog(settings: Settings, client: ComfyClient | None = None) -> Catalog:
    owned = client is None
    client = client or ComfyClient(settings.comfy_url)
    try:
        lists = _comfy_lists(client)
    finally:
        if owned:
            client.close()

    models = list_models(settings.diffusion_models_dir)
    models_source = "disk"
    if not models:
        models = [DEFAULT_UNET, DEFAULT_GGUF_UNET]
        models_source = "fallback"

    images = _listdir(settings.comfy_input_dir, IMAGE_SUFFIXES)
    videos = _listdir(settings.comfy_input_dir, VIDEO_SUFFIXES)
    audios = _listdir(settings.comfy_input_dir, AUDIO_SUFFIXES)
    media_source = "disk" if settings.comfy_input_dir.is_dir() else "unavailable"

    chosen_model = default_model(models)
    first_frame = default_first_frame(images)
    ref_images = default_ref_images(images)

    defaults: dict[str, Any] = {
        "mode": "flf2v" if first_frame else "t2v",
        "diffusion_model": chosen_model,
        "prompt": BASELINE_PROMPT,
        "first_frame": first_frame,
        "last_frame": "",
        "ref_images": ref_images,
        "scheduler": DEFAULT_SCHEDULER,
        "sampler": DEFAULT_SAMPLER,
        "aspect_ratio": DEFAULT_ASPECT,
        "steps": 20,
        "seed": 42,
        "mp": 0.5,
        "duration_s": 5.0,
        "cache_enabled": True,
        "cache": "spectrum",
        "cache_preset": "moderate",
        "sol_attn": True,
        "sol_preset": "moderate",
    }

    if lists is None:
        return Catalog(
            comfy_online=False,
            comfy_url=settings.comfy_url,
            source="fallback",
            schedulers=list(FALLBACK_SCHEDULERS),
            samplers=list(FALLBACK_SAMPLERS),
            aspect_ratios=list(FALLBACK_ASPECTS),
            diffusion_models=models,
            diffusion_models_source=models_source,
            default_diffusion_model=chosen_model,
            images=images,
            videos=videos,
            audios=audios,
            media_source=media_source,
            default_first_frame=first_frame,
            default_ref_images=ref_images,
            defaults=defaults,
        )

    schedulers, samplers, aspects = lists
    # Prefer a default the running instance actually offers.
    if DEFAULT_SCHEDULER not in schedulers and schedulers:
        defaults["scheduler"] = schedulers[0]
    if DEFAULT_SAMPLER not in samplers and samplers:
        defaults["sampler"] = samplers[0]
    if DEFAULT_ASPECT not in aspects and aspects:
        defaults["aspect_ratio"] = aspects[0]

    return Catalog(
        comfy_online=True,
        comfy_url=settings.comfy_url,
        source="comfy",
        schedulers=schedulers,
        samplers=samplers,
        aspect_ratios=aspects,
        diffusion_models=models,
        diffusion_models_source=models_source,
        default_diffusion_model=chosen_model,
        images=images,
        videos=videos,
        audios=audios,
        media_source=media_source,
        default_first_frame=first_frame,
        default_ref_images=ref_images,
        defaults=defaults,
    )


class CatalogCache:
    """Short-lived cache so a page full of components does not rescan a network drive."""

    def __init__(self, settings: Settings, *, ttl_s: float = CACHE_TTL_S) -> None:
        self._settings = settings
        self._ttl = ttl_s
        self._lock = threading.Lock()
        self._value: Catalog | None = None
        self._stamp = 0.0

    def get(self, *, refresh: bool = False) -> Catalog:
        with self._lock:
            fresh = self._value is not None and (time.monotonic() - self._stamp) < self._ttl
            if fresh and not refresh:
                return self._value  # type: ignore[return-value]
        value = build_catalog(self._settings)
        with self._lock:
            self._value = value
            self._stamp = time.monotonic()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._stamp = 0.0
