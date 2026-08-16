from __future__ import annotations

import pytest
from pydantic import ValidationError

from h3lab.domain.config import GenerationConfig, config_hash, recipe_hash
from h3lab.shared.contracts import GenerationDocument, JobSubmission
from h3lab.shared.projection import materialize_submission, project_h3_submission

REVISION = f"sha256:{'a' * 64}"
ASSET_A = "11111111-1111-4111-8111-111111111111"
ASSET_B = "22222222-2222-4222-8222-222222222222"


def seed_document() -> GenerationDocument:
    return GenerationDocument.model_validate(
        {
            "protocolVersion": "1.0",
            "documentId": "minimax-h3-unified:generation",
            "schemaRevision": "h3-v1",
            "workflowId": "minimax-h3-unified",
            "workflowRevision": REVISION,
            "title": "MiniMax H3",
            "availability": {
                "state": "available",
                "observedAt": "2026-08-15T08:00:00.000Z",
            },
            "capabilities": {
                "required": ["component.seed", "component.textarea", "action.submit"],
                "optional": [],
            },
            "components": [
                {
                    "id": "prompt",
                    "kind": "textarea",
                    "binding": "prompt",
                    "label": "Prompt",
                    "required": True,
                    "optional": False,
                    "defaultValue": "default prompt",
                },
                {
                    "id": "seed",
                    "kind": "seed",
                    "binding": "seed",
                    "label": "Seed",
                    "required": True,
                    "optional": False,
                    "allowRandom": True,
                    "minimum": 10,
                    "maximum": 20,
                    "defaultValue": None,
                },
            ],
            "actions": [
                {
                    "id": "generate",
                    "kind": "submit",
                    "label": "Generate",
                    "endpoint": "/v1/workflows/minimax-h3-unified/jobs",
                    "method": "POST",
                    "optional": False,
                }
            ],
        }
    )


def h3_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "mode": "text_to_video",
        "prompt": "A lighthouse in rain",
        "seed": 42,
        "duration": 5,
        "aspectRatio": "16:9 (Widescreen)",
        "megapixels": 1,
        "steps": 20,
        "turboLora": "none",
        "filenamePrefix": "h3-test-video",
        "cache": "easy",
        "attention": "sage_sol",
        "interpolation": "gmfss",
        "upscaler": "rtx",
        "cleanVram": True,
        "postGrade": True,
        "faceRefine": False,
        "firstFrame": [],
        "lastFrame": [],
        "referenceImages": [],
        "referenceVideos": [],
        "referenceVideoAudio": [],
        "referenceAudio": [],
    }
    value.update(overrides)
    return value


def submission(**overrides: object) -> JobSubmission:
    return JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input=h3_input(**overrides),
    )


def test_materialization_pins_revisions_defaults_and_random_seed():
    document = seed_document()
    raw = JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input={"seed": None},
    )
    made = materialize_submission(document, raw, randbelow=lambda span: span - 1)
    assert made.input == {"prompt": "default prompt", "seed": 20}

    with pytest.raises(ValueError, match="revision"):
        materialize_submission(
            document,
            raw.model_copy(update={"workflow_revision": f"sha256:{'b' * 64}"}),
        )


def test_projection_preserves_every_shared_axis_and_exact_identity():
    raw = submission()
    config = project_h3_submission(raw)
    assert config.execution_backend == "shared"
    assert config.mode == "t2v"
    assert config.prompt == "A lighthouse in rain"
    assert config.seed == 42
    assert config.duration_s == 5
    assert config.aspect_ratio == "16:9 (Widescreen)"
    assert config.mp == 1
    assert config.steps == 20
    assert config.scheduler == "simple"
    assert config.sampler == "euler"
    assert config.diffusion_model == "shared:minimax-h3-unified"
    assert config.cache == "easy"
    assert config.attention == "sage_sol"
    assert config.interp == "gmfss"
    assert config.upscaler is True
    assert config.upscaler_mode == "rtx"
    assert config.clean_vram is True
    assert config.post_grade is True
    assert config.face_refine is False
    assert config.filename_prefix == "h3-test-video"
    assert config.shared_identity == raw.input


def test_projection_maps_modes_assets_and_schedule_bound_lora():
    flf = project_h3_submission(
        submission(
            mode="first_last_frame",
            firstFrame=[ASSET_A],
            lastFrame=[ASSET_B],
            interpolation="none",
            upscaler="none",
        )
    )
    assert flf.mode == "flf2v"
    assert flf.first_frame == ASSET_A
    assert flf.last_frame == ASSET_B
    assert flf.interp == "off"
    assert flf.upscaler is False

    r2v = project_h3_submission(
        submission(
            mode="reference_to_video",
            referenceVideoAudio=[ASSET_A],
            turboLora="minimax_h3_turbo_8step.safetensors",
            steps=8,
        )
    )
    assert r2v.mode == "r2v"
    assert r2v.ref_video_audios == (ASSET_A,)
    assert r2v.turbo is True
    assert r2v.turbo_lora == "minimax_h3_turbo_8step.safetensors"
    assert r2v.steps == 8


def test_projection_rejects_incomplete_unknown_or_incoherent_input():
    incomplete = submission()
    with pytest.raises(ValidationError):
        project_h3_submission(
            incomplete.model_copy(
                update={
                    "input": {
                        key: value
                        for key, value in incomplete.input.items()
                        if key != "mode"
                    }
                }
            )
        )

    with pytest.raises(ValidationError):
        project_h3_submission(submission(unknown=True))

    with pytest.raises(ValidationError):
        project_h3_submission(submission(mode="first_last_frame", firstFrame=[]))


def test_shared_axes_split_identity_without_rehashing_historical_configs():
    historical = GenerationConfig(mode="t2v", prompt="x")
    assert config_hash(historical) == "b6c01c39b9764de9d44de19f43767e24"
    assert recipe_hash(historical) == "4bcd306ccd4cdae1c7b6297ed3f77c51"

    rtx = project_h3_submission(submission(upscaler="rtx"))
    seedvr = project_h3_submission(submission(upscaler="seedvr2"))
    assert config_hash(rtx) != config_hash(seedvr)
    assert recipe_hash(rtx) != recipe_hash(seedvr)
