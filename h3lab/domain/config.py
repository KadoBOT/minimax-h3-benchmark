"""Generation config: the value that determines an output, plus its identity."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GenMode = Literal["flf2v", "t2v", "r2v"]
CacheName = Literal["none", "spectrum", "easy", "h3"]
PresetLevel = Literal["conservative", "moderate", "aggressive", "custom"]
CachePreset = PresetLevel
RefImageSize = Literal["match", "max"]
Interp = Literal["off", "film", "rife", "gmfss"]

GEN_MODES: tuple[GenMode, ...] = ("flf2v", "t2v", "r2v")
CACHE_NAMES: tuple[CacheName, ...] = ("none", "spectrum", "easy", "h3")
SPECTRUM_SAMPLERS = frozenset({"euler", "res_multistep"})
INTERP_MODES: tuple[Interp, ...] = ("off", "film", "rife", "gmfss")
INTERP_LABELS: dict[str, str] = {
    "off": "Off",
    "film": "FILM Net",
    "rife": "RIFE",
    "gmfss": "GMFSS",
}

# Field names a stored config may still use. They are read and translated, never written.
LEGACY_FIELD_ALIASES: frozenset[str] = frozenset({"rife"})

# Studio / API names that mean an existing config field. A payload that speaks the
# MiniMaxH3Studio dialect is accepted and stored in the lab's own vocabulary.
STUDIO_FIELD_ALIASES: dict[str, str] = {
    "duration": "duration_s",
    "megapixels": "mp",
    "sampler_name": "sampler",
    "interpolation": "interp",
    "upscale_rtx": "upscaler",
}
STUDIO_VALUE_ALIASES: dict[str, dict[str, str]] = {
    "mode": {"T2V": "t2v", "FLF2V": "flf2v", "R2V": "r2v"},
    "interp": {"none": "off"},
}
TEMPLATE_AXIS_FIELD = "template"
CURRENT_TEMPLATE_ID = "__current__"
TEMPLATE_STATE_KEY = "h3s_ui"
TEMPLATE_TOP_LEVEL_FIELDS = frozenset(
    {
        "steps",
        "scheduler",
        "sampler",
        "cache_enabled",
        "cache",
        "turbo",
        "turbo_lora",
        "turbo_lora_strength",
        "sol_attn",
        "clean_vram",
        "interp",
        "upscaler",
    }
)
TEMPLATE_WIDGET_FIELDS = frozenset(
    {
        "attn",
        "shift_video",
        "shift_audio",
        "derope",
        "post_grade",
        "upscale_ltx",
        "sla",
        "sla_sparsity",
        "sla_block_size",
        "sla_dense_last_steps",
        "sla_protect_audio",
        "sla_stabilize_motion",
        "adaln",
        "fp16_accum",
        "er_sde",
        "er_sde_solver",
        "er_sde_max_stage",
        "er_sde_eta",
        "er_sde_s_noise",
        "use_trt_vae",
        "trt_vae_decoder",
        "trt_vae_encoder",
        "use_vdn",
        "vdn_checkpoint",
        "vdn_apply_turbo_adapter",
        "vdn_strength",
        "vdn_lora_mode",
        "vdn_branch_weights",
        "vdn_attention_backend",
        "vdn_verbose",
    }
)
# Studio knobs that are not first-class config fields. A top-level payload may name
# them; they land on `widgets`. A brand-new widget the form discovered does not
# need to be listed here — the UI already writes it to `widgets` by name.
STUDIO_EXTRA_FIELDS: frozenset[str] = frozenset(
    {
        "guides",
        "upscale_ltx",
        "seed_mode",
        "post_grade",
        "dual",
        "shift_video",
        "pass2_steps",
        "pass2_denoise",
        "pass2_scheduler",
        "pass2_sampler_name",
        "pass2_shift",
        "pass2_scale",
        "attn",
        # Experiment toggles. Each drives a node the workflow keeps inert at its
        # default, so naming one here is what makes it a sweepable axis.
        "shift_audio",
        "derope",
        "sla",
        "sla_sparsity",
        "sla_block_size",
        "sla_dense_last_steps",
        "sla_protect_audio",
        "sla_stabilize_motion",
        "adaln",
        "fp16_accum",
        "er_sde",
        "er_sde_solver",
        "er_sde_max_stage",
        "er_sde_eta",
        "er_sde_s_noise",
        "use_trt_vae",
        "trt_vae_decoder",
        "trt_vae_encoder",
        "use_vdn",
        "vdn_checkpoint",
        "vdn_apply_turbo_adapter",
        "vdn_strength",
        "vdn_lora_mode",
        "vdn_branch_weights",
        "vdn_attention_backend",
        "vdn_verbose",
    }
)
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
DEFAULT_TURBO_STRENGTH = 1.0

# Fallback weights when a run does not name a file. The bare UNET loader handles every
# non-GGUF diffusion model; only the .gguf extension needs the other loader.
DEFAULT_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
DEFAULT_GGUF_UNET = "MiniMax-H3-FL2VA-Q4_K_M.gguf"

# The distilled LoRA a turbo run uses when the config does not name one. The templates ship
# with this file selected, so an existing run that only said `turbo: true` keeps its meaning.
DEFAULT_TURBO_LORA = "minimax_h3_turbo_4step_comfyui_pruned.safetensors"

# Distilled LoRAs are trained for a fixed schedule and say so in their filename. Reading it
# is what lets two turbo LoRAs with different step counts be compared honestly: a 4-step LoRA
# sampled at 8 steps, or an 8-step one at 4, measures the mismatch rather than the LoRA.
#
# The count has to be its own word. `minimax_h3_turbo_4step_...` is a 4-step LoRA, while
# `..._turbo_v4_step600_ema_...` is version 4 at training step 600 and says nothing about a
# schedule, so it falls back to the default rather than sampling at whatever it happens to
# have been numbered.
_STEP_IN_NAME = re.compile(r"(?:^|[^0-9a-z])(\d{1,3})[\s\-_]?step", re.IGNORECASE)


def resolve_model_filename(diffusion_model: str) -> str:
    """The filename to hand the loader node."""
    name = (diffusion_model or "").strip()
    return name or DEFAULT_UNET


def resolve_turbo_lora(turbo_lora: str) -> str:
    """The filename to hand the turbo LoRA node."""
    name = (turbo_lora or "").strip()
    return name or DEFAULT_TURBO_LORA


def turbo_steps_for(turbo_lora: str) -> int:
    """The step count a distilled LoRA was trained for, from its filename."""
    match = _STEP_IN_NAME.search(resolve_turbo_lora(turbo_lora))
    if not match:
        return TURBO_STEPS
    steps = int(match.group(1))
    return steps if 1 <= steps <= 200 else TURBO_STEPS


def is_gguf(diffusion_model: str) -> bool:
    return (diffusion_model or "").strip().lower().endswith(".gguf")

BASELINE_PROMPT = (
    "subject_definitions:\n"
    "<Subject 1> is Rail Saint Korr from <Picture 1>, an older Velk warrior with a lean wiry-dense "
    "build, gaunt planed face, shaved scalp, right-side roped burn scars, and four living dorsal caldera "
    "vents on the upper back venting dull ember heat. Wearing asymmetrical soot-black rail-runner wraps "
    "over dark trousers with leg wraps, gripping a compact blackened hooked boarding axe.\n"
    "<Subject 2> is the industrial foundry fortress of Cinderrail from <Picture 2>, a tiered mountain "
    "of colossal smokestacks, dark iron catwalks, massive rotating gears, and glowing molten metal channels "
    "under heavy smog.\n"
    "<Subject 3> is Hearth Bol from <Picture 3>, a broad muscular bearded Velk foundry smith with four "
    "dorsal caldera vents, soot-stained work clothes, heavy leather apron, tool harness, and a massive "
    "chained iron foundry key.\n\n"
    "summary:\n"
    "[reference generation] A 5.00-second native 1.91:1 cinematic landscape composition high-octane "
    "action sequence in the Orrery universe. Set across the industrial heights of <Subject 2>, <Subject 1> "
    "sprints across a suspended magnetic rail and vaults down toward <Subject 3> at the blast furnace gate. "
    "Dynamic lateral tracking, fast cutting cadence, high chiaroscuro ember contrast, and synchronized "
    "industrial sound.\n\n"
    "retention_analysis:\n"
    "<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - gaunt shaved head, burn scars, soot-black "
    "runner wraps, hooked axe, and four glowing dorsal caldera vents remain consistent.\n"
    "<Subject 2> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - towering smokestacks, molten rails, "
    "dark iron gantries, and ember smoke establish the environment.\n"
    "<Subject 3> (appears in [Shot 2], [Shot 3]): fully_preserved - broad muscular build, beard, leather apron, "
    "chained foundry key, and dorsal vents remain consistent.\n\n"
    "detailed_description:\n"
    "The target video features 2D painterly anime and graphic cel-shaded treatment with high chiaroscuro contrast, "
    "glowing molten accents, charcoal soot, and sharp cut transitions.\n"
    "[Shot 1] Native 1.91:1 wide tracking shot frames <Subject 1> sprinting left-to-right along an elevated magnetic "
    "rail high above <Subject 2>. The four living caldera vents on his upper back pulse with dull orange magma heat, "
    "trailing subtle heat haze into the dark smog. His hooked boarding axe catches amber rim light as his boots spark "
    "against the metal track. The camera tracks laterally with large amplitude at fast speed, keeping him on the "
    "left-third while smokestacks and glowing slag cascades rush past in the background.\n"
    "[Shot 2] At 00:01.800, the shot cuts to an asymmetric medium-low angle inside the blast furnace gate of <Subject 2>. "
    "<Subject 3> stands braced on the right-third, heaving his massive chained foundry key across an open molten channel "
    "as sparks blast across the foreground. His four back vents flare brightly in rhythm with the forge hammer. "
    "The camera pushes in with medium amplitude at fast speed, tilting slightly upward to emphasize his broad muscular "
    "silhouette against the roaring fire.\n"
    "[Shot 3] At 00:03.400, the shot transitions to a dynamic wide-to-medium convergence shot. <Subject 1> drops from an "
    "overhead gantry onto the grated foundry platform beside <Subject 3>, landing with one knee planted and hooked axe raised. "
    "Both warriors turn in unison to face the glowing furnace breach as a burst of molten metal illuminates their silhouettes "
    "in sharp chiaroscuro contrast. The camera pushes in with large amplitude at fast speed toward the center-frame lock until "
    "the 00:05.000 mark.\n\n"
    "overall_soundscape:\n"
    "Deep industrial drone, heavy reverberating forge impacts, hiss of molten metal slag, spark crackle, boot impacts "
    "on magnetic iron rails, heavy chain clatter, and rushing wind through high gantries.\n\n"
    "non_diegetic_music:\n"
    "Driving 140 BPM industrial hybrid trailer cue: heavy distorted sub-bass pulse, metallic percussive hits syncing with "
    "shot cuts at 00:01.800 and 00:03.400, rising brass swell, sharp cymbal choke on the final lockup at 00:05.000, no fade."
)

# The media the form starts from, so a first run costs no file hunting.
BASELINE_FIRST_FRAME = "rail_saint_korr_hero_21x9.png"
BASELINE_REF_IMAGES: tuple[str, ...] = (
    "rail_saint_korr_hero_21x9.png",
    "cinderrail_establishing.jpeg",
    "hearth_bol_hero_21x9.png",
)


def basename(value: str) -> str:
    """Strip an OS path down to the name ComfyUI's loaders accept.

    Combo values already look like ``minimax-h3/foo.safetensors`` — those must
    stay intact. Only a real filesystem path (``/home/...`` or ``C:\\...``) is
    reduced to its last component.
    """
    text = str(value).replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/") or (len(text) > 2 and text[1] == ":"):
        return text.rsplit("/", 1)[-1]
    return text.lstrip("./")


def _guide_files(raw: Any) -> list[str]:
    """Filenames buried in a Studio `guides` JSON payload."""
    payload: Any = raw
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, list):
        return []
    names: list[str] = []
    for clip in payload:
        if not isinstance(clip, dict):
            continue
        for key in ("image", "audio"):
            value = clip.get(key)
            if isinstance(value, str) and value.strip():
                names.append(basename(value))
    return names


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


def spectrum_cache_compatible(sampler: str, widgets: dict[str, Any]) -> bool:
    if widgets.get("er_sde", False):
        return (
            widgets.get("er_sde_solver", "ER-SDE") == "ODE"
            or widgets.get("er_sde_eta", 1.0) == 0
            or widgets.get("er_sde_s_noise", 1.0) == 0
        )
    return sampler in SPECTRUM_SAMPLERS


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
    turbo_lora: str = ""
    turbo_lora_strength: Annotated[float, Field(ge=0.0, le=3.0)] = DEFAULT_TURBO_STRENGTH
    interp: Interp = "off"
    upscaler: bool = False
    clean_vram: bool = False

    cache_enabled: bool = True
    cache: CacheName = "spectrum"
    cache_preset: PresetLevel = "moderate"
    sol_attn: bool = True
    sol_preset: PresetLevel = "moderate"
    widgets: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data: Any) -> Any:
        """Read older names, the Studio API dialect, and extra studio widgets.

        Stored runs, saved presets, and the old benchmark's export still speak `rife`.
        The MiniMaxH3Studio node speaks `duration` / `interpolation` / `T2V`. Unknown
        studio knobs land on `widgets` so a new API field hashes and round-trips
        without a model change. An explicit current name always wins over an alias.
        """
        if not isinstance(data, dict):
            return data
        moved = dict(data)
        if "rife" in moved:
            legacy = moved.pop("rife")
            if moved.get("interp") is None:
                moved["interp"] = "rife" if legacy else "off"
        for studio_name, field in STUDIO_FIELD_ALIASES.items():
            if studio_name in moved and field not in moved:
                moved[field] = moved.pop(studio_name)
            elif studio_name in moved:
                moved.pop(studio_name)
        cache = moved.get("cache")
        if isinstance(cache, bool):
            moved.pop("cache")
            if "cache_enabled" not in moved:
                moved["cache_enabled"] = cache
            if not cache:
                moved["cache"] = "none"
            elif moved.get("cache") is None:
                moved["cache"] = "spectrum"
        for field, mapping in STUDIO_VALUE_ALIASES.items():
            value = moved.get(field)
            if isinstance(value, str) and value in mapping:
                moved[field] = mapping[value]
        extras = {key: moved.pop(key) for key in list(moved) if key in STUDIO_EXTRA_FIELDS}
        if extras:
            widgets = dict(moved.get("widgets") or {})
            widgets.update(extras)
            moved["widgets"] = widgets
        explicit_attn = (moved.get("widgets") or {}).get("attn")
        if explicit_attn is not None:
            if explicit_attn not in {"off", "sol", "comfy_kitchen"}:
                raise ValueError(f"unsupported attention mode {explicit_attn!r}")
            moved["sol_attn"] = explicit_attn == "sol"
        return moved

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("prompt must not be empty")
        return text

    @field_validator("diffusion_model", "turbo_lora", "first_frame", "last_frame")
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
        # With turbo off there is no LoRA in the graph, so naming one would split the
        # identity of two runs that produce the same pixels. With turbo on the opposite is
        # true: "" means the default file, and a run that says so has to say which, or it
        # would read as a different experiment from the one that spelled the name out.
        #
        # The step count is the same rule from the other side. A turbo run samples at the
        # schedule its LoRA was distilled for, so whatever the step field held when the
        # toggle was flipped is not a setting — it is a leftover, and leaving it in a hashed
        # field makes two identical runs read as two experiments and shows a person a
        # schedule the sampler was never given.
        if self.turbo:
            object.__setattr__(self, "turbo_lora", resolve_turbo_lora(self.turbo_lora))
            object.__setattr__(self, "steps", turbo_steps_for(self.turbo_lora))
        else:
            object.__setattr__(self, "turbo_lora", "")
            object.__setattr__(self, "turbo_lora_strength", DEFAULT_TURBO_STRENGTH)

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
        """The step count the sampler is given.

        A turbo run samples at the schedule its LoRA was distilled for, which the validator
        has already written into `steps`. The two can no longer disagree; this stays because
        it is the name the rest of the lab asks the question by.
        """
        return turbo_steps_for(self.turbo_lora) if self.turbo else self.steps

    @property
    def turbo_lora_file(self) -> str:
        """The LoRA filename a turbo run loads, or empty when turbo is off."""
        return self.turbo_lora if self.turbo else ""

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
        names.extend(_guide_files(self.widgets.get("guides")))
        return tuple(name for name in names if name)

    def merged(self, **overrides: Any) -> GenerationConfig:
        """A new config with ``overrides`` applied and revalidated.

        Legacy names and Studio API names are passed through for the model to translate,
        so an override written against either vocabulary changes the config instead of
        being quietly ignored. Unknown studio knobs land on `widgets`.
        """
        data = self.model_dump()
        rewritten: dict[str, Any] = {}
        for key, value in overrides.items():
            target = STUDIO_FIELD_ALIASES.get(key)
            if target is not None and target not in overrides:
                rewritten[target] = value
            else:
                rewritten[key] = value
        incoming_widgets = rewritten.get("widgets")
        if isinstance(incoming_widgets, dict) and data.get("widgets"):
            merged_widgets = dict(data["widgets"])
            merged_widgets.update(incoming_widgets)
            rewritten = {**rewritten, "widgets": merged_widgets}
        data.update(rewritten)
        return type(self)(**data)


def template_provenance(config: GenerationConfig) -> tuple[str, str] | None:
    raw = config.widgets.get(TEMPLATE_STATE_KEY)
    if not isinstance(raw, str):
        return None
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("source") != "sweep"
        or not isinstance(state.get("template_id"), str)
    ):
        return None
    template_id = state["template_id"]
    name = state.get("template_name")
    return template_id, name if isinstance(name, str) and name else template_id


def config_attention(config: GenerationConfig) -> str:
    explicit = config.widgets.get("attn")
    if isinstance(explicit, str):
        return explicit
    return "sol" if config.sol_attn else "off"


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
    "turbo_lora",
    "turbo_lora_strength",
    "interp",
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


def canonical_form(
    cfg: GenerationConfig,
    *,
    exclude: Iterable[str] = (),
    exclude_widgets: Iterable[str] = (),
) -> str:
    """Deterministic JSON over the sampling-relevant fields only."""
    skip = set(exclude)
    skipped_widgets = {TEMPLATE_STATE_KEY, *exclude_widgets}
    payload = {
        field: _jsonable(
            {
                key: value
                for key, value in cfg.widgets.items()
                if key not in skipped_widgets
                and (key != "attn" or value not in {"sol", "off"})
            }
            if field == "widgets"
            else getattr(cfg, field)
        )
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
    "turbo_lora": "Turbo LoRA",
    "turbo_lora_strength": "Turbo strength",
    "interp": "Interpolation",
    "upscaler": "Upscaler",
    "clean_vram": "Clean VRAM",
    "cache_enabled": "Cache on",
    "cache": "Cache",
    "cache_preset": "Cache preset",
    "sol_attn": "Sol-Attn",
    "sol_preset": "Sol preset",
    "widgets": "Widget overrides",
    "guides": "Guides",
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


# Fields the validator derives from another field. When a determinant already differs,
# reporting the derived field too states the same fact twice: "Cache: none vs spectrum"
# followed by "Cache on: off vs on" is one difference, not two. `steps` has two determinants
# because a turbo run's schedule comes from its LoRA: both "Turbo: off vs on" and "Turbo
# LoRA: 4step vs 8step" already say what happened to the step count.
DERIVED_FROM: dict[str, tuple[str, ...]] = {
    "cache_enabled": ("cache",),
    "turbo_lora": ("turbo",),
    "turbo_lora_strength": ("turbo",),
    "steps": ("turbo", "turbo_lora"),
    "sla_sparsity": ("sla",),
    "sla_block_size": ("sla",),
    "sla_dense_last_steps": ("sla",),
    "sla_protect_audio": ("sla",),
    "sla_stabilize_motion": ("sla",),
    "er_sde_solver": ("er_sde",),
    "er_sde_max_stage": ("er_sde",),
    "er_sde_eta": ("er_sde",),
    "er_sde_s_noise": ("er_sde",),
}


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
    for derived, determinants in DERIVED_FROM.items():
        if derived in found and any(name in found for name in determinants):
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


def lora_stem(turbo_lora: str) -> str:
    """A turbo LoRA in the few characters that distinguish it from the others."""
    stem = model_stem(turbo_lora)
    for noise in ("turbo_", "turbo-"):
        if stem.lower().startswith(noise):
            stem = stem[len(noise) :]
            break
    return stem.strip("_-") or "default"


def derive_label(seq: int, cfg: GenerationConfig) -> str:
    """Human-facing display string. Never used as identity."""
    parts = [model_stem(cfg.diffusion_model)]
    parts.append(cfg.cache if cfg.cache_enabled else "nocache")
    if cfg.cache_enabled and cfg.cache_preset != "custom":
        parts[-1] = f"{cfg.cache}/{cfg.cache_preset[:3]}"
    attention = config_attention(cfg)
    if attention == "sol":
        parts.append(f"sol/{cfg.sol_preset[:3]}")
    elif attention == "comfy_kitchen":
        parts.append("kitchen")
    else:
        parts.append("nosol")
    parts.append(f"{cfg.effective_steps}st")
    if cfg.turbo:
        parts.append(f"turbo/{lora_stem(cfg.turbo_lora_file)}")
        if cfg.turbo_lora_strength != DEFAULT_TURBO_STRENGTH:
            parts[-1] += f"@{cfg.turbo_lora_strength:g}"
    if cfg.interp != "off":
        parts.append(cfg.interp)
    if cfg.upscaler:
        parts.append("up")
    if cfg.mode != "flf2v":
        parts.insert(0, cfg.mode)
    return f"#{seq} " + " · ".join(parts)
