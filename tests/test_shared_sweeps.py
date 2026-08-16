from __future__ import annotations

import pytest

from h3lab.domain.shared_sweeps import (
    SharedSweepAxis,
    SharedSweepSpec,
    expand_shared_sweep,
)
from h3lab.shared.contracts import GenerationDocument, JobSubmission

REVISION = f"sha256:{'a' * 64}"


def document(*, steps_visible_for: str | None = None) -> GenerationDocument:
    steps: dict[str, object] = {
        "id": "steps",
        "kind": "number",
        "binding": "steps",
        "label": "Steps",
        "required": True,
        "minimum": 1,
        "maximum": 200,
        "step": 1,
        "integer": True,
        "defaultValue": 20,
    }
    if steps_visible_for is not None:
        steps["visibleWhen"] = [
            {"field": "mode", "operator": "equals", "value": steps_visible_for}
        ]
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
                "required": [
                    "component.number",
                    "component.seed",
                    "component.select",
                    "component.toggle",
                    "action.submit",
                ],
                "optional": [],
            },
            "components": [
                {
                    "id": "mode",
                    "kind": "select",
                    "binding": "mode",
                    "label": "Mode",
                    "required": True,
                    "options": [
                        {"value": "text_to_video", "label": "Text"},
                        {"value": "first_last_frame", "label": "Frames"},
                    ],
                    "defaultValue": "text_to_video",
                },
                steps,
                {
                    "id": "clean-vram",
                    "kind": "toggle",
                    "binding": "cleanVram",
                    "label": "Clean VRAM",
                    "required": True,
                    "defaultValue": True,
                },
                {
                    "id": "seed",
                    "kind": "seed",
                    "binding": "seed",
                    "label": "Seed",
                    "required": True,
                    "allowRandom": True,
                    "minimum": 0,
                    "maximum": 100,
                    "defaultValue": 42,
                },
            ],
            "actions": [
                {
                    "id": "generate",
                    "kind": "submit",
                    "label": "Generate",
                    "endpoint": "/v1/workflows/minimax-h3-unified/jobs",
                    "method": "POST",
                }
            ],
        }
    )


def submission(**overrides: object) -> JobSubmission:
    values: dict[str, object] = {
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
    values.update(overrides)
    return JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input=values,
    )


def test_expands_typed_axes_repeats_and_incrementing_seeds():
    spec = SharedSweepSpec(
        base=submission(),
        axes=(SharedSweepAxis(binding="steps", values=(10, 20)),),
        repeats=2,
        seed_strategy="increment",
    )

    expanded = expand_shared_sweep(document(), spec)

    assert [(item.input["steps"], item.input["seed"]) for item in expanded] == [
        (10, 42),
        (10, 43),
        (20, 42),
        (20, 43),
    ]


def test_rejects_duplicate_invisible_and_invalid_axes_before_expansion():
    with pytest.raises(ValueError, match="duplicate"):
        SharedSweepSpec(
            base=submission(),
            axes=(
                SharedSweepAxis(binding="steps", values=(10, 20)),
                SharedSweepAxis(binding="steps", values=(30, 40)),
            ),
        )

    hidden = SharedSweepSpec(
        base=submission(),
        axes=(SharedSweepAxis(binding="steps", values=(10, 20)),),
    )
    with pytest.raises(ValueError, match="not visible"):
        expand_shared_sweep(document(steps_visible_for="first_last_frame"), hidden)

    invalid = SharedSweepSpec(
        base=submission(),
        axes=(SharedSweepAxis(binding="steps", values=(0, 20)),),
    )
    with pytest.raises(ValueError, match="steps"):
        expand_shared_sweep(document(), invalid)


def test_random_seed_strategy_is_bounded_and_unique():
    selected = iter([4, 4, 7])
    spec = SharedSweepSpec(
        base=submission(),
        repeats=2,
        seed_strategy="random",
    )

    expanded = expand_shared_sweep(
        document(),
        spec,
        randbelow=lambda _span: next(selected),
    )

    assert [item.input["seed"] for item in expanded] == [4, 7]


def test_shared_sweep_request_uses_sdui_bindings():
    from h3lab.api.schemas import SharedSweepRequest

    request = SharedSweepRequest.model_validate(
        {
            "base": submission().model_dump(mode="json", by_alias=True),
            "axes": [{"binding": "steps", "values": [10, 20]}],
            "repeats": 2,
            "seed_strategy": "increment",
            "skip_duplicates": True,
        }
    )

    assert request.to_spec().axes[0].binding == "steps"


def test_lab_previews_shared_submissions_with_existing_duplicate_counts(settings, stub):
    from h3lab.engine.lab import Lab

    lab = Lab(settings, client=stub, start_worker=False)
    try:
        spec = SharedSweepSpec(
            base=submission(),
            axes=(SharedSweepAxis(binding="steps", values=(10, 20)),),
        )
        first = lab.preview_shared_sweep(document(), spec)
        assert first.count == 2
        assert first.combinations == 2
        assert first.new_count == 2

        lab.runs.create(first.items[0].config)
        second = lab.preview_shared_sweep(document(), spec)
        assert second.new_count == 1
        assert second.duplicate_count == 1
        assert second.items[0].existing_run_id
    finally:
        lab.close()


def test_lab_validates_the_whole_shared_sweep_before_queuing(settings, stub):
    from h3lab.engine.lab import Lab

    lab = Lab(settings, client=stub, start_worker=False)
    calls: list[tuple[int, str]] = []

    def enqueue_shared(_document, item, *, request_key, count=1):
        calls.append((item.input["steps"], request_key))
        return []

    lab.enqueue_shared = enqueue_shared  # type: ignore[method-assign]
    try:
        valid = SharedSweepSpec(
            base=submission(),
            axes=(SharedSweepAxis(binding="steps", values=(10, 20)),),
        )
        lab.run_shared_sweep(document(), valid, request_key="sweep-key")
        assert calls == [(10, "sweep-key:0"), (20, "sweep-key:1")]

        invalid = SharedSweepSpec(
            base=submission(),
            axes=(SharedSweepAxis(binding="steps", values=(10, 500)),),
        )
        calls.clear()
        with pytest.raises(ValueError, match="steps"):
            lab.run_shared_sweep(document(), invalid, request_key="invalid-key")
        assert calls == []
    finally:
        lab.close()


def test_sweep_routes_dispatch_pinned_submissions_through_the_shared_document():
    from h3lab.api.routes.runs import preview_sweep
    from h3lab.api.schemas import SharedSweepRequest

    expected = object()

    class Shared:
        def get_generation_document(self):
            return document()

    class Lab:
        def preview_shared_sweep(self, resolved_document, spec):
            assert resolved_document == document()
            assert spec.base == submission()
            return expected

    body = SharedSweepRequest(
        base=submission(),
        axes=[{"binding": "steps", "values": [10, 20]}],
    )

    assert preview_sweep(Lab(), body, Shared()) is expected  # type: ignore[arg-type]
