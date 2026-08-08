"""Generation config: the value that determines an output, plus its identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GenMode = Literal["flf2v", "t2v", "r2v"]
CacheName = Literal["none", "spectrum", "easy", "h3"]
PresetLevel = Literal["conservative", "moderate", "aggressive", "custom"]
CachePreset = PresetLevel
RefImageSize = Literal["match", "max"]

GEN_MODES: tuple[GenMode, ...] = ("flf2v", "t2v", "r2v")
CACHE_NAMES: tuple[CacheName, ...] = ("none", "spectrum", "easy", "h3")
PRESET_LEVELS: tuple[PresetLevel, ...] = (
    "conservative",
    "moderate",
    "aggressive",
    "custom",
)

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3

DEFAULT_SCHEDULER = "beta57"
DEFAULT_SAMPLER = "euler"
DEFAULT_ASPECT = "16:9 (Widescreen)"
DEFAULT_SEED = 42
TURBO_STEPS = 4

# Fallback weights when a run does not name a file. The bare UNET loader handles every
# non-GGUF diffusion model; only the .gguf extension needs the other loader.
DEFAULT_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
DEFAULT_GGUF_UNET = "MiniMax-H3-FL2VA-Q4_K_M.gguf"


def resolve_model_filename(diffusion_model: str) -> str:
    """The filename to hand the loader node."""
    name = (diffusion_model or "").strip()
    return name or DEFAULT_UNET


def is_gguf(diffusion_model: str) -> bool:
    return (diffusion_model or "").strip().lower().endswith(".gguf")

BASELINE_PROMPT = (
    "[0s-1.5s] Low tracking shot races forward with the courier as he accelerates hard "
    "on the magnetic skateboard, cyan board thrusters flare brighter, rain streaks turn "
    "into diagonal streaks across the lens, neon signs smear into long light trails "
    "while the alley walls rush past on both sides.\n"
    "[1.5s-3.5s] He snaps into a sharp left bank at full speed, the board sprays a sheet "
    "of water and sparks off the wet pavement, a swarm of holographic ads and floating "
    "drones whip past his head, camera whip-pans to keep him centered as background "
    "traffic blurs into pure light streaks.\n"
    "[3.5s-5s] The courier launches off a sudden ramp of debris, body and board launching "
    "airborne in a tight arc through heavy rain and neon haze, camera follows the upward "
    "trajectory then drops with him as he lands hard, water exploding outward in all "
    "directions while the alley continues to rush past at extreme speed."
)

# The media the form starts from, so a first run costs no file hunting. The frame is the
# still the baseline prompt above describes; the references are a set that belongs together
# and only reads as a scene when all of them are present.
#
# These are names, not promises. `catalog` resolves each one against ComfyUI's input folder
# and drops whatever is not there, because a default pointing at a missing file is worse
# than no default — it fails preflight instead of failing to be filled in.
BASELINE_FIRST_FRAME = "Cyberpunk_courier_riding_magneti…_2K_202608070843.jpeg"
BASELINE_REF_IMAGES: tuple[str, ...] = (
    "Female_space_explorer_character___202608071035.jpeg",
    "Alien_greenhouse_concept_design___202608071035.jpeg",
    "Spherical_robot_character_design__2K_202608071035.jpeg",
    "Storyboard_grid_of_greenhouse_ex__202608071035.jpeg",
)


def basename(value: str) -> str:
    """ComfyUI loaders take bare filenames; browsers may hand us a full path."""
    return Path(str(value).replace("\\", "/")).name


def _clamp_names(values: Iterable[str] | None, limit: int) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        out.append(basename(text))
        if len(out) >= limit:
            break
    return out


class GenerationConfig(BaseModel):
    """Everything that determines a generated video. Immutable once a run starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: GenMode = "flf2v"
    diffusion_model: str = ""
    prompt: str = BASELINE_PROMPT

    first_frame: str = ""
    last_frame: str = ""
    ref_images: tuple[str, ...] = ()
    ref_videos: tuple[str, ...] = ()
    ref_video_audios: tuple[str, ...] = ()
    ref_audios: tuple[str, ...] = ()
    ref_image_size: RefImageSize = "match"

    scheduler: str = DEFAULT_SCHEDULER
    sampler: str = DEFAULT_SAMPLER
    aspect_ratio: str = DEFAULT_ASPECT
    steps: Annotated[int, Field(ge=1, le=200)] = 20
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = DEFAULT_SEED
    mp: Annotated[float, Field(ge=0.05, le=8.0)] = 0.5
    duration_s: Annotated[float, Field(ge=0.5, le=60.0)] = 5.0

    turbo: bool = False
    rife: bool = False
    upscaler: bool = False
    clean_vram: bool = False

    cache_enabled: bool = True
    cache: CacheName = "spectrum"
    cache_preset: PresetLevel = "moderate"
    sol_attn: bool = True
    sol_preset: PresetLevel = "moderate"
    widgets: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("prompt must not be empty")
        return text

    @field_validator("diffusion_model", "first_frame", "last_frame")
    @classmethod
    def _to_basename(cls, value: str) -> str:
        text = str(value or "").strip()
        return basename(text) if text else ""

    @field_validator("scheduler", "sampler", "aspect_ratio")
    @classmethod
    def _trim_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("ref_images", mode="before")
    @classmethod
    def _clamp_images(cls, value: Any) -> tuple[str, ...]:
        return tuple(_clamp_names(value, MAX_REF_IMAGES))

    @field_validator("ref_videos", "ref_video_audios", mode="before")
    @classmethod
    def _clamp_videos(cls, value: Any) -> tuple[str, ...]:
        return tuple(_clamp_names(value, MAX_REF_VIDEOS))

    @field_validator("ref_audios", mode="before")
    @classmethod
    def _clamp_audios(cls, value: Any) -> tuple[str, ...]:
        return tuple(_clamp_names(value, MAX_REF_AUDIOS))

    @model_validator(mode="after")
    def _mode_coherence(self) -> GenerationConfig:
        # cache="none" and cache_enabled=False are the same statement; keep one truth.
        if self.cache == "none" and self.cache_enabled:
            object.__setattr__(self, "cache_enabled", False)
        if not self.cache_enabled and self.cache != "none":
            object.__setattr__(self, "cache", "none")

        if self.mode == "flf2v" and not self.first_frame:
            raise ValueError("first_frame is required for mode 'flf2v'")
        if self.mode != "flf2v" and (self.first_frame or self.last_frame):
            object.__setattr__(self, "first_frame", "")
            object.__setattr__(self, "last_frame", "")
        if self.mode != "r2v":
            for field in ("ref_images", "ref_videos", "ref_video_audios", "ref_audios"):
                object.__setattr__(self, field, ())
        elif not (self.ref_images or self.ref_videos or self.ref_audios):
            raise ValueError("mode 'r2v' needs at least one reference image, video, or audio")
        return self

    @property
    def effective_steps(self) -> int:
        """Turbo LoRA is trained for a fixed 4-step schedule."""
        return TURBO_STEPS if self.turbo else self.steps

    @property
    def cache_active(self) -> bool:
        return self.cache_enabled and self.cache != "none"

    @property
    def uses_gguf(self) -> bool:
        return is_gguf(self.diffusion_model)

    @property
    def media_files(self) -> tuple[str, ...]:
        """Every input file ComfyUI must already have, in wiring order."""
        names = [self.first_frame, self.last_frame]
        names.extend(self.ref_images)
        names.extend(self.ref_videos)
        names.extend(self.ref_video_audios)
        names.extend(self.ref_audios)
        return tuple(name for name in names if name)

    def merged(self, **overrides: Any) -> GenerationConfig:
        """A new config with ``overrides`` applied and revalidated."""
        data = self.model_dump()
        data.update({k: v for k, v in overrides.items() if k in type(self).model_fields})
        return type(self)(**data)


# Fields that change the produced pixels. Ordered so canonical output is stable
# regardless of how the model happens to be declared.
HASHED_FIELDS: tuple[str, ...] = (
    "mode",
    "diffusion_model",
    "prompt",
    "first_frame",
    "last_frame",
    "ref_images",
    "ref_videos",
    "ref_video_audios",
    "ref_audios",
    "ref_image_size",
    "scheduler",
    "sampler",
    "aspect_ratio",
    "steps",
    "seed",
    "mp",
    "duration_s",
    "turbo",
    "rife",
    "upscaler",
    "clean_vram",
    "cache_enabled",
    "cache",
    "cache_preset",
    "sol_attn",
    "sol_preset",
    "widgets",
)

RECIPE_EXCLUDED: frozenset[str] = frozenset({"seed"})


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, float):
        # 8.0 and 8 must hash the same; round-trip through repr of a normalised float.
        return float(f"{value:.6g}")
    return value


def canonical_form(cfg: GenerationConfig, *, exclude: Iterable[str] = ()) -> str:
    """Deterministic JSON over the sampling-relevant fields only."""
    skip = set(exclude)
    payload = {
        field: _jsonable(getattr(cfg, field))
        for field in HASHED_FIELDS
        if field not in skip
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(text: str) -> str:
    """The one hash function every config identity is built from."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def config_hash(cfg: GenerationConfig) -> str:
    """Identity of an exact experiment. Equal hash means identical sampling inputs."""
    return digest(canonical_form(cfg))


def recipe_hash(cfg: GenerationConfig, *, also_exclude: Iterable[str] = ()) -> str:
    """Identity of an experiment across seeds. Repeats of a recipe are replicates."""
    return digest(canonical_form(cfg, exclude=RECIPE_EXCLUDED | set(also_exclude)))


class FieldDiff(BaseModel):
    field: str
    label: str
    values: list[str]


FIELD_LABELS: dict[str, str] = {
    "mode": "Mode",
    "diffusion_model": "Weights",
    "prompt": "Prompt",
    "first_frame": "First frame",
    "last_frame": "Last frame",
    "ref_images": "Ref images",
    "ref_videos": "Ref videos",
    "ref_video_audios": "Ref video audio",
    "ref_audios": "Ref audio",
    "ref_image_size": "Ref image size",
    "scheduler": "Scheduler",
    "sampler": "Sampler",
    "aspect_ratio": "Aspect",
    "steps": "Steps",
    "seed": "Seed",
    "mp": "Megapixels",
    "duration_s": "Duration",
    "turbo": "Turbo",
    "rife": "RIFE",
    "upscaler": "Upscaler",
    "clean_vram": "Clean VRAM",
    "cache_enabled": "Cache on",
    "cache": "Cache",
    "cache_preset": "Cache preset",
    "sol_attn": "Sol-Attn",
    "sol_preset": "Sol preset",
    "widgets": "Widget overrides",
}


class ModeNeeds(BaseModel):
    """What a mode demands, in a form a form can read.

    The model validator below is the authority; this states the same rules declaratively so
    the browser can grey out an impossible submit instead of learning about it from a 422.
    """

    model_config = ConfigDict(frozen=True)

    mode: GenMode
    label: str
    requires_all: tuple[str, ...] = ()
    requires_any: tuple[str, ...] = ()
    accepts: tuple[str, ...] = ()


MODE_NEEDS: tuple[ModeNeeds, ...] = (
    ModeNeeds(
        mode="flf2v",
        label="First / last frame",
        requires_all=("first_frame",),
        accepts=("first_frame", "last_frame"),
    ),
    ModeNeeds(mode="t2v", label="Text only"),
    ModeNeeds(
        mode="r2v",
        label="References",
        requires_any=("ref_images", "ref_videos", "ref_audios"),
        accepts=("ref_images", "ref_videos", "ref_video_audios", "ref_audios", "ref_image_size"),
    ),
)


def field_defaults() -> dict[str, Any]:
    """The declared default of every config field, JSON-safe.

    Built field by field rather than by instantiating the model, because two of the three
    modes require an input file and so have no valid empty instance.
    """
    out: dict[str, Any] = {}
    for name, field in GenerationConfig.model_fields.items():
        out[name] = _jsonable(field.get_default(call_default_factory=True))
    return out


def field_display(field: str, value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (tuple, list)):
        return ", ".join(str(v) for v in value) if value else "—"
    if isinstance(value, dict):
        if not value:
            return "—"
        return ", ".join(f"{k}={value[k]}" for k in sorted(value))
    if value is None or value == "":
        return "—"
    if field == "duration_s":
        return f"{float(value):g}s"
    if field == "mp":
        return f"{float(value):g} MP"
    if field == "prompt":
        text = str(value).replace("\n", " ⏎ ")
        return text if len(text) <= 120 else text[:117] + "…"
    return str(value)


# Fields the validator derives from another field. When the determinant already differs,
# reporting the derived field too states the same fact twice: "Cache: none vs spectrum"
# followed by "Cache on: off vs on" is one difference, not two.
DERIVED_FROM: dict[str, str] = {"cache_enabled": "cache"}


def config_diff(configs: Sequence[GenerationConfig]) -> list[FieldDiff]:
    """Only the fields that actually differ across *configs*, in canonical order."""
    if len(configs) < 2:
        return []
    found: dict[str, FieldDiff] = {}
    for field in HASHED_FIELDS:
        rendered = [field_display(field, getattr(cfg, field)) for cfg in configs]
        if len(set(rendered)) > 1:
            found[field] = FieldDiff(
                field=field, label=FIELD_LABELS.get(field, field), values=rendered
            )
    for derived, determinant in DERIVED_FROM.items():
        if derived in found and determinant in found:
            del found[derived]
    return [found[field] for field in HASHED_FIELDS if field in found]


def model_stem(diffusion_model: str) -> str:
    stem = Path(diffusion_model or "").stem
    if not stem:
        return "default"
    # Trim the shared MiniMax H3 prefix so labels stay readable in a dense list.
    for noise in ("minimax_h3_", "minimax-h3-", "MiniMax-H3-", "minimax_", "MiniMax"):
        if stem.lower().startswith(noise.lower()):
            stem = stem[len(noise) :]
            break
    return stem.strip("_-") or "default"


def derive_label(seq: int, cfg: GenerationConfig) -> str:
    """Human-facing display string. Never used as identity."""
    parts = [model_stem(cfg.diffusion_model)]
    parts.append(cfg.cache if cfg.cache_enabled else "nocache")
    if cfg.cache_enabled and cfg.cache_preset != "custom":
        parts[-1] = f"{cfg.cache}/{cfg.cache_preset[:3]}"
    parts.append(f"sol/{cfg.sol_preset[:3]}" if cfg.sol_attn else "nosol")
    parts.append(f"{cfg.effective_steps}st")
    if cfg.turbo:
        parts.append("turbo")
    if cfg.rife:
        parts.append("rife")
    if cfg.upscaler:
        parts.append("up")
    if cfg.mode != "flf2v":
        parts.insert(0, cfg.mode)
    return f"#{seq} " + " · ".join(parts)
