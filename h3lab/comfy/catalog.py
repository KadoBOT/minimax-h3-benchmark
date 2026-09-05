"""What the lab can choose from: model files, input media, sampler and scheduler lists.

Every lookup degrades instead of failing. A ComfyUI that is down or a models folder on an
unplugged drive leaves the form usable with known-good defaults, and says which parts are
guesses via the `source` fields.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Final, NamedTuple

from pydantic import BaseModel, ConfigDict

from h3lab.comfy.client import ComfyClient, ComfyError
from h3lab.domain.config import (
    BASELINE_FIRST_FRAME,
    BASELINE_GUIDES,
    BASELINE_PROMPT,
    BASELINE_REF_IMAGES,
    DEFAULT_ASPECT,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    DEFAULT_TURBO_LORA,
    DEFAULT_TURBO_STRENGTH,
    DEFAULT_UNET,
    GEN_MODES,
    GenerationConfig,
    MAX_REF_AUDIOS,
    MAX_REF_IMAGES,
    MAX_REF_VIDEOS,
    PRESET_LEVELS,
    turbo_steps_for,
)
from h3lab.settings import DEFAULT_COMFY_INPUT_DIR, REPO_ROOT, Settings

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
MINIMAX_H3_FOLDER: Final[str] = "minimax-h3"
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


def _in_minimax_h3_folder(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return normalized.lower().startswith(f"{MINIMAX_H3_FOLDER}/")


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
    folder = (
        directory
        if directory.name.lower() == MINIMAX_H3_FOLDER
        else directory / MINIMAX_H3_FOLDER
    )
    return [
        f"{MINIMAX_H3_FOLDER}/{name}"
        for name in _listdir(folder, MODEL_SUFFIXES)
    ]


def list_turbo_loras(directory: Path) -> list[str]:
    """The H3 LoRAs on disk. Same filter as the weights: this model's files, not every LoRA."""
    return [name for name in _listdir(directory, MODEL_SUFFIXES) if is_h3_model(name)]


def default_turbo_lora(names: list[str]) -> str:
    """The LoRA a turbo run starts from: the one the templates ship with, if it is here."""
    if DEFAULT_TURBO_LORA in names:
        return DEFAULT_TURBO_LORA
    return names[0] if names else DEFAULT_TURBO_LORA


class InstalledNameError(ValueError):
    """The run named a file ComfyUI will not load."""


def match_installed(wanted: str, offered: list[str], *, kind: str = "checkpoint") -> str:
    """The combo value ComfyUI will accept for this request.

    Combo values carry their folder (``minimax-h3/foo.safetensors``). A stored
    run or a fallback default often has only the basename. Match exact first,
    then the basename, case-insensitive. Never invent a different quant.
    """
    name = (wanted or "").strip()
    if not name:
        raise InstalledNameError(f"no {kind} was named")
    if name in offered:
        return name
    base = Path(name).name.lower()
    hits = [item for item in offered if Path(item).name.lower() == base]
    if len(hits) == 1:
        return hits[0]
    listed = ", ".join(offered) if offered else "(none)"
    raise InstalledNameError(
        f"{name} is not installed. ComfyUI's {kind} list is: {listed}"
    )


def resolve_run_weights(config: GenerationConfig, client: ComfyClient | None) -> GenerationConfig:
    """Rewrite stored names onto the combo values this ComfyUI will load.

    Offline, leave the config alone so a dry-run or a test fixture still builds.
    """
    if client is None:
        return config
    try:
        unets = _comfy_unets(client)
        loras = _comfy_loras(client) if config.turbo else []
    except ComfyError:
        return config
    updates: dict[str, Any] = {}
    if unets:
        wanted = (config.diffusion_model or "").strip()
        if not wanted or (wanted == DEFAULT_UNET and not any(wanted.lower() == Path(u).name.lower() for u in unets)):
            updates["diffusion_model"] = default_model(unets)
        else:
            try:
                updates["diffusion_model"] = match_installed(wanted, unets)
            except InstalledNameError:
                if wanted == DEFAULT_UNET or not wanted:
                    updates["diffusion_model"] = default_model(unets)
                else:
                    raise
    if config.turbo and loras:
        wanted_lora = (config.turbo_lora or "").strip()
        if not wanted_lora or (wanted_lora == DEFAULT_TURBO_LORA and not any(wanted_lora.lower() == Path(l).name.lower() for l in loras)):
            updates["turbo_lora"] = default_turbo_lora(loras)
        else:
            try:
                updates["turbo_lora"] = match_installed(config.turbo_lora_file, loras, kind="LoRA")
            except InstalledNameError:
                if wanted_lora == DEFAULT_TURBO_LORA or not wanted_lora:
                    updates["turbo_lora"] = default_turbo_lora(loras)
                else:
                    raise
    if not updates:
        return config
    if all(getattr(config, key) == value for key, value in updates.items()):
        return config
    return config.merged(**updates)


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
    return names[0] if names else ""


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

    turbo_loras: list[str] = []
    turbo_loras_source: str = "fallback"
    default_turbo_lora: str = DEFAULT_TURBO_LORA
    # The schedule each LoRA was distilled for, read from its filename here rather than
    # again in the browser, so the form and the run can never quote different step counts.
    turbo_lora_steps: dict[str, int] = {}

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


class _Live(NamedTuple):
    """The lists a running ComfyUI answered for. Any one of them may be empty."""

    schedulers: list[str]
    samplers: list[str]
    aspects: list[str]
    loras: list[str]
    unets: list[str]

    @property
    def usable(self) -> bool:
        return bool(self.schedulers and self.samplers)


def _comfy_unets(client: ComfyClient) -> list[str]:
    """What diffusion-model loaders accept from the MiniMax H3 folder."""
    names: list[str] = []
    seen: set[str] = set()
    for class_type, input_name in (
        ("UNETLoader", "unet_name"),
        ("DiffusionModelLoader", "unet_name"),
        ("DiffusionModelLoader", "model_name"),
    ):
        for name in client.combo_options(class_type, input_name):
            if name in seen or not _in_minimax_h3_folder(name):
                continue
            seen.add(name)
            names.append(name)
    for name in client.models("diffusion_models"):
        if name in seen or not _in_minimax_h3_folder(name):
            continue
        seen.add(name)
        names.append(name)
    return names


def _comfy_loras(client: ComfyClient) -> list[str]:
    """What the turbo node itself will accept, filtered to this model."""
    names: list[str] = []
    seen: set[str] = set()
    for class_type, input_name in (
        ("MiniMaxH3TurboLoRA", "lora_name"),
        ("LoraLoaderModelOnly", "lora_name"),
        ("LoraLoader", "lora_name"),
    ):
        for name in client.combo_options(class_type, input_name):
            if name in seen or not is_h3_model(name):
                continue
            seen.add(name)
            names.append(name)
    for name in client.models("loras"):
        if name in seen or not is_h3_model(name):
            continue
        seen.add(name)
        names.append(name)
    return names


def _from_comfy(client: ComfyClient) -> _Live | None:
    """Every list the installed nodes can answer for, or `None` if none of them answered.

    The lists are gathered together but judged apart. An instance without the resolution
    node still knows its LoRAs, and a sampler list that comes back empty is no reason to
    fall back to a guessed LoRA list.
    """
    try:
        schedulers = client.combo_options("BasicScheduler", "scheduler")
        samplers = client.combo_options("KSamplerSelect", "sampler_name")
        aspects = client.combo_options("ResolutionSelector", "aspect_ratio")
        loras = _comfy_loras(client)
        unets = _comfy_unets(client)
    except ComfyError:
        return None
    return _Live(schedulers, samplers, aspects or list(FALLBACK_ASPECTS), loras, unets)


def build_catalog(settings: Settings, client: ComfyClient | None = None) -> Catalog:
    owned = client is None
    client = client or ComfyClient(settings.comfy_url)
    try:
        live = _from_comfy(client)
    finally:
        if owned:
            client.close()
    loras = live.loras if live is not None else []

    disk_models = list_models(settings.diffusion_models_dir)
    live_unets = live.unets if live is not None else []
    if disk_models:
        models = disk_models
        models_source = "disk"
    elif live_unets:
        models = live_unets
        models_source = "comfy"
    else:
        models = []
        models_source = "unavailable"

    loras_source = "comfy"
    if not loras:
        loras = list_turbo_loras(settings.lora_models_dir)
        loras_source = "disk"
    if not loras:
        loras = [DEFAULT_TURBO_LORA]
        loras_source = "fallback"
    chosen_lora = default_turbo_lora(loras)
    lora_steps = {name: turbo_steps_for(name) for name in loras}

    images = _listdir(settings.comfy_input_dir, IMAGE_SUFFIXES)
    videos = _listdir(settings.comfy_input_dir, VIDEO_SUFFIXES)
    audios = _listdir(settings.comfy_input_dir, AUDIO_SUFFIXES)
    media_source = "disk" if settings.comfy_input_dir.is_dir() else "unavailable"
    repo_inputs = REPO_ROOT / "inputs"
    if repo_inputs.is_dir():
        if not settings.comfy_input_dir.is_dir():
            images = _listdir(repo_inputs, IMAGE_SUFFIXES)
            videos = _listdir(repo_inputs, VIDEO_SUFFIXES)
            audios = _listdir(repo_inputs, AUDIO_SUFFIXES)
            media_source = "disk"
        elif settings.comfy_input_dir == DEFAULT_COMFY_INPUT_DIR:
            for img in _listdir(repo_inputs, IMAGE_SUFFIXES):
                if img not in images:
                    images.append(img)
            for vid in _listdir(repo_inputs, VIDEO_SUFFIXES):
                if vid not in videos:
                    videos.append(vid)
            for aud in _listdir(repo_inputs, AUDIO_SUFFIXES):
                if aud not in audios:
                    audios.append(aud)
            media_source = "disk"

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
        "turbo": False,
        "turbo_lora": chosen_lora,
        "turbo_lora_strength": DEFAULT_TURBO_STRENGTH,
        "cache_enabled": True,
        "cache": "spectrum",
        "cache_preset": "moderate",
        "sol_attn": True,
        "sol_preset": "moderate",
        "widgets": {
            "guides": json.dumps(list(BASELINE_GUIDES), separators=(",", ":")),
        },
    }

    if live is None or not live.usable:
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
            turbo_loras=loras,
            turbo_loras_source=loras_source,
            default_turbo_lora=chosen_lora,
            turbo_lora_steps=lora_steps,
            images=images,
            videos=videos,
            audios=audios,
            media_source=media_source,
            default_first_frame=first_frame,
            default_ref_images=ref_images,
            defaults=defaults,
        )

    schedulers, samplers, aspects = live.schedulers, live.samplers, live.aspects
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
        turbo_loras=loras,
        turbo_loras_source=loras_source,
        default_turbo_lora=chosen_lora,
        turbo_lora_steps=lora_steps,
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
