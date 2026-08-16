"""Project pinned SDUI input into h3lab's benchmark vocabulary without compiling it."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from h3lab.domain.config import GenerationConfig, GenMode
from h3lab.shared.contracts import (
    AssetComponent,
    GenerationDocument,
    InputComponent,
    JobSubmission,
    NumberComponent,
    OpaqueId,
    SeedComponent,
    SelectComponent,
    TextareaComponent,
    TextComponent,
    ToggleComponent,
)


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class H3SubmissionInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    mode: Literal["text_to_video", "first_last_frame", "reference_to_video"]
    prompt: Annotated[str, Field(min_length=1, max_length=12000)]
    seed: Annotated[int, Field(ge=0, le=9007199254740991)]
    duration: Annotated[int, Field(ge=1, le=60)]
    aspect_ratio: Annotated[str, Field(min_length=1)]
    megapixels: Annotated[float, Field(gt=0, le=8)]
    steps: Annotated[int, Field(ge=1, le=200)]
    turbo_lora: Annotated[str, Field(min_length=1)]
    filename_prefix: Annotated[str, Field(min_length=1, max_length=160)]
    cache: Literal["none", "spectrum", "easy", "h3"]
    attention: Literal["native", "kitchen", "sage_sol"]
    interpolation: Literal["none", "gmfss", "rife", "film"]
    upscaler: Literal["none", "rtx", "seedvr2"]
    clean_vram: bool
    post_grade: bool
    face_refine: bool
    first_frame: Annotated[list[OpaqueId], Field(max_length=1)]
    last_frame: Annotated[list[OpaqueId], Field(max_length=1)]
    reference_images: Annotated[list[OpaqueId], Field(max_length=32)]
    reference_videos: Annotated[list[OpaqueId], Field(max_length=32)]
    reference_video_audio: Annotated[list[OpaqueId], Field(max_length=32)]
    reference_audio: Annotated[list[OpaqueId], Field(max_length=32)]


def materialize_submission(
    document: GenerationDocument,
    submission: JobSubmission,
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> JobSubmission:
    if (
        submission.workflow_revision != document.workflow_revision
        or submission.schema_revision != document.schema_revision
    ):
        raise ValueError("submission revisions do not match the displayed document")
    if document.availability.state != "available":
        raise ValueError("generation is not currently available")

    values: dict[str, JsonValue] = dict(submission.input)
    for component in document.components:
        if not isinstance(component, InputComponent):
            continue
        binding = component.binding
        if binding not in values:
            default = _default_value(component)
            if not isinstance(default, _Missing):
                values[binding] = default
        if isinstance(component, SeedComponent) and values.get(binding) is None:
            if not component.allow_random:
                raise ValueError(f"{binding} does not allow a random seed")
            span = component.maximum - component.minimum + 1
            selected = randbelow(span)
            if not isinstance(selected, int) or selected < 0 or selected >= span:
                raise ValueError("random seed source returned an out-of-range value")
            values[binding] = component.minimum + selected
    return JobSubmission(
        workflow_revision=submission.workflow_revision,
        schema_revision=submission.schema_revision,
        input=values,
    )


def project_h3_submission(submission: JobSubmission) -> GenerationConfig:
    parsed = H3SubmissionInput.model_validate(submission.input)
    mode: GenMode
    if parsed.mode == "text_to_video":
        mode = "t2v"
    elif parsed.mode == "first_last_frame":
        mode = "flf2v"
    else:
        mode = "r2v"
    turbo = parsed.turbo_lora != "none"
    return GenerationConfig(
        mode=mode,
        execution_backend="shared",
        shared_workflow_revision=submission.workflow_revision,
        shared_schema_revision=submission.schema_revision,
        diffusion_model="shared:minimax-h3-unified",
        prompt=parsed.prompt,
        first_frame=_one(parsed.first_frame),
        last_frame=_one(parsed.last_frame),
        ref_images=parsed.reference_images,
        ref_videos=parsed.reference_videos,
        ref_video_audios=parsed.reference_video_audio,
        ref_audios=parsed.reference_audio,
        scheduler="simple",
        sampler="euler",
        aspect_ratio=parsed.aspect_ratio,
        steps=parsed.steps,
        seed=parsed.seed,
        mp=parsed.megapixels,
        duration_s=parsed.duration,
        turbo=turbo,
        turbo_lora="" if not turbo else parsed.turbo_lora,
        interp="off" if parsed.interpolation == "none" else parsed.interpolation,
        upscaler=parsed.upscaler != "none",
        upscaler_mode=parsed.upscaler,
        clean_vram=parsed.clean_vram,
        cache_enabled=parsed.cache != "none",
        cache=parsed.cache,
        attention=parsed.attention,
        post_grade=parsed.post_grade,
        face_refine=parsed.face_refine,
        filename_prefix=parsed.filename_prefix,
        sol_attn=parsed.attention == "sage_sol",
        widgets={},
        shared_identity=dict(submission.input),
    )


def submission_from_config(config: GenerationConfig) -> JobSubmission:
    """Rebuild an exact shared binding map after a local count/sweep config edit."""
    if (
        config.execution_backend != "shared"
        or config.shared_workflow_revision is None
        or config.shared_schema_revision is None
        or not config.shared_identity
    ):
        raise ValueError("config does not retain a pinned shared submission")
    values = {
        **config.shared_identity,
        "mode": {
            "t2v": "text_to_video",
            "flf2v": "first_last_frame",
            "r2v": "reference_to_video",
        }[config.mode],
        "prompt": config.prompt,
        "seed": config.seed,
        "duration": config.duration_s,
        "aspectRatio": config.aspect_ratio,
        "megapixels": config.mp,
        "steps": config.steps,
        "turboLora": config.turbo_lora
        if config.turbo and config.turbo_lora
        else "none",
        "filenamePrefix": config.filename_prefix,
        "cache": config.cache if config.cache_enabled else "none",
        "attention": config.attention,
        "interpolation": "none" if config.interp == "off" else config.interp,
        "upscaler": config.upscaler_mode,
        "cleanVram": config.clean_vram,
        "postGrade": config.post_grade,
        "faceRefine": config.face_refine,
        "firstFrame": [config.first_frame] if config.first_frame else [],
        "lastFrame": [config.last_frame] if config.last_frame else [],
        "referenceImages": list(config.ref_images),
        "referenceVideos": list(config.ref_videos),
        "referenceVideoAudio": list(config.ref_video_audios),
        "referenceAudio": list(config.ref_audios),
    }
    return JobSubmission(
        workflow_revision=config.shared_workflow_revision,
        schema_revision=config.shared_schema_revision,
        input=values,
    )


class _Missing:
    pass


_MISSING = _Missing()


def _default_value(component: InputComponent) -> JsonValue | _Missing:
    if isinstance(component, AssetComponent):
        return []
    if isinstance(component, ToggleComponent):
        return component.default_value
    if isinstance(component, SeedComponent):
        return component.default_value
    if (
        isinstance(
            component,
            (TextComponent, TextareaComponent, NumberComponent, SelectComponent),
        )
        and "default_value" in component.model_fields_set
    ):
        return component.default_value
    return _MISSING


def _one(values: list[str]) -> str:
    return values[0] if values else ""


__all__ = [
    "H3SubmissionInput",
    "materialize_submission",
    "project_h3_submission",
    "submission_from_config",
]
